# NOTA — Backend Specification v2 (Revised)

This revision supersedes the backend portions of the original spec. It addresses architectural flaws found in review: stateful MCP server (broken for multi-user), missing persistence layer, missing agentic tool-calling loop, broken change-highlighting assumption, missing score context for the LLM, missing validation/error contracts, unhandled range commands, concurrency races, and unbiased Whisper transcription. The backend is now Python/Flask with music21, which eliminates the hand-written beat-resolution engine entirely.

Frontend (React + Verovio) is unchanged and covered by the frontend spec.

---

## 1. Summary of Changes from v1

| # | v1 Problem | v2 Fix |
|---|-----------|--------|
| 1 | MCP server held one MusicXML DOM in memory — breaks with multiple users/scores, loses state on restart | Stateless MCP server: every tool call includes `score_id`; server loads → modifies → persists per call |
| 2 | No database; no way to store users, scores, metadata, or undo history | SQLite via SQLAlchemy (swap to Postgres later without code changes) |
| 3 | Data flow assumed a single tool call per command | Explicit agentic loop: Claude ↔ tools until Claude emits a final text response (max 8 iterations) |
| 4 | Assumed Verovio preserves `xml:id` — untrue for elements the tools create | Every tool injects a generated `xml:id` on every element it creates; those IDs are returned for highlighting |
| 5 | Undo stack in MCP server memory | DB-backed snapshot table keyed by score, survives restarts |
| 6 | Claude had no knowledge of the score (measure count, time sig, parts) | Score metadata extracted at upload, injected into system prompt every request |
| 7 | No tool input validation or error contract | All tools validate bounds; structured error responses Claude can act on |
| 8 | Range commands ("staccato on all notes in bars 8–12") required dozens of tool calls | Tools accept optional ranges; one call applies to all matching notes |
| 9 | Concurrent commands on the same score could race | Per-score mutex; second command waits or returns 409 |
| 10 | Whisper transcription unbiased toward musical vocabulary | Whisper `prompt` parameter seeded with musical term lexicon |
| 11 | TypeScript backend required hand-rolling beat/offset resolution | Python + music21: offsets, divisions, pickups, voices, chords, grace notes handled natively |
| 12 | System prompt self-contradictory; stale model string; no .mxl decompression; XXE risk unaddressed | All fixed below |

---

## 2. Technology Stack (Backend)

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web framework | Flask + Flask-CORS | REST API |
| ORM / DB | SQLAlchemy + SQLite (dev) / Postgres (prod) | Users, scores, snapshots, sessions |
| Auth | Flask session cookies + bcrypt (or Authlib for Google OAuth) | Login/signup |
| MusicXML engine | music21 | Parse, query, modify MusicXML |
| Safe XML parsing | defusedxml | Prevent XXE / entity-expansion attacks on upload |
| MCP server | Python MCP SDK (`mcp` package), stdio transport | Notation tools |
| LLM | Anthropic Python SDK, model `claude-sonnet-4-6` | Command interpretation + tool orchestration |
| STT | OpenAI Whisper API (`whisper-1`) with vocabulary prompt | Voice → text |
| File storage | Local filesystem `data/scores/{score_id}.musicxml` (S3-compatible later) | Score content |

**Why music21 matters:** the single hardest module in v1 was the location resolver — converting "measure 12 beat 3" into an XML insertion point while handling `<divisions>`, `<backup>`/`<forward>`, pickup measures, mid-piece meter changes, chords, and grace notes. music21 does all of this natively: `score.parts[0].measure(12)` returns the measure; every note has an `.offset` in quarter-note units; `beat` properties account for pickups and meter changes. v2 deletes the entire custom engine.

---

## 3. Revised Architecture

