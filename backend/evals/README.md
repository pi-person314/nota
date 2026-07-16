# Nota LLM Command Eval Suite

Scores the real command orchestrator (`nota.orchestrator.loop.run_command`)
against a dataset of 55+ spoken-command transcripts with known expected
tool-call behavior (`evals/dataset.py`).

## Running live

Requires `ANTHROPIC_API_KEY` in the environment (loaded from `backend/.env`
or the process env, the same way the rest of the app reads it). This talks
to the real Claude API and costs real tokens: each case is one short
command (at most a couple of tool-call iterations), so a full run is
roughly 60-70 short Claude calls.

```
cd backend
venv/Scripts/python -m evals.run_evals
```

Flags:

- `--limit N` -- only run the first N selected cases (applied after
  `--category`), for a cheap smoke run.
- `--category NAME` -- only run cases in one category. See `CATEGORIES` in
  `evals/dataset.py` for the full list (`simple`, `synonyms`, `ranges`,
  `compound`, `transcription_artifacts`, `context_carryover`, `undo_redo`,
  `out_of_range`, `ambiguous`).

Each run builds a fresh temporary SQLite database and score storage
directory (removed automatically when the run finishes), registers a fresh
copy of the sixteen-measure fixture score per case (or per
`setup_transcripts` chain), and drives the real MCP stdio tool server the
app uses in production. This is an end-to-end integration check of the
real system prompt against the real tools, not a mock.

A JSON report is written to `evals/results/<timestamp>.json` (per-case
pass/fail with expected vs. actual detail, per-category and overall pass
rates) and a console table is printed. The process exits non-zero if any
case failed.

## How scoring works

Each case's `expectation` is one of three shapes (see `evals/scoring.py`
for the exact matching logic):

- **`tool_calls`** -- an ordered-or-unordered list of `{tool, args}`
  entries, where `args` is matched as a *subset* of the actual call's
  arguments (extra actual keys, e.g. the injected `score_id`, are ignored;
  numeric comparisons tolerate float noise; string comparisons are
  case-insensitive). Unordered by default, so a compound command's two
  tool calls can come back in either order; pass `ordered=True` via
  `expect_tools(..., ordered=True)` when sequence matters. The actual call
  count must match exactly -- an unexpected extra tool call is a failure.
- **`no_tools` + `expect_clarification_or_correction`** -- passes when zero
  tools were called and Claude's final response has non-empty text (a
  clarifying question for a genuinely ambiguous command, or a
  conversational correction for an out-of-range one).
- **`any_of`** -- a list of alternative expectations (of either shape
  above); passes if any one alternative matches. Used for cases with more
  than one acceptable phrasing, e.g. a hairpin call with
  `direction="decrescendo"` or `direction="diminuendo"` -- both are valid
  synonyms the tool itself accepts, so either is a correct interpretation.

Cases may also set `setup_transcripts`: a list of transcripts run through
the same score (and therefore the same server-side `CommandLog` history)
before the scored transcript, for testing context carry-over ("beat 3"
with no measure mentioned, "same thing at measure 15"). Only the tool
calls made while handling the *scored* transcript count toward that case's
result.

## Validating the harness (no API key needed)

`backend/tests/evals/` runs in the normal test suite and never touches the
real API:

- `test_dataset_schema.py` validates every case's shape (required fields,
  a known category, exactly one expectation mode) and confirms every tool
  name referenced anywhere in the dataset is actually registered on the
  MCP server.
- `test_runner_matching.py` runs the full runner (`evals.run_evals.run_case`)
  against a scripted fake Anthropic client (the same fake used by
  `tests/orchestrator/`) and a direct-dispatch tool backend (no
  subprocess), proving the matching logic itself is correct: exact
  matches, args-subset mismatches, the ranged-vs-per-note distinction,
  `no_tools` pass/fail, `any_of`, and `setup_transcripts` context flow.

## Adding a case

Add an entry to `CASES` in `evals/dataset.py` using the `case(...)` /
`tc(...)` / `expect_tools(...)` / `expect_no_tools()` / `expect_any_of(...)`
helpers defined at the top of that file. Pick an existing `category` (see
`CATEGORIES`) or add a new one there too. Keep measure/beat references
within the fixture's 16 measures x 4 beats (see `evals/fixture.py`) unless
the case is deliberately testing out-of-range behavior.
