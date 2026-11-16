# Architecture

Status: design. Only the package skeleton and CLI stubs exist.

## Pipeline

```
recording -> transcribe -> analyze (metrics) -> audit (AI judgment)
          -> items (findings become learning items) -> export / practice
          -> next session verifies usage -> items updated
```

## Modules

Each module sits behind an interface so a piece can be swapped without touching the others.

| Module | Responsibility |
|---|---|
| `transcribe` | Interchangeable speech-to-text backends (candidates: Buzz CLI with whisper.cpp, faster-whisper, mlx-whisper). The final choice comes from a benchmark on real audio. |
| `analyze` | Objective metrics (pauses, pace, fillers, latency) as pure, tested functions. |
| `audit` | Qualitative AI audit through Claude Code headless mode (`claude -p`) with a fixed rubric. Output is validated JSON; every quote is verified against the transcript. |
| `items` | Learning items, evidence and mastery, stored in SQLite. |
| `export` | Markdown (e.g. for Obsidian), Anki (via AnkiConnect), HTML report. |
| `practice` | Practice modes: shadowing, 4/3/2, interview questions. |
| `packs` | Domain and native-language content (e.g. the FDE pack with scenarios that hold hidden facts). |
| `cli` | The `speakloop` command (Typer). |

A separate two-track recorder for macOS (Swift, milestone M5) is planned outside the Python package.

## Data and workspace layout

A local workspace (default `~/SpeakLoop/`, configurable) holds one folder per session (audio, transcript, metrics, audit, report) plus one SQLite database. None of it is ever versioned; `.gitignore` excludes `workspace/`, `sessions/`, `transcripts/`, databases and audio formats. Tests use synthetic fixtures only.

## Decision log

- All repository documentation and code comments are in English.
- AI runs only through the user's own Claude Code subscription (headless `claude -p`). No API keys, no paid API backends. A local model via Ollama may be added later as an optional backend for people without a subscription.
- Local-first and private: audio, transcripts, session data and databases never leave the machine and are never committed.
- Anki integration goes through AnkiConnect (the local Anki add-on API), with deterministic, tested sync code. An MCP bridge may be added later as an optional conversational layer.
- Python 3.12, packaged with uv, src layout, CLI named `speakloop`.
- Runtime dependencies are kept minimal (`typer`, `pydantic`); new ones need explicit approval.