```
┌──────────────────────────────────────────────┐
│  Frontend (React + Verovio)  — unchanged     │
└───────────────────┬──────────────────────────┘
                    │ REST (session cookie auth)
                    ▼
┌──────────────────────────────────────────────┐
│  Flask Backend                                │
│  ┌─────────────┐ ┌─────────────────────────┐  │
│  │ Auth routes │ │ Score routes (CRUD)     │  │
│  └─────────────┘ └─────────────────────────┘  │
│  ┌─────────────┐ ┌─────────────────────────┐  │
│  │ Whisper svc │ │ Command orchestrator    │  │
│  │ (+ lexicon  │ │ • builds system prompt  │  │
│  │  prompt)    │ │   w/ score metadata     │  │
│  └─────────────┘ │ • agentic loop w/ Claude│  │
│                  │ • per-score lock        │  │
│                  └───────────┬─────────────┘  │
│                              │ MCP client     │
└──────────────────────────────┼────────────────┘
                               │ stdio
                  ┌────────────▼─────────────┐
                  │ MCP Server (STATELESS)   │
                  │ every call: score_id →   │
                  │ load from storage →      │
                  │ music21 modify →         │
                  │ inject xml:id →          │
                  │ snapshot + persist →     │
                  │ return changed IDs       │
                  └────────────┬─────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │ SQLite + data/scores/    │
                  │ users, scores, snapshots │
                  └──────────────────────────┘
```

The MCP server and Flask share the same storage layer (a small `storage.py` module both import). The MCP server never caches a document across calls.

> **Design note — why keep MCP at all?** Since backend and tools are one codebase, direct function dispatch would be simpler and slightly faster. MCP is retained deliberately: it keeps the tool layer independently testable, lets any MCP-capable client (e.g., Claude Desktop) drive the same tools, and is a stated goal of the project. The stateless design removes the main cost of that choice.

---

## 4. Data Model

```python
class User(Base):
    id: str            # uuid
    name: str
    email: str         # unique
    password_hash: str # bcrypt; null if OAuth-only
    created_at: datetime

class Score(Base):
    id: str            # uuid
    user_id: str       # FK -> User
    name: str          # display name (renameable)
    part_name: str | None
    is_starred: bool = False
    file_path: str     # data/scores/{id}.musicxml
    # Metadata extracted once at upload (see §6):
    measure_count: int
    has_pickup: bool
    parts_json: str    # JSON list of {id, name}
    time_signatures_json: str  # JSON list of {measure, ts}
    created_at: datetime
    last_opened_at: datetime
    last_modified_at: datetime

class Snapshot(Base):
    id: int            # autoincrement — ordering
    score_id: str      # FK -> Score
    xml: str           # full MusicXML (zlib-compressed bytes)
    label: str         # e.g. 'add_dynamic f m12 b1'
    created_at: datetime

class CommandLog(Base):     # powers conversation history + history chips
    id: int
    score_id: str
    transcript: str
    tools_called_json: str
    confirmation: str
    created_at: datetime
```

**Undo/redo:** before any tool mutates a score, the current XML is written to `Snapshot`. Undo pops the latest snapshot into the live file (pushing the current state onto a redo list tracked by a `redo_pointer` on the score or a parallel table). Cap snapshots at 50 per score, evicting oldest. Snapshots are compressed; a 500 KB score compresses to ~30 KB, so 50 snapshots ≈ 1.5 MB per score — acceptable.

---

## 5. Stateless MCP Server

Every tool signature gains a required `score_id` parameter. Per-call lifecycle:

```python
def run_tool(score_id: str, mutate: Callable[[m21.stream.Score], list[str]]) -> ToolResult:
    path = storage.path_for(score_id)
    if path is None:
        return ToolResult.error("SCORE_NOT_FOUND", f"No score with id {score_id}")
    score = m21.converter.parse(path)          # load
    storage.save_snapshot(score_id, path)      # snapshot BEFORE mutation
    changed_ids = mutate(score)                # modify + inject xml:ids
    score.write('musicxml', fp=path)           # persist
    storage.touch_modified(score_id)
    return ToolResult.ok(changed_ids)
```

