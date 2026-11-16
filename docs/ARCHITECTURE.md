# Architecture

Status: milestone M1 in progress. `speakloop audit` runs the full pipeline (transcribe, metrics, audit, report); items, practice and packs are still placeholders.

## Pipeline

```
audio (mic [+ system])
   |  transcribe each track (BuzzBackend / FakeBackend), merge by start time
   v
Transcript --> compute_metrics --> Metrics (no proposal time yet)
   |                                  |
   |  run_audit (claude -p, rubric v1, prompt v1)
   v                                  v
verified quotes + first proposal time --> compute_metrics again (clarifying questions)
   |
   v
workspace: session.json transcript.json metrics.json findings.json [audit.json] report.md
   |
   +--> optional export to an Obsidian folder (never overwrites)
```

Data flow, implemented in `speakloop.pipeline.run_session` with every backend injected:

1. A `Session` is created (new id, timezone-aware time; tracks: `mic` = speaker, `system` = interlocutor when given).
2. Each track is transcribed with an initial prompt that nudges Whisper to keep disfluencies (`DEFAULT_TRANSCRIPTION_PROMPT`; without a prompt "uh" came out as "ah"). Transcripts are merged by `merge_transcripts`.
3. Metrics are computed. If an audit backend is given, the audit runs and metrics are recomputed with `proposal_time_s` from the audit so the FDE clarifying-question count exists.
4. Everything is saved and the report is rendered and written atomically to `report.md`.
5. A transcription failure raises `PipelineError` naming the step and saves nothing. An audit failure never loses the session: transcript, metrics and a report without patterns are saved and `SessionResult.audit_error` carries the message (the CLI then exits non-zero).

The remaining stages (items, practice, next-session verification) are planned, not built.

## Modules

Each module sits behind an interface so a piece can be swapped without touching the others.

| Module | Responsibility |
|---|---|
| `transcribe` | Interchangeable speech-to-text backends (Buzz CLI today, plus a deterministic `FakeBackend` for tests). |
| `analyze` | Objective metrics (pauses, pace, fillers, latency) as pure, tested functions. |
| `audit` | Qualitative AI audit through Claude Code headless mode (`claude -p`) with a fixed rubric. Output is validated JSON; every quote is verified against the transcript. |
| `items` | Learning items, evidence and mastery, stored in SQLite. |
| `export` | Markdown (e.g. for Obsidian), Anki (via AnkiConnect), HTML report. |
| `practice` | Practice modes: shadowing, 4/3/2, interview questions. |
| `packs` | Domain and native-language content (e.g. the FDE pack with scenarios that hold hidden facts). |
| `server` | Local FastAPI app: JSON API, background job queue and the built frontend. |
| `cli` | The `speakloop` command (Typer). |

A separate two-track recorder for macOS (Swift, milestone M5) is planned outside the Python package.

## Data and workspace layout

A local workspace (default `~/SpeakLoop/`, configurable) holds one folder per session (audio, transcript, metrics, audit, report) plus one SQLite database. None of it is ever versioned; `.gitignore` excludes `workspace/`, `sessions/`, `transcripts/`, databases and audio formats. Tests use synthetic fixtures only.

## Data contracts

The models in `src/speakloop/models.py` (pydantic, frozen, unknown fields rejected) are the contracts between modules. Times are float seconds from the start of the recording. JSON Schemas for `Session`, `Transcript`, `Metrics`, `Finding` and `Item` and `AuditSummary` live in `docs/schemas/`; regenerate them with `uv run python scripts/export_schemas.py` (a test fails when they are out of date).

Workspace layout (`SPEAKLOOP_HOME`, default `~/SpeakLoop`), managed by `speakloop.workspace.Workspace`:

```
sessions/<YYYYMMDD-HHMMSS-xxxx>/
    session.json  transcript.json  metrics.json  findings.json  audit.json  report.md
glossary.txt   (optional personal terms, see Transcription)
items.db   (SQLite, managed by speakloop.items.store.ItemStore)
```

Files are written atomically (temp file in the same folder, then `os.replace`) and session ids are validated to prevent path traversal. Backends implement the protocols in `transcribe/base.py` and `audit/base.py`.

## Transcription

- `BuzzBackend` shells out to `buzz add` and parses the SRT it writes. It uses the `fasterwhisper` model type because `whispercpp` is broken in the tested Buzz 1.4.5 install. The OpenAI API model type is refused (no paid APIs).
- Buzz exits 0 even when transcription fails, so the presence of an SRT file is the real success signal.
- `BUZZ_DISABLE_TELEMETRY=1` is always set for the child process: otherwise Buzz sends an `app_launched` telemetry event on every start.
- Buzz does not expose word probabilities, so `Word.probability` is `None`.
- `FakeBackend(words)` returns a fixed word list and is what all tests use. Real Buzz never runs in the normal test suite.

