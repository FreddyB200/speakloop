"""End-to-end session pipeline: transcribe, measure, audit, save and report.

Every backend is injected, so the whole flow runs in tests without Buzz or Claude Code.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from speakloop.analyze.metrics import compute_metrics
from speakloop.audit.base import AuditBackend, AuditBackendError
from speakloop.audit.rubric import Rubric
from speakloop.audit.run import AuditResult, run_audit
from speakloop.export.report import render_report
from speakloop.models import (
    AuditSummary,
    Finding,
    Metrics,
    Session,
    SessionKind,
    Track,
    TrackId,
    Transcript,
    new_session_id,
)
from speakloop.transcribe.base import TranscriptionBackend, TranscriptionError
from speakloop.workspace import Workspace

DEFAULT_TRANSCRIPTION_PROMPT = (
    "Um, uh, er, hmm. Well, you know, I mean, I- I think we, uh, should ask first."
)
MAX_PROMPT_CHARS = 800
_GLOSSARY_LEAD = " Names and terms: "
_log = logging.getLogger(__name__)


def build_transcription_prompt(base: str, glossary: Sequence[str]) -> str:
    """Append the personal glossary to the initial prompt, keeping it under the size cap.

    Terms that do not fit are dropped (with a warning); with no terms the base is unchanged.
    """
    terms = list(dict.fromkeys(t.strip() for t in glossary if t.strip()))
    if not terms:
        return base
    kept: list[str] = []
    for term in terms:
        candidate = base + _GLOSSARY_LEAD + ", ".join([*kept, term]) + "."
        if len(candidate) > MAX_PROMPT_CHARS:
            break
        kept.append(term)
    if len(kept) < len(terms):
        _log.warning(
            "glossary truncated: using %d of %d terms to keep the prompt under %d characters",
            len(kept),
            len(terms),
            MAX_PROMPT_CHARS,
        )
    if not kept:
        return base
    return base + _GLOSSARY_LEAD + ", ".join(kept) + "."


class PipelineError(Exception):
    """A pipeline step failed. The message names the step."""


@dataclass(frozen=True)
class SessionResult:
    session: Session
    transcript: Transcript
    metrics: Metrics
    findings: tuple[Finding, ...]
    report_path: Path
    dropped_quotes: int | None
    discarded_findings: int | None
    audit_error: str | None = None


def merge_transcripts(session_id: str, *transcripts: Transcript) -> Transcript:
    """Combine per-track transcripts into one, with segments sorted by start time."""
    if not transcripts:
        raise ValueError("at least one transcript is required")
    segments = sorted((s for t in transcripts for s in t.segments), key=lambda s: s.start)
    backends = list(dict.fromkeys(t.backend for t in transcripts))
    models = list(dict.fromkeys(t.model for t in transcripts))
    language = next((t.language for t in transcripts if t.language is not None), None)
    prompt = next((t.prompt for t in transcripts if t.prompt is not None), None)
    return Transcript(
        session_id=session_id,
        language=language,
        backend="+".join(backends),
        model="+".join(models),
        prompt=prompt,
        segments=tuple(segments),
    )


def run_session(
    audio_mic: Path,
    *,
    audio_system: Path | None,
    kind: SessionKind,
    scenario_id: str | None,
    workspace: Workspace,
    transcriber: TranscriptionBackend,
    auditor: AuditBackend | None,
    rubric: Rubric,
    language: str = "en",
    prompt: str | None = DEFAULT_TRANSCRIPTION_PROMPT,
    glossary: Sequence[str] = (),
    now: datetime | None = None,
) -> SessionResult:
    """Process one recording and persist the session. See module docstring."""
    moment = now if now is not None else datetime.now(UTC)
    session = Session(
        id=new_session_id(moment),
        created_at=moment,
        kind=kind,
        scenario_id=scenario_id,
        tracks=(
            Track(id="mic", role="speaker", audio_path=audio_mic),
            *(
                (Track(id="system", role="interlocutor", audio_path=audio_system),)
                if audio_system is not None
                else ()
            ),
        ),
    )

    if prompt is not None:
        prompt = build_transcription_prompt(prompt, glossary)

    inputs: list[tuple[TrackId, Path]] = [("mic", audio_mic)]
    if audio_system is not None:
        inputs.append(("system", audio_system))
    parts: list[Transcript] = []
    for track_id, path in inputs:
        try:
            parts.append(
                transcriber.transcribe(
                    path,
                    track=track_id,
                    session_id=session.id,
                    language=language,
                    prompt=prompt,
                )
            )
        except TranscriptionError as exc:
            raise PipelineError(f"transcription failed for track {track_id}: {exc}") from exc
    transcript = merge_transcripts(session.id, *parts)

    metrics = compute_metrics(transcript, session)
    audit: AuditResult | None = None
    audit_error: str | None = None
    if auditor is not None:
        try:
            audit = run_audit(transcript, session, metrics, auditor, rubric)
        except AuditBackendError as exc:
            audit_error = f"audit failed: {exc}"
        else:
            if audit.proposal_time_s is not None:
                metrics = compute_metrics(
                    transcript, session, proposal_time_s=audit.proposal_time_s
                )

    findings: tuple[Finding, ...] = audit.findings if audit else ()
    workspace.save_session(session)
    workspace.save_transcript(transcript)
    workspace.save_metrics(metrics)
    workspace.save_findings(session.id, list(findings))
    if auditor is not None:
        workspace.save_audit(
            session.id,
            AuditSummary(
                summary=audit.summary if audit else None,
                next_session_goal=audit.next_session_goal if audit else None,
                proposal_time_s=audit.proposal_time_s if audit else None,
                dropped_quotes=audit.dropped_quotes if audit else 0,
                discarded_findings=audit.discarded_findings if audit else 0,
                rubric_version=rubric.version,
                error=audit_error,
            ),
        )

    report = render_report(
        session,
        metrics,
        findings,
        summary=audit.summary if audit else None,
        next_session_goal=audit.next_session_goal if audit else None,
        transcript=transcript,
    )
    report_path = workspace.save_report(session.id, report)
    return SessionResult(
        session=session,
        transcript=transcript,
        metrics=metrics,
        findings=findings,
        report_path=report_path,
        dropped_quotes=audit.dropped_quotes if audit else None,
        discarded_findings=audit.discarded_findings if audit else None,
        audit_error=audit_error,
    )
