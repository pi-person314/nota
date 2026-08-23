# Nota

**A hands-free music notation editor.** Say the marking the way you'd say it to a stand partner — *"crescendo from bar 5 to bar 8"*, *"third finger on beat 2"*, *"change the F in bar 3 to F sharp"* — and watch it land on the engraved score instantly. Built for musicians who mark parts mid-rehearsal with an instrument in their hands.

## Features

- **Voice commands in natural musical language** — no syntax to memorize. Bars, beats, dynamics, articulations, slurs, hairpins, ornaments, tempo marks, rehearsal marks, text expressions, and fingerings.
- **Real note editing** — add, delete, re-pitch, and re-time actual notes; transpose whole passages by named intervals. Deletions become rests (nothing shifts, as in engraved music).
- **"Hey Nota" wake word** — fully in-browser hot-word detection (openWakeWord on onnxruntime-web); nothing is streamed anywhere until you speak a command. The mic also auto-stops after silence.
- **Spoken confirmations** — Nota reads back what it did (mutable, and interruptible mid-sentence).
- **Engraved rendering** — Verovio renders the score as SVG, with just-changed elements highlighted, page navigation, and zoom.
- **MusicXML in and out** — upload `.musicxml` / `.mxl` / `.xml` from Sibelius, MuseScore, Finale, etc.; download standard MusicXML back. Undo/redo for every edit.
- **PDF import (beta)** — optional scanned-score conversion via Audiveris OMR, with a quality gate and clear marking of converted scores (recognition is not 100% reliable).
- **Multi-user** — email/password or Google sign-in, password reset, per-user libraries with starring, archiving, search, and server-side thumbnails. Light and dark themes.

## How it works

```
mic ──► /api/transcribe ──► Whisper (with a music-vocabulary prompt)
                                 │ transcript
                                 ▼
        /api/scores/:id/command ──► Claude agentic loop ──► MCP notation tools
                                                            (music21 edits the
                                                             MusicXML on disk)
                                 ▲                                 │
   browser re-renders (Verovio) ◄┴── updated MusicXML + spoken reply
```

The backend exposes the notation tools over MCP (Model Context Protocol); Claude decides which tools to call from your transcript plus recent conversation history, so follow-ups like *"same thing at bar 15"* work. Every tool call validates against the live score before touching it and snapshots for undo. Wake-word detection never leaves the browser; audio is only sent for transcription after you actively speak a command.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Zustand, Tailwind CSS v4 |
| Notation rendering | Verovio (WebAssembly) |
| Wake word | openWakeWord models on onnxruntime-web |
| Speech-to-text | OpenAI Whisper API |
| Text-to-speech | Web Speech API (browser-native) |
| Command orchestration | Anthropic Claude + MCP tool server |
| Notation engine | music21 (Python) |
| Backend | Flask, SQLAlchemy 2.0, SQLite (Postgres-ready via `DATABASE_URL`) |
| Optional OMR | Audiveris (PDF → MusicXML) |
| Auth | Flask sessions, bcrypt, Google OAuth 2.0 |

## Getting started

### Prerequisites

