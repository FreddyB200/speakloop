# CLAUDE.md

Guidance for AI agents working on SpeakLoop, a local-first speaking coach. See `README.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.

## Architecture map

`src/speakloop/`: `cli.py` (Typer app: `version`, `doctor`, `audit`), `pipeline.py` (`run_session`: transcribe, metrics, audit, save, report, with injected backends), `models.py` (pydantic data contracts), `workspace.py` (session folders of JSON files), `transcribe` (`base.py` protocol, `buzz.py` `BuzzBackend`, `fake.py` `FakeBackend`), `analyze` (`metrics.py`: pure metric functions), `audit` (`base.py` protocol, `claude_code.py` backend, `run.py`, `verify.py` quote verification, `rubric/` and `prompts/` v1), `export` (`report.py` Markdown report, `obsidian.py` folder export), `items` (`store.py`: SQLite `ItemStore`), `practice` and `packs` (empty placeholders). JSON Schemas of the models are generated into `docs/schemas/` by `scripts/export_schemas.py` (a test fails if they are stale). Tests live in `tests/` and never call real Buzz or real `claude`; the `integration` marker is opt-in via `SPEAKLOOP_RUN_INTEGRATION=1`. See `docs/ARCHITECTURE.md` for env vars and design notes.

## Commands

- `uv sync`: install dependencies
- `uv run pytest`: tests
- `uv run ruff check` and `uv run ruff format --check`: lint and format (use `uv run ruff format` to fix)
- `uv run mypy src`: strict type check
- `uv run speakloop --help`: run the CLI
- `uv run speakloop doctor`: check claude, Buzz and the workspace
- `uv run speakloop audit session.m4a --kind discovery`: run the pipeline (uses the real Buzz and Claude Code; never from tests)

All of these must pass before a task is done (CI runs the same).

## Hard rules

- Never commit real audio, transcripts or personal data. Synthetic fixtures only.
- English only: code, comments, docs, commit messages.
- No new dependencies without explicit approval.
- Every change needs tests.
- Typed code that passes `mypy --strict`.
- Keep modules decoupled behind interfaces so backends can be swapped.
- AI only through Claude Code headless (`claude -p`). Never API keys or paid API backends.
- Do not expand scope beyond the assigned task.
