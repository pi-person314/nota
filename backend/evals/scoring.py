"""Matching logic that scores one case's expectation against the tool
calls the orchestrator actually made.

An expectation dict is one of three shapes (see `evals/dataset.py` for the
helpers that build them):

- `{"tool_calls": [...], "ordered": bool}` -- every entry is
  `{"tool": name, "args": {...}}`; `args` is matched as a *subset* of the
  actual call's arguments (extra actual keys, e.g. the injected
  `score_id`, are ignored). Unordered by default: any bijection between
  expected and actual calls that satisfies every pairing counts as a pass,
  so a compound command's calls can come back in either order.
- `{"no_tools": True, "expect_clarification_or_correction": bool}` --
  passes when no tools were called and, if the flag is set, Claude's final
  text response is non-empty.
- `{"any_of": [expectation, ...]}` -- passes if any one alternative
  (recursively, of either shape above) passes.
"""

from __future__ import annotations

from itertools import permutations
from typing import Any

NUMERIC_TOLERANCE = 1e-6


def _values_match(actual: Any, expected: Any) -> bool:
    is_num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if is_num(actual) and is_num(expected):
        return abs(actual - expected) <= NUMERIC_TOLERANCE
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().lower() == expected.strip().lower()
    return actual == expected


def args_subset_matches(actual_args: dict, expected_subset: dict) -> bool:
    """True if every key/value in `expected_subset` is present (and equal,
    with numeric tolerance and case-insensitive string comparison) in
    `actual_args`. Keys in `actual_args` not mentioned in
    `expected_subset` are ignored.
    """
    for key, expected_value in expected_subset.items():
        if key not in actual_args:
            return False
        if not _values_match(actual_args[key], expected_value):
            return False
    return True


def _single_call_matches(actual_call: tuple[str, dict], expected_call: dict) -> bool:
    name, args = actual_call
    if name != expected_call["tool"]:
        return False
    return args_subset_matches(args, expected_call.get("args", {}))


def match_tool_calls(
    actual_calls: list[tuple[str, dict]], expected_calls: list[dict], ordered: bool
) -> tuple[bool, str]:
    """Match a list of expected `{tool, args}` entries against the actual
    `(name, args)` calls the dispatcher recorded. Requires an exact count
    match -- an unexpected extra tool call is a failure, not a partial
    pass. Returns (passed, human-readable detail for failures).
    """
    if len(actual_calls) != len(expected_calls):
        return False, (
            f"expected {len(expected_calls)} tool call(s), got {len(actual_calls)}: "
            f"{[name for name, _ in actual_calls]}"
        )

    if ordered:
        for i, (actual, expected) in enumerate(zip(actual_calls, expected_calls)):
            if not _single_call_matches(actual, expected):
                return False, f"call {i}: expected {expected}, got {{'tool': '{actual[0]}', 'args': {actual[1]}}}"
        return True, ""

    n = len(expected_calls)
    for perm in permutations(range(n)):
        if all(_single_call_matches(actual_calls[i], expected_calls[perm[i]]) for i in range(n)):
            return True, ""
    return False, (
        f"no assignment of actual calls "
        f"{[{'tool': name, 'args': a} for name, a in actual_calls]} "
        f"matches expected {expected_calls}"
    )


def score_expectation(
    expectation: dict, actual_calls: list[tuple[str, dict]], llm_result: dict
) -> tuple[bool, str]:
    """Score one case. Returns (passed, detail) -- detail is empty on a
    pass and a human-readable explanation on a failure.
    """
    if expectation.get("any_of"):
        failures = []
        for alternative in expectation["any_of"]:
            passed, detail = score_expectation(alternative, actual_calls, llm_result)
            if passed:
                return True, ""
            failures.append(detail)
        return False, "no alternative matched: " + " | ".join(failures)

    if expectation.get("no_tools"):
        if actual_calls:
            return False, f"expected no tool calls, got {[name for name, _ in actual_calls]}"
        if expectation.get("expect_clarification_or_correction") and not (llm_result.get("confirmation") or "").strip():
            return False, "expected a clarifying question or conversational correction but got no text response"
        return True, ""

    expected_calls = expectation.get("tool_calls") or []
    ordered = bool(expectation.get("ordered", False))
    return match_tool_calls(actual_calls, expected_calls, ordered)
