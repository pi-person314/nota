"""Runner for the LLM command-interpretation eval suite: scores the real
orchestrator (`nota.orchestrator.loop.run_command`) against
`evals.dataset.CASES`.

Live invocation (talks to the real Anthropic API -- costs real tokens):

    cd backend
    venv/Scripts/python -m evals.run_evals

Requires `ANTHROPIC_API_KEY` in the environment (see README.md). `--limit N`
and `--category NAME` run a cheaper subset. `run_case`/`run_suite` are also
the entry points `tests/evals/` uses to exercise the full runner machinery
against a scripted fake Anthropic client, with no API key and no
subprocess -- see that package for how the seam is patched.

A case can fail to be scored at all: if the orchestrator/LLM layer itself
errors out (a timeout or API failure -- `result["error"]`, e.g.
`LLM_TIMEOUT`/`LLM_ERROR`), the case never meaningfully exercised the
model. That is tracked as a third outcome, "errored", distinct from
passed/failed, both in `CaseResult`/`SuiteReport` and in the exit code:

    0 - every scored case passed, no orchestrator/LLM errors
    1 - at least one case failed (the model produced the wrong tool
        calls/response) and no case errored
    2 - ANTHROPIC_API_KEY missing; the run never started
    3 - at least one case errored (orchestrator/LLM failure); the pass/
        fail counts for this run are not a trustworthy signal -- see the
        error breakdown printed to the console and `error_counts` in the
        JSON report
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from nota.orchestrator import loop

from .dataset import CASES, CATEGORIES
from .dispatcher import RecordingDispatcher
from .fixture import configure_isolated_env, register_fresh_score
from .scoring import score_expectation

RESULTS_DIR = Path(__file__).resolve().parent / "results"


@dataclass
class CaseResult:
    id: str
    category: str
    transcript: str
    passed: bool
    detail: str
    expected: dict
    actual_calls: list
    confirmation: str
    needs_clarification: bool
    error: str | None = None


@dataclass
class SuiteReport:
    generated_at: str
    total: int
    passed: int
    failed: int
    errored: int
    error_counts: dict
    by_category: dict
    results: list = field(default_factory=list)


def case_outcome(result: CaseResult) -> str:
    """Classify a scored case into exactly one of three buckets.

    A case whose orchestrator/LLM call itself errored out (a timeout or
    API failure, surfaced via `CaseResult.error`) never meaningfully
    exercised the model -- it is neither a pass nor a model failure, so it
    is bucketed separately from both and must not be counted toward
    either.
    """
    if result.error:
        return "errored"
    return "passed" if result.passed else "failed"


def run_case(case: dict, dispatcher: RecordingDispatcher, cfg) -> CaseResult:
    """Run one dataset case to completion and score it.

    Registers a fresh copy of the fixture score, replays any
    `setup_transcripts` through it (to build server-side `CommandLog`
    history for context-carryover cases), then runs the scored transcript.
    Only tool calls made while handling the scored transcript -- not the
    setup transcripts -- count toward the result.

    If the orchestrator reports an `error` (an LLM timeout or API
    failure), the case is never scored against its expectation -- it is
    marked failed with a detail describing the error rather than being
    graded on whatever partial tool calls happened before the failure, so
    an outage can never be mistaken for the model getting the case wrong.
    """
    score_id = register_fresh_score(cfg, name=f"Eval: {case['id']}")

    for setup_transcript in case.get("setup_transcripts", []):
        loop.run_command(score_id, setup_transcript)

    start = len(dispatcher.calls)
    result = loop.run_command(score_id, case["transcript"])
    actual_calls = dispatcher.calls[start:]

    error = result.get("error")
    if error:
        passed, detail = False, f"orchestrator/LLM error before scoring: {error}"
    else:
        passed, detail = score_expectation(case["expectation"], actual_calls, result)

    return CaseResult(
        id=case["id"],
        category=case["category"],
        transcript=case["transcript"],
        passed=passed,
        detail=detail,
        expected=case["expectation"],
        actual_calls=[{"tool": name, "args": args} for name, args in actual_calls],
        confirmation=result.get("confirmation", ""),
        needs_clarification=result.get("needs_clarification", False),
        error=error,
    )


def run_suite(cases: list[dict], dispatcher: RecordingDispatcher, cfg) -> SuiteReport:
    results = [run_case(one_case, dispatcher, cfg) for one_case in cases]

    by_category: dict[str, dict] = {}
    error_counts: dict[str, int] = {}
    passed = failed = errored = 0

    for r in results:
        bucket = by_category.setdefault(r.category, {"total": 0, "passed": 0, "failed": 0, "errored": 0})
        bucket["total"] += 1
        outcome = case_outcome(r)
        bucket[outcome] += 1
        if outcome == "passed":
            passed += 1
        elif outcome == "failed":
            failed += 1
        else:
            errored += 1
            error_counts[r.error] = error_counts.get(r.error, 0) + 1

    return SuiteReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total=len(results),
        passed=passed,
        failed=failed,
        errored=errored,
        error_counts=error_counts,
        by_category=by_category,
        results=[asdict(r) for r in results],
    )


def _select_cases(limit: int | None, category: str | None) -> list[dict]:
    cases = CASES
    if category:
        cases = [c for c in cases if c["category"] == category]
        if not cases:
            raise SystemExit(
                f"No cases in category '{category}'. Known categories: {', '.join(CATEGORIES)}"
            )
    if limit is not None:
        cases = cases[:limit]
    return cases


def exit_code_for(report: SuiteReport) -> int:
    """Map a completed suite run to a process exit code (see the module
    docstring for the full convention). Errored cases always take priority
    over failed ones -- once any case erred out, this run's pass/fail
    counts are not a trustworthy signal, regardless of how the rest of the
    suite scored.
    """
    if report.errored:
        return 3
    return 0 if report.failed == 0 else 1


def _format_error_breakdown(error_counts: dict) -> str:
    return ", ".join(f"{code} x{count}" for code, count in sorted(error_counts.items()))


def _print_table(report: SuiteReport) -> None:
    print()
    print(f"{'category':<24} {'passed':>8} {'failed':>8} {'errored':>8} {'total':>8} {'rate':>8}")
    print("-" * 68)
    for cat in sorted(report.by_category):
        bucket = report.by_category[cat]
        scored = bucket["passed"] + bucket["failed"]
        rate = bucket["passed"] / scored * 100 if scored else 0.0
        print(
            f"{cat:<24} {bucket['passed']:>8} {bucket['failed']:>8} {bucket['errored']:>8} "
            f"{bucket['total']:>8} {rate:>7.1f}%"
        )
    print("-" * 68)
    scored_total = report.passed + report.failed
    overall_rate = report.passed / scored_total * 100 if scored_total else 0.0
    print(
        f"{'OVERALL':<24} {report.passed:>8} {report.failed:>8} {report.errored:>8} "
        f"{report.total:>8} {overall_rate:>7.1f}%"
    )
    print()

    summary = f"{report.passed} passed, {report.failed} failed"
    if report.errored:
        summary += f", {report.errored} errored ({_format_error_breakdown(report.error_counts)})"
    print(summary)
    print()

    errors = [r for r in report.results if r.get("error")]
    if errors:
        print(f"{len(errors)} errored case(s) -- orchestrator/LLM failure, not scored against expectation:\n")
        for r in errors:
            print(f"ERROR [{r['category']}] {r['id']}: \"{r['transcript']}\" -- {r['error']}")
        print()

    failures = [r for r in report.results if not r["passed"] and not r.get("error")]
    if failures:
        print(f"{len(failures)} failing case(s):\n")
        for r in failures:
            print(f"FAIL [{r['category']}] {r['id']}: \"{r['transcript']}\"")
            print(f"    expected: {r['expected']}")
            print(f"    actual tool calls: {r['actual_calls']}")
            print(f"    confirmation: {r['confirmation']!r}")
            print(f"    reason: {r['detail']}")
            print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Nota LLM command eval suite.",
        epilog=(
            "Exit codes: 0 = every scored case passed, no orchestrator/LLM errors; "
            "1 = at least one case failed and none errored; "
            "2 = ANTHROPIC_API_KEY missing, run never started; "
            "3 = at least one case errored (orchestrator/LLM failure) -- pass/fail "
            "counts for this run are not a trustworthy signal, see the error "
            "breakdown in the console output and error_counts in the JSON report."
        ),
    )
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N selected cases.")
    parser.add_argument(
        "--category", type=str, default=None, choices=CATEGORIES, help="Only run cases in this category."
    )
    args = parser.parse_args(argv)

    # Load backend/.env into the process environment the same way the rest
    # of the app expects it to be available (existing process env vars take
    # precedence -- this never overrides an already-set key).
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set. The eval suite calls the real Claude API and "
            "needs it in the environment (backend/.env or the process env). "
            "See backend/evals/README.md.",
            file=sys.stderr,
        )
        return 2

    cases = _select_cases(args.limit, args.category)
    print(f"Running {len(cases)} case(s)...")

    with tempfile.TemporaryDirectory(prefix="nota-evals-") as tmp_dir:
        cfg = configure_isolated_env(tmp_dir)

        # A private MCPClientManager (not the process singleton) pointed at
        # this run's isolated storage/db, so the eval run never touches
        # real data and cleans up its own subprocess when done.
        from nota.orchestrator.mcp_client import MCPClientManager

        manager = MCPClientManager()
        manager.configure(database_url=cfg.database_url, score_storage_dir=cfg.score_storage_dir)
        dispatcher = RecordingDispatcher(manager)
        loop._get_dispatcher = lambda: dispatcher

        try:
            report = run_suite(cases, dispatcher, cfg)
        finally:
            manager.shutdown()
            # Release the SQLite file handle before the TemporaryDirectory
            # context manager tries to remove it below -- on Windows a
            # still-open sqlite3 connection makes that cleanup raise
            # PermissionError even though the run itself succeeded.
            from nota import db as db_module

            db_module.get_engine().dispose()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)

    _print_table(report)
    print(f"Full report written to {out_path}")

    if report.errored:
        print(
            f"WARNING: {report.errored} case(s) errored due to an orchestrator/LLM failure "
            f"({_format_error_breakdown(report.error_counts)}). This run's pass/fail counts do "
            "not reflect model quality for those cases -- rerun before trusting the result.",
            file=sys.stderr,
        )

    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
