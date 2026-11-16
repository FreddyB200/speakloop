"""Run the AI audit: prompt, backend call, quote verification, deterministic findings."""

from dataclasses import dataclass

from speakloop.audit.base import AuditBackend, AuditBackendError
from speakloop.audit.prompting import render_prompt
from speakloop.audit.rubric import Rubric
from speakloop.audit.schema import audit_json_schema, validate_audit
from speakloop.audit.verify import verify_audit
from speakloop.models import Finding, Metrics, Session, Transcript


@dataclass(frozen=True)
class AuditResult:
    findings: tuple[Finding, ...]
    proposal_time_s: float | None
    summary: str
    next_session_goal: str
    dropped_quotes: int
    discarded_findings: int


def run_audit(
    transcript: Transcript,
    session: Session,
    metrics: Metrics,
    backend: AuditBackend,
    rubric: Rubric,
) -> AuditResult:
    """Audit one session. Raises AuditBackendError if the answer is unusable."""
    speaker = next(t.id for t in session.tracks if t.role == "speaker")
    prompt = render_prompt(rubric=rubric, session=session, transcript=transcript, metrics=metrics)
    data = backend.complete_json(prompt, json_schema=audit_json_schema())
    try:
        raw = validate_audit(data)
    except ValueError as exc:
        raise AuditBackendError(f"audit answer failed validation: {exc}") from exc
    verified = verify_audit(raw, transcript, speaker)
    ranked = sorted(verified.findings, key=lambda v: -v.raw.severity)
    kept = ranked[: rubric.max_patterns]
    cut = len(ranked) - len(kept)
    findings = tuple(
        Finding(
            id=f"{session.id}-audit-{index}",
            session_id=session.id,
            category=v.raw.category,
            title=v.raw.title,
            explanation=v.raw.explanation,
            suggestion=v.raw.suggestion,
            evidence=v.evidence,
            severity=v.raw.severity,
            source="audit",
        )
        for index, v in enumerate(kept, start=1)
    )
    return AuditResult(
        findings=findings,
        proposal_time_s=verified.proposal_time_s,
        summary=raw.summary,
        next_session_goal=raw.next_session_goal,
        dropped_quotes=verified.dropped_quotes,
        discarded_findings=verified.discarded_findings + cut,
    )