**xml:id injection (fixes flaw #4):** music21 objects have an `.id` attribute that its MusicXML writer exports as `xml:id` when set. Every created element gets `f"nota-{uuid4().hex[:8]}"`. These IDs are returned in `changed_element_ids`; Verovio carries `xml:id` through to the SVG, so the frontend can select and highlight exactly the new elements. Tools must also verify after write-out that the ID survived serialization (unit-tested per element type; for the rare element music21 won't carry an id through, fall back to returning the parent note's id).

**Performance note:** parse + serialize per call costs roughly 100–500 ms for a typical single part. Within the 3 s latency budget this is fine and buys total correctness. If it ever becomes the bottleneck, add an LRU cache keyed by `(score_id, file_mtime)` — an optimization, not a requirement.

**Structured results (fixes flaw #7):** every tool returns JSON:

```json
// success
{ "success": true,
  "changed_element_ids": ["nota-a1b2c3d4"],
  "summary": "Added f at measure 12, beat 1" }

// failure — machine-readable so Claude can recover conversationally
{ "success": false,
  "error_code": "MEASURE_OUT_OF_RANGE",
  "message": "Measure 200 does not exist. The score has 68 measures." }
```

Error codes: `SCORE_NOT_FOUND`, `MEASURE_OUT_OF_RANGE`, `BEAT_OUT_OF_RANGE` (message includes the measure's actual beat count from its time signature), `NO_NOTE_AT_POSITION` (message includes nearest note positions), `PART_NOT_FOUND` (message lists valid parts), `INVALID_ENUM_VALUE`, `NOTHING_TO_REMOVE`, `NOTHING_TO_UNDO`, `NOTHING_TO_REDO`.

Validation order inside every tool: part exists → measure in `[1, measure_count]` (or 0 with pickup) → beat within the measure's meter → target note exists where required.

---

## 6. Score Metadata & Upload Pipeline

`POST /api/scores/upload`:

1. Reject files > 10 MB. Accept `.musicxml`, `.xml`, `.mxl`.
2. **.mxl decompression:** `.mxl` is a zip; read `META-INF/container.xml` to find the rootfile, extract it. Reject zip bombs (uncompressed size cap 50 MB).
3. **Safe parse:** run through `defusedxml` first to reject XXE/entity-expansion payloads, then hand to music21.
4. Extract and store metadata on the `Score` row:
   - `measure_count`, `has_pickup` (music21: first measure `paddingLeft > 0` / measure number 0)
   - parts list `[{id, name}]`
   - time signature map `[{measure: 1, ts: "4/4"}, {measure: 33, ts: "3/4"}]`
   - initial `part_name`, display name from `<work-title>`/`<movement-title>`, falling back to filename
5. Persist canonical XML to `data/scores/{id}.musicxml` (always store uncompressed canonical form, regardless of upload format).
6. Return `ScoreSummary` JSON.

This metadata is cheap to read on every command and powers the system prompt (§7) — Claude always knows the score's shape without the backend re-parsing anything.

---

## 7. Command Orchestrator

The heart of the backend: `POST /api/scores/:id/command`.

### 7.1 Per-score lock (fixes flaw #9)

A process-wide `dict[score_id, threading.Lock]`. The handler acquires the score's lock with a 15 s timeout; on timeout return `409 {"error": "COMMAND_IN_PROGRESS"}` and let the frontend surface "still working on the last command." (If the backend ever runs multi-process, move this to a DB advisory lock — noted, not needed for MVP.)

### 7.2 System prompt (fixes flaws #6 and #12)

Built fresh per request from score metadata:

```
You are Nota, a voice-driven music notation assistant for orchestral musicians.

CURRENT SCORE:
- Title: {name}
- Parts: {parts list}
- Measures: {measure_count}{" (plus a pickup measure, numbered 0)" if has_pickup}
- Time signatures: {ts map, e.g. "4/4 from m.1, 3/4 from m.33"}

Interpret the musician's spoken command and call the appropriate notation tools.
Commands come from speech-to-text and may contain transcription artifacts
("sfor zando" = sforzando, "measure to" may mean "measure 2").

RULES:
1. Prefer acting over asking. Call tools when the command specifies a location;
   ask a brief clarifying question ONLY when the location or marking is genuinely
   ambiguous or missing.
2. Accept standard synonyms: bar = measure, cresc = crescendo, dim/decresc =
   decrescendo, stacc = staccato, marc = marcato.
3. Validate against the score: if the user references a measure beyond
   {measure_count}, don't call a tool — tell them briefly.
4. Compound commands require multiple tool calls; ranges ("staccato in bars
   8 to 12") use a single ranged tool call, not per-note calls.
5. If a beat is given with no measure, use the most recently mentioned measure
   from the conversation.
6. "undo", "go back", "never mind" → the undo tool.
7. If a tool returns an error, relay the useful part conversationally
   ("That measure only has 3 beats — did you mean beat 3?").
8. After acting, respond with one short spoken confirmation, e.g.
   "Added forte at measure 12." It will be read aloud via TTS.
```

Rule 1 resolves the v1 contradiction between "always call a tool" and "ask for clarification."

### 7.3 Agentic loop (fixes flaw #3)

```python
def run_command(score_id, transcript, history):
    messages = history[-12:] + [{"role": "user", "content": transcript}]
    changed_ids, tools_called = [], []

    for _ in range(8):                                   # iteration cap
        resp = anthropic.messages.create(
            model="claude-sonnet-4-6",
            system=build_system_prompt(score_id),
            messages=messages,
            tools=mcp_tool_schemas(),                    # cached from MCP list_tools
            max_tokens=1000,
        )
        messages.append({"role": "assistant", "content": resp.content})

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            break                                        # final text answer

        results = []
        for tu in tool_uses:
            out = mcp_client.call_tool(tu.name, {**tu.input, "score_id": score_id})
            tools_called.append(tu.name)
            if out.get("success"):
                changed_ids += out.get("changed_element_ids", [])
            results.append({"type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": json.dumps(out)})
        messages.append({"role": "user", "content": results})

    confirmation = extract_final_text(messages)
    log_command(score_id, transcript, tools_called, confirmation)
    return {
        "musicxml": storage.read(score_id),
        "changed_element_ids": changed_ids,
        "confirmation": confirmation,
        "tools_called": tools_called,
        "needs_clarification": len(tools_called) == 0 and bool(confirmation),
    }
```

Key points: tool results are fed back so Claude can chain and self-correct; the loop is capped; `needs_clarification` lets the frontend render Claude's question and keep the mic hot; conversation history is server-side via `CommandLog` (last 12 turns reconstructed), so "same thing at measure 15" works without the frontend managing history.

### 7.4 Timeouts and failure handling

- Whisper call: 20 s timeout → `502 TRANSCRIPTION_FAILED`.
- Empty/garbage transcript (< 2 chars): `422 EMPTY_TRANSCRIPT` — frontend prompts to try again, no Claude call wasted.
- Claude call: 30 s timeout per iteration → return partial state with `"error": "LLM_TIMEOUT"`; any tools already executed remain applied (their snapshots exist, user can undo).
- MCP tool exception: caught, returned to Claude as an error tool_result (Claude decides whether to retry or explain); never crashes the loop.

---

## 8. Tool Catalog (v2 deltas only)

All ten v1 tools survive with these changes:

1. **Every tool:** required `score_id: string`; structured success/error contract (§5); validation order (§5); xml:id injection.
2. **`add_articulation` gains ranges (fixes flaw #8):** optional `end_measure` / `end_beat`. When present, the articulation is applied to every note whose offset lies within [start, end], one tool call, all note IDs returned. "Staccato on every note in measures 8 through 12" = one call.
3. **`add_dynamic` de-duplication:** if an identical dynamic already exists at the location, return success with `"summary": "f already present at measure 12 beat 1"` and no change — voice commands get repeated when users think they weren't heard.
4. **`remove_notation` disambiguation:** if multiple candidates match, return an error listing them (`"Found a slur and a staccato at m.12 b.1 — which one?"`) so Claude can ask.
5. **`undo`/`redo`:** operate on the `Snapshot` table; return the full restored `changed_element_ids: []` plus `"summary": "Undid: add_dynamic f m12 b1"` using the snapshot label.

music21 implementation notes per tool family:

- Dynamics: `m21.dynamics.Dynamic('f')` inserted at `measure.insert(offset, dyn)`.
- Slurs: `m21.spanner.Slur(note_start, note_end)` appended to the part; music21 emits correct start/stop MusicXML.
- Hairpins: `m21.dynamics.Crescendo/Diminuendo` spanners.
- Articulations: append to `note.articulations` (`m21.articulations.Staccato()` etc.); bowings are in `m21.articulations` too (`DownBow`, `UpBow`).
- Text/tempo/rehearsal: `m21.expressions.TextExpression`, `m21.tempo.MetronomeMark`, `m21.expressions.RehearsalMark`.
- Ornaments: `note.expressions.append(m21.expressions.Trill())` etc.

---

## 9. Whisper Service (fixes flaw #10)

```python
LEXICON_PROMPT = (
    "Musical notation commands: measure, bar, beat, crescendo, decrescendo, "
    "diminuendo, sforzando, fortissimo, pianissimo, mezzo forte, mezzo piano, "
    "staccato, staccatissimo, marcato, tenuto, legato, slur, accent, fermata, "
    "trill, mordent, pizzicato, arco, down-bow, up-bow, sul ponticello, "
    "rehearsal mark, ritardando, accelerando, a tempo, hairpin, dolce."
)

def transcribe(audio_bytes) -> str:
    return openai.audio.transcriptions.create(
        model="whisper-1", file=audio_bytes,
        prompt=LEXICON_PROMPT, language="en",
    ).text
```

The `prompt` parameter biases decoding toward these tokens — the cheapest accuracy win available. Numbers still mis-transcribe occasionally ("measure to" for "measure 2"); the system prompt tells Claude to expect this, which handles it at the interpretation layer rather than the STT layer.

---

## 10. API Endpoints (Backend, v2)

| Method | Endpoint | Notes |
|--------|----------|-------|
| POST | /api/auth/signup | bcrypt hash; sets session cookie |
| POST | /api/auth/login | |
| POST | /api/auth/logout | |
| GET | /api/auth/me | |
| GET | /api/scores | `?sort=last_opened|last_modified|date_uploaded|name_asc|name_desc&starred=true` |
| POST | /api/scores/upload | Pipeline in §6 |
| GET | /api/scores/:id | Returns XML + metadata; updates `last_opened_at` |
| PATCH | /api/scores/:id | `{name?, is_starred?}` |
| DELETE | /api/scores/:id | Deletes file, snapshots, logs |
| GET | /api/scores/:id/export | `Content-Disposition: attachment` |
| POST | /api/transcribe | audio/webm → `{text}` |
| POST | /api/scores/:id/command | §7; body `{text}` — history is server-side now |
| POST | /api/scores/:id/undo | Wraps the undo tool directly (no LLM round-trip for the toolbar button) |
| POST | /api/scores/:id/redo | Same |
| GET | /api/scores/:id/history | Command log for the history chips |

All `/api/scores/*` routes verify the session user owns the score (403 otherwise). API keys (Anthropic, OpenAI) live only in backend env vars, never sent to the client.

Note the direct undo/redo endpoints: the toolbar buttons shouldn't pay a 1–2 s LLM round-trip for a deterministic action. Voice-initiated undo still flows through Claude → undo tool.

---

## 11. Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| ANTHROPIC_API_KEY | Claude API | Yes |
| OPENAI_API_KEY | Whisper API | Yes |
| SECRET_KEY | Flask session signing | Yes |
| DATABASE_URL | Default `sqlite:///nota.db` | No |
| SCORE_STORAGE_DIR | Default `./data/scores` | No |
| MAX_UPLOAD_MB | Default 10 | No |
| PORT | Default 5001 | No |

---

## 12. Testing Strategy (v2 additions)

- **Tool unit tests (highest priority):** per tool × fixture matrix. Fixtures: 4/4 simple, 6/8 compound, pickup measure, mid-piece meter change, two-voice staff, chords, grace notes. Assert (a) music21 round-trip validity, (b) Verovio renders output without error, (c) **every returned xml:id exists in the serialized XML** — this is the regression test for the highlighting fix.
- **Error-path tests:** each error code in §5 has a test that triggers it and asserts the message contains the actionable detail (measure count, valid beat range, part list).
- **Orchestrator tests:** mock Anthropic client replaying scripted tool_use sequences; assert loop termination, tool_result feedback, iteration cap, lock behavior under two concurrent requests (second gets 409 or queues).
- **Snapshot tests:** mutate → undo → assert byte-equivalent XML; undo past empty stack → `NOTHING_TO_UNDO`; 51st snapshot evicts the 1st.
- **Upload security tests:** XXE payload rejected; zip bomb rejected; oversized file rejected; malformed .mxl (missing container.xml) rejected with a clean 422.
- **LLM eval set (unchanged from v1, expanded):** 50+ transcripts → expected tool calls, now including transcription-artifact cases ("add a for tay at measure twelve", "sfor zando on beat 2") and out-of-range cases where the expected behavior is a conversational correction with zero tool calls.

---

## 13. Revised Implementation Phases

**Phase 1 — Data layer + engine (Week 1–2)**
1. Flask app skeleton, SQLAlchemy models, auth routes (email/password).
2. Upload pipeline: .mxl decompression, defusedxml, music21 parse, metadata extraction, canonical storage.
3. Score CRUD endpoints incl. sort/star/rename/delete/export.
4. MCP server skeleton (stateless load/snapshot/mutate/persist harness from §5) + first 3 tools: `add_dynamic`, `draw_slur`, `add_articulation` (with ranges), with xml:id injection and the full error contract.
5. Tool unit tests against the fixture matrix.

**Phase 2 — Orchestration (Week 3)**
1. Command orchestrator: system prompt builder, agentic loop, per-score lock, timeouts.
2. `/command` endpoint with typed text (voice deferred); server-side history via CommandLog.
3. Direct undo/redo endpoints + snapshot machinery.
4. Wire to frontend: typed command → highlight changed elements end-to-end.

**Phase 3 — Voice (Week 4)**
1. `/transcribe` with lexicon prompt.
2. Full pipeline: record → transcribe → command → render.
3. `needs_clarification` handling (frontend shows Claude's question, keeps mic active).

**Phase 4 — Remaining tools + hardening (Week 5)**
1. `draw_hairpin`, `add_text_expression`, `add_tempo`, `add_rehearsal_mark`, `add_ornament`, `remove_notation`.
2. Error-path, concurrency, and upload-security test suites.
3. LLM eval run; system prompt tuning against the eval set.

**Phase 5 — Polish (Week 6)**
1. TTS readback (frontend, Web Speech API — no backend work).
2. Real-score testing with orchestral parts; fixture additions for anything that breaks.
3. Optional: Porcupine "hey nota" wake word (frontend); LRU parse cache if latency measurements warrant it.

---

## 14. Known Limitations (v2)

- **Single-process concurrency model:** the per-score lock is a threading lock; fine for Flask dev server / single gunicorn worker. Multi-worker deployment needs a DB advisory lock — deliberate deferral.
- **Full-XML transport:** each command returns the entire MusicXML. For a typical part (< 1 MB) over gzip this is fine; diff-based sync is a v2+ optimization.
- **music21 serialization fidelity:** music21's MusicXML writer normalizes some formatting (layout tags, ordering) on round-trip. Musical content is preserved, but the file won't be byte-identical to the upload. Acceptable; original upload could be retained separately if pristine export ever matters.
- **No note entry, single-part command context, no playback, English-only:** unchanged from v1, still deliberate.