### Environment variables

| Variable | Meaning |
|---|---|
| `SPEAKLOOP_BUZZ` | Path to the Buzz executable (else `~/.venvs/buzz/bin/buzz`, then PATH) |
| `SPEAKLOOP_CLAUDE` | Path or name of the `claude` executable (else PATH) |
| `SPEAKLOOP_HOME` | Workspace root (default `~/SpeakLoop`) |
| `SPEAKLOOP_OBSIDIAN_DIR` | Absolute folder to also export reports to (same as `--obsidian-dir`) |
| `SPEAKLOOP_RUN_INTEGRATION` | Set to `1` to run the opt-in tests marked `integration`, which need external tools |

## Metrics

`analyze/metrics.py` holds pure, deterministic functions with documented heuristics (WPM windows, long pauses, fillers, repetitions, false starts, MATTR, response latency, and FDE signals). Notes:

- Fillers come from a lexicon; "like" is an opt-in filler (`FillerLexicon.with_entries("like")`) because it is often a legitimate word.
- Risky-commitment detection is lexical and does not handle negation yet ("we will not guarantee" can still match).
- The clarifying-question count needs the proposal time found by the audit; without it the value is `None`.

## Audit

`ClaudeCodeBackend` runs `claude -p` with: `--output-format json` (one envelope), `--json-schema` (structured output), `--tools ""` (no tools: the transcript reaches the model only through the prompt, sent on stdin), `--strict-mcp-config` (no MCP servers), `--disable-slash-commands`, `--no-session-persistence` (nothing left in Claude Code history), `--permission-mode dontAsk` with `--permission-prompts none` (anything that would prompt is denied), and `--setting-sources user` (only the user's login settings; the working directory is a fresh temporary one). `--bare` is not used because it requires an API key, which would break subscription auth; `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are removed from the child environment. Details are in the module docstring of `audit/claude_code.py`.

Every quote returned by the model is verified against the speaker track on normalized tokens; unverifiable quotes are dropped, findings left without quotes are discarded, and timings and quote text always come from the transcript. The counts are reported. The rubric v1 lives in `src/speakloop/audit/rubric/default.toml` and the prompt v1 in `src/speakloop/audit/prompts/audit.md`.

## Report and export

The report is Markdown with YAML front matter. The front matter keys (`type`, `date`, `session_id`, `kind`, `scenario`, `duration_min`, `word_count`, `wpm_mean`, ... `findings`, `top_patterns`, `next_goal`) are a stable contract for downstream tools such as Obsidian Dataview; golden files in `tests/fixtures/export/` guard it. `export_to_folder` writes `<date> <kind> <session_id>.md` into a folder and never overwrites (a numeric suffix is appended instead).

## Testing

`uv run pytest` is fully offline and uses synthetic data. Tests that need real tools carry the `integration` marker and only run with `SPEAKLOOP_RUN_INTEGRATION=1`.

## Decision log

- All repository documentation and code comments are in English.
- AI runs only through the user's own Claude Code subscription (headless `claude -p`). No API keys, no paid API backends. A local model via Ollama may be added later as an optional backend for people without a subscription.
- Local-first and private: audio, transcripts, session data and databases never leave the machine and are never committed.
- Anki integration goes through AnkiConnect (the local Anki add-on API), with deterministic, tested sync code. An MCP bridge may be added later as an optional conversational layer.
- Python 3.12, packaged with uv, src layout, CLI named `speakloop`.
- Runtime dependencies are kept minimal (`typer`, `pydantic`); new ones need explicit approval.

## Transcript section, audit.json and `speakloop report`

- `render_report(..., transcript=...)` appends a final `## Transcript` section: a collapsed Obsidian callout (`> [!quote]- Transcript as recognized (<backend>:<model>)`, a plain blockquote on GitHub) with one `**[mm:ss]** text` line per segment in time order (`h:mm:ss` over an hour), the other side of a two-track call marked `*(other speaker)*`, and a last line with the initial prompt in italics. The pipeline always passes the transcript; the front matter is unchanged.
- The audit outcome that is not a finding is saved as `audit.json` (`AuditSummary`: summary, next session goal, proposal time, dropped quotes, discarded findings, rubric version, error). It is written whenever an auditor ran (also when it failed, with `error` set) and is absent with `--no-audit`; `Workspace.load_audit` returns None if missing.
- `speakloop report SESSION_ID [--workspace PATH] [--obsidian-dir PATH] [--no-transcript]` re-renders `report.md` from the saved files (audit.json optional) and, when an Obsidian folder is given (option or `SPEAKLOOP_OBSIDIAN_DIR`), calls `export_to_folder(..., replace=True)`: an existing file whose name ends with `<session_id>.md` is replaced atomically, otherwise a new file is created. The default `replace=False` never overwrites. Unknown or malformed session ids fail with a clear error.
- Personal glossary: `speakloop audit --glossary "TransMilenio, Datos Abiertos"` and the optional `<workspace>/glossary.txt` (one term per line, `#` comments) are merged and appended to the initial prompt as `Names and terms: A, B.` The whole prompt is capped at 800 characters (extra terms are dropped with a warning). Nothing is added with `--no-prompt`.

## Web server and API (contract v0)

`speakloop serve` runs a FastAPI app (`speakloop.server.app.create_app(workspace)`) with uvicorn on `127.0.0.1:8791` (if the port is taken, the next free one is used and printed). OpenAPI is at `/api/openapi.json` (Swagger UI at `/api/docs`). JSON fields are snake_case and reuse the pydantic models. Backends come from `cli.make_transcriber` and `cli.make_auditor`, looked up at call time so tests can patch them.

| Endpoint | Result |
|---|---|
| `GET /api/health` | `{ok, version}` |
| `GET /api/doctor` | `{checks: [{name, ok, detail}]}` (same logic as `speakloop doctor`) |
| `GET /api/sessions` | newest first: `id, created_at, kind, scenario_id, duration_s, wpm_mean, fillers_per_100w, findings_count, has_audio, audit_error` (sessions without metrics are skipped) |
| `GET /api/sessions/{id}` | `{session, metrics, findings, audit, transcript, audio_tracks}`; 404 for unknown or invalid ids |
| `GET /api/sessions/{id}/report.md` | `text/markdown` |
| `GET /api/sessions/{id}/audio/{track}` | stored audio (`mic` or `system`) with Range support; 404 if missing |
| `POST /api/sessions` | multipart `mic`, optional `system`, `kind` (default `free`), `scenario_id`, `audit` (default true); `202 {job_id}` |
| `GET /api/jobs/{job_id}` | `{job_id, status, session_id, error, audit_error}`; status is `queued`, `transcribing`, `analyzing`, `auditing`, `saving`, `done` or `error` |
| `POST /api/sessions/{id}/export` | exports or replaces the Obsidian note: `{path}`; 400 without a configured folder (settings, else `SPEAKLOOP_OBSIDIAN_DIR`) |
| `GET/PUT /api/settings` | `{obsidian_dir, glossary, model_size, language}` |

Unknown `/api/*` paths return a JSON 404. Any other GET serves `web/dist` with a fallback to `index.html` (SPA); without a build, `/` shows a page explaining how to build the frontend.

### Jobs

Uploads are saved to a temporary folder, then queued in an in-process queue served by one daemon worker thread, so only one pipeline runs at a time. `run_session` reports progress through its `on_step` callback, which updates the job status. Jobs live in memory only (a restart forgets them; finished sessions are on disk). The temp upload folder is always removed after the job.

### Audio storage

With `keep_audio=True` (always on in the server, opt-in `--keep-audio` in the CLI) each input file is copied to `sessions/<id>/audio/<track><ext>` and the track's `audio_path` is that path relative to the session folder. The audio endpoint serves only relative paths that resolve inside the session folder; absolute paths (CLI sessions that did not keep audio) and traversal are never served.

### Settings

`<workspace>/config.toml` holds `obsidian_dir`, `model_size` and `language` (written by hand, only simple strings, read with `tomllib`; an unreadable file falls back to defaults). The glossary stays in `<workspace>/glossary.txt` (one term per line), so the CLI keeps working. Saving the glossary from the API drops comments from that file.

### Security (local-only server)

- Binds `127.0.0.1` by default.
- Requests whose Host header is not `localhost`, `127.0.0.1` or `::1` get 403 (DNS-rebinding protection).
- State-changing requests (non-GET/HEAD/OPTIONS) with an Origin that is not the server's own origin (same host and port as the Host header) get 403. Extra origins, such as the Vite dev server, can be allowed with `SPEAKLOOP_ALLOWED_ORIGINS` (comma-separated) or `create_app(extra_origins=...)`; by default there is none.
- No CORS headers; the Vite dev server proxies `/api`.
- Uploads: at most 500 MB per file (413 beyond, also checked early through Content-Length) and only `audio/*` or `video/*` content types (415). Stored file names are built from the track and a sanitized extension, never from the client file name; `scenario_id` is restricted to `[A-Za-z0-9_.-]{1,64}`.
- Session ids are validated before touching any path; static files are served only from inside `web/dist`.
