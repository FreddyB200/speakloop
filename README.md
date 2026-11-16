# SpeakLoop

A local-first speaking coach that turns the mistakes you make while speaking into practice, and measures whether you stop making them.

> **Status: Pre-alpha.** Milestone M1 is in progress: `speakloop audit` already runs the transcribe, metrics, AI audit and report pipeline, but the rest (items, Anki, practice modes, recorder) is not built. Expect rough edges. Most of what is described below is where the project is going, not what it does today.

## The closed loop

Language apps teach generic content and measure whether you *recognize* a card. SpeakLoop starts from what *you* say wrong and measures whether you *use it correctly* in spontaneous speech in the next session.

```
 Session (mock interview, shadowing, 4/3/2, conversation)
        | recording
        v
 Analysis: objective metrics (code) + qualitative audit (AI, fixed rubric)
        | findings with evidence (exact quote + timestamp)
        v
 Learning items (grammar pattern, phrase, word, sound)
        | review scheduler per modality
        v
 Practice (Anki cards, "say it aloud", shadowing, goals for the next session)
        |
        +--> the next session checks whether you used it correctly
             --> updates the mastery of each item
```

## MVP focus: Forward Deployed Engineer interview practice

The first content pack targets Forward Deployed Engineer (FDE) interviews, where spoken English matters most because the job is working with customers:

- Customer discovery (ask clarifying questions before proposing anything)
- Customer under pressure (incidents, out-of-scope demands, executives on the call)
- Technical deep dive (explain your own project, adapting register to the audience)
- Thinking out loud (fluency while reasoning)
- Behavioral questions (STAR structure, concreteness)
- Three-minute demos

## Principles

- **Local-first and private.** Audio, transcripts and session data never leave your machine and are never committed.
- **AI through your own Claude Code subscription.** Headless `claude -p` only. No API keys, no paid API backends.
- **Reproducible metrics computed by code.** Pauses, pace, filler words and latency are pure, tested functions; the AI only handles judgment, against a fixed rubric.
- **Quotes verified against the transcript.** If the AI cites something that is not in the transcript, the finding is discarded.

## Planned features

- Local transcription with swappable backends
- Objective speaking metrics and an AI audit with a fixed rubric
- Learning items with mastery measured in real speech, not only on cards
- Anki integration through AnkiConnect
- Practice modes: shadowing, 4/3/2, interview question bank
- Progress tracking against your own baseline
- Domain and native-language content packs

## Roadmap

- **M0** Foundations and proof: repo, data contracts, transcription benchmark, rubric and prompts v1
- **M1** MVP audit loop: `speakloop audit <audio>` produces a report
- **M2** Items and Anki: findings become items and cards
- **M3** Practice modes: shadowing, 4/3/2, interview question bank
- **M4** Progress: trends against the baseline, weekly review
- **M5** Recorder: two-track capture on macOS
- **M6** Pronunciation research: phoneme-level prototype
- **M7** Ecosystem: plugins, content packs, documentation

See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

An example report, generated from synthetic speech with deliberately planted mistakes: [docs/examples/discovery-synthetic.md](docs/examples/discovery-synthetic.md).

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://claude.com/claude-code) with an active subscription (for AI audits, from M1)

```
uv sync
uv run speakloop doctor
```

## Usage (early, macOS)

Requires [Buzz](https://github.com/chidiwilliams/buzz) for local transcription and Claude Code for the AI audit.

```
uv run speakloop doctor
uv run speakloop audit session.m4a --kind discovery
```

`doctor` checks that `claude`, Buzz and the workspace folder (`~/SpeakLoop`, or `$SPEAKLOOP_HOME`) are usable. `audit` writes the session files and a Markdown `report.md` under `sessions/<id>/` and prints a short summary. Useful options: `--system other.m4a` (the other side of the call as a second track), `--no-audit` (transcript and metrics only), `--obsidian-dir PATH` (or `SPEAKLOOP_OBSIDIAN_DIR`) to also copy the report to a folder. See `speakloop audit --help`.

## License

MIT. See [LICENSE](LICENSE).
