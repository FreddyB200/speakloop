# CLAUDE.md

Guidance for AI agents working on SpeakLoop, a local-first speaking coach. See `README.md`, `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.

## Architecture map

`src/speakloop/`: `cli.py` (Typer app), `models.py` (pydantic data contracts), `workspace.py` (session folders of JSON files), `transcribe` (`base.py`: `TranscriptionBackend` protocol), `analyze`, `audit` (`base.py`: `AuditBackend` protocol), `items` (`store.py`: SQLite `ItemStore`), `export`, `practice`, `packs`. JSON Schemas of the models are generated into `docs/schemas/` by `scripts/export_schemas.py` (a test fails if they are stale). The remaining modules are empty placeholders for now. Tests live in `tests/`.

## Commands

- `uv sync`: install dependencies
- `uv run pytest`: tests
- `uv run ruff check` and `uv run ruff format --check`: lint and format (use `uv run ruff format` to fix)
- `uv run mypy src`: strict type check
- `uv run speakloop --help`: run the CLI

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
