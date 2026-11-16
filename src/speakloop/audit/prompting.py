"""Render the audit prompt from the rubric, session, transcript and metrics."""

from pathlib import Path
from string import Template

from speakloop.audit.rubric import Rubric, RubricEntry
from speakloop.models import Metrics, Session, Transcript

DEFAULT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "audit.md"


def format_timestamp(seconds: float) -> str:
    total = int(max(seconds, 0.0))
    return f"{total // 60:02d}:{total % 60:02d}"


def _timed_text(transcript: Transcript, track: str) -> str:
    segments = sorted(
        (s for s in transcript.segments if s.track == track and s.text.strip()),
        key=lambda s: s.start,
    )
    return "\n".join(f"[{format_timestamp(s.start)}] {s.text.strip()}" for s in segments)


def _entries(entries: tuple[RubricEntry, ...]) -> str:
    return "\n".join(f"- {e.name}: {e.description}" for e in entries) or "- (none)"


def _metrics_text(metrics: Metrics) -> str:
    lines = [
        f"duration_s: {metrics.duration_s:.1f}",
        f"word_count: {metrics.word_count}",
        f"wpm_mean: {metrics.wpm_mean:.1f}",
        f"fillers_per_100w: {metrics.fillers_per_100w:.1f}",
        f"filler_counts: {dict(metrics.filler_counts)}",
        f"repetitions: {metrics.repetitions}",
        f"false_starts: {metrics.false_starts}",
        f"long_pauses: {len(metrics.long_pauses)}",
    ]
    if metrics.fde is not None and metrics.fde.talk_ratio is not None:
        lines.append(f"talk_ratio: {metrics.fde.talk_ratio:.2f}")
    return "\n".join(lines)


def render_prompt(
    *,
    rubric: Rubric,
    session: Session,
    transcript: Transcript,
    metrics: Metrics,
    template: str | None = None,
) -> str:
    """Render the audit prompt. The speaker track is the only quotable source."""
    speaker = next(t.id for t in session.tracks if t.role == "speaker")
    interlocutor = next((t.id for t in session.tracks if t.role == "interlocutor"), None)
    body = template if template is not None else DEFAULT_TEMPLATE_PATH.read_text("utf-8")
    inter_text = _timed_text(transcript, interlocutor) if interlocutor else ""
    return Template(body).safe_substitute(
        kind=session.kind.value,
        scenario_id=session.scenario_id or "none",
        rubric_version=rubric.version,
        spoken_english_instruction=rubric.spoken_english_instruction,
        max_patterns=rubric.max_patterns,
        categories=_entries(rubric.categories),
        fde_dimensions=_entries(rubric.fde_dimensions),
        metrics=_metrics_text(metrics),
        interlocutor_text=inter_text or "(none)",
        speaker_text=_timed_text(transcript, speaker) or "(empty)",
    )