- Python 3.13+
- Node 22+
- An [Anthropic API key](https://console.anthropic.com/) and an [OpenAI API key](https://platform.openai.com/) (Whisper)

### Backend

```bash
cd backend
python -m venv venv
./venv/Scripts/pip install -r requirements.txt   # Windows; use venv/bin/pip elsewhere
cp .env.example .env                              # then fill in the required values
./venv/Scripts/python run.py                      # http://localhost:5001
```

At minimum set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and a long random `SECRET_KEY` in `backend/.env`.

### Frontend

```bash
cd frontend
npm install
npm run dev                                       # http://localhost:5173
```

Open `http://localhost:5173`, create an account, and drop a MusicXML file onto the dashboard. The dev server proxies `/api/*` to the backend.

## Using the app

1. **Upload a score** — drag a `.musicxml`, `.mxl`, or `.xml` file onto the dashboard (or a PDF, if OMR is configured — see below).
2. **Speak** — tap the mic (or say *"Hey Nota"* when the wake word is armed), then give a command. Recording sends automatically when you stop speaking. You can also type commands in the same bar.
3. **Listen and look** — Nota confirms aloud, the changed elements flash on the score, and the edit is on disk immediately. Say *"undo"* to take it back.
4. **Clarifications** — if a command is ambiguous ("remove the dynamic" when there are two), Nota asks; answer by voice or text.
5. **Manage your library** — star, archive, rename, download, or delete scores from each card's menu; search and sort from the shelf. Settings has theme, spoken-reply, and wake-word toggles.

### Voice command examples

| Category | Say something like |
|---|---|
| Dynamics | "forte at measure 12 beat 1" · "pianissimo at bar 3" |
| Hairpins | "crescendo from bar 5 to bar 8" |
| Slurs | "slur from measure 2 beat 1 to measure 3 beat 1" |
| Articulations | "staccato on beat 2 of bar 4" · "staccato in bars 8 through 12" |
| Ornaments | "trill on beat 2 of measure 5" · "fermata on beat 4 of the last measure" |
| Tempo | "quarter equals 120 at measure 1" · "adagio at bar 40" |
| Rehearsal marks | "rehearsal mark A at measure 9" |
| Text | "dolce at measure 1" |
| Fingerings | "third finger on beat 2 of measure 5" (0 = open string) |
| Notes | "add a quarter note G on beat 3 of measure 5" · "change the F in bar 3 to F sharp" · "make the note at bar 6 beat 1 a half note" · "delete the note at measure 7 beat 2" · "put a rest on beat 2" |
| Transposition | "transpose measures 1 through 8 up an octave" |
| Removal | "remove the dynamic at measure 12" |
| History | "undo" · "redo" · "same thing at bar 15" |

Beats are counted the way a musician counts them (a 6/8 bar has two beats; fractional beats like 1.5 address off-beats), and pickup measures are understood.

### The wake word

The bundled `frontend/public/oww/hey_nota.onnx` model detects "Hey Nota" locally in the browser. Arm it with the **Hey Nota** pill in the command bar or the toggle in Settings. To use a different phrase, train a model with [openWakeWord](https://github.com/dscripka/openWakeWord), drop the `.onnx` into `frontend/public/oww/`, and point `VITE_WAKE_WORD_MODEL` at it. Detection is suspended while Nota itself is speaking so it can't hear its own voice.

## Configuration

All backend settings live in `backend/.env` (see `backend/.env.example` for a commented template). `.env` is gitignored — never commit real keys.

### Required

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude, for command interpretation and tool orchestration |
| `OPENAI_API_KEY` | Whisper speech-to-text |
| `SECRET_KEY` | Signs session cookies and OAuth state — use a long random string |

### Core (optional)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///nota.db` | Any SQLAlchemy URL |
| `SCORE_STORAGE_DIR` | `./data/scores` | Where score files, thumbnails, and undo snapshots live |
| `MAX_UPLOAD_MB` | `10` | Upload size cap (PDFs included) |
| `PORT` | `5001` | Backend port |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Orchestrator model |
| `SCORE_CACHE_SIZE` | `4` | Parsed-score cache entries (0 disables) |
| `SPANNER_INDEX_DISABLE` | off | Set `1` to bypass the export accelerator |

### Google sign-in (optional)

| Variable | Purpose |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | From Google Cloud Console → Credentials → OAuth client ID (**Web application**). Sign-in is disabled while unset |
| `GOOGLE_REDIRECT_URI` | The registered callback. Local dev: `http://localhost:5173/api/auth/google/callback` (the Vite origin — it proxies to Flask) |

Register the same redirect URI in the Google console, and while the OAuth consent screen is in *Testing* mode, add your account under **Test users**.

### Password-reset email (optional)

| Variable | Default | Purpose |
|---|---|---|
| `APP_BASE_URL` | request origin | Public frontend origin used in reset links |
| `SMTP_HOST` | *(unset)* | Mail server. **When unset, reset links are logged to the backend console instead** — fine for dev, not for production |
| `SMTP_PORT` | `587` | STARTTLS is used on 587 |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | | Credentials, if the server needs them |
| `SMTP_FROM` | `no-reply@nota.app` | From address |

### PDF import via Audiveris (optional, beta)

| Variable | Default | Purpose |
|---|---|---|
| `AUDIVERIS_PATH` | *(unset)* | Full path to the Audiveris launcher. PDF upload is disabled while unset |
| `OMR_TIMEOUT_S` | `180` | Per-PDF conversion budget |

Install [Audiveris](https://audiveris.github.io/audiveris/) separately. Converted scores pass a quality gate and are badged **PDF** in the library — optical recognition is genuinely not 100% reliable, so always check converted scores against the original.

### Abuse / cost protection

| Variable | Default | Purpose |
|---|---|---|
| `DAILY_COMMAND_LIMIT` | `200` | Per-user voice/text commands per UTC day (each spends Anthropic tokens). `0` or negative disables |
| `DAILY_TRANSCRIBE_LIMIT` | `400` | Per-user transcriptions per UTC day (each spends OpenAI tokens). `0` or negative disables |

### Production serving

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` enables Secure cookies and disables the dev CORS handler |
| `FRONTEND_DIST_DIR` | *(unset)* | Path to the built frontend; when set, Flask serves the SPA itself |
| `GUNICORN_THREADS` | `16` | Request threads (single worker — see below) |
| `GUNICORN_TIMEOUT` | `300` | Long enough for command loops and OMR |

### Frontend (`frontend/.env.local`, optional)

| Variable | Default | Purpose |
|---|---|---|
| `VITE_WAKE_WORD_MODEL` | `/oww/hey_nota.onnx` | Wake-word model path under `public/` |
| `VITE_WAKE_WORD_THRESHOLD` | `0.5` | Detection sensitivity, 0–1 (higher = stricter) |

## Testing

```bash
cd backend
./venv/Scripts/python -m pytest tests -q          # full suite (~800 tests)
./venv/Scripts/python -m pytest tests/tools -q    # notation tools only

cd frontend
npm run lint && npm run build
```

There is also an LLM eval harness (`backend/evals/`) that replays a dataset of spoken-command transcripts against the real orchestrator and scores the tool calls — useful when changing the system prompt or tool descriptions: `./venv/Scripts/python evals/run_evals.py`.

## Deployment

Nota deploys as **one Docker container on one machine with a persistent disk** (Fly.io, Render, or any VPS). The provided `Dockerfile` builds the frontend, then runs gunicorn serving both the API and the SPA.

Two hard constraints to respect:

1. **Exactly one worker process.** Score locking, the parsed-score cache, and the MCP tool subprocess are all per-process; `gunicorn.conf.py` pins `workers = 1` (with threads for concurrency) deliberately. Do not scale by adding workers or replicas.
2. **Persistent volume.** Point `DATABASE_URL` (e.g. `sqlite:////data/nota.db`) and `SCORE_STORAGE_DIR` (e.g. `/data/scores`) at a mounted volume, and back it up — it holds every user's scores.

Production checklist: `APP_ENV=production`, HTTPS at the platform edge (the mic requires a secure context), real `SMTP_*` values (users are told to check their inbox), production `GOOGLE_REDIRECT_URI` registered in the Google console with the consent screen published, a strong `SECRET_KEY`, and quota limits tuned to taste.

## Project structure

```
backend/
  nota/
    routes/          # Flask blueprints: auth, scores, commands, transcribe, ingest
    orchestrator/    # Claude agentic loop, MCP client, system prompt, locks
    mcp_server/      # The notation tools (music21) + stdio MCP server
    services/        # Whisper, OMR, caching, MusicXML repair, thumbnails
  evals/             # Spoken-command eval dataset + runner
  tests/             # pytest suites: routes, orchestrator, tools, services, evals
frontend/
  src/
    pages/           # Landing, Auth, Dashboard, Viewer, Settings
    components/      # VoiceBar, ScoreCard, UploadDropzone, ...
    hooks/           # Voice recorder, wake word, speech readback, Verovio
    store/           # Zustand stores (auth, scores, readback)
  public/oww/        # Wake-word ONNX models
Dockerfile           # Multi-stage production image
```
