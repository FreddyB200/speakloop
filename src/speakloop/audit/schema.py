"""JSON schema of the answer the audit model must produce, plus a strict validator."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from speakloop.models import FindingCategory


class RawFinding(BaseModel):
    """One finding as the model reports it, before quote verification."""

    model_config = ConfigDict(extra="forbid")

    category: FindingCategory
    title: str = Field(min_length=1)
    explanation: str
    suggestion: str | None
    severity: Literal[1, 2, 3]
    quotes: list[str] = Field(min_length=1)


class RawAudit(BaseModel):
    """The whole model answer, before quote verification."""

    model_config = ConfigDict(extra="forbid")

    findings: list[RawFinding]
    first_proposal_quote: str | None
    summary: str
    next_session_goal: str


def audit_json_schema() -> dict[str, object]:
    """Return the JSON schema sent to the model (also used to describe the answer)."""
    finding: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["category", "title", "explanation", "suggestion", "severity", "quotes"],
        "properties": {
            "category": {"type": "string", "enum": [c.value for c in FindingCategory]},
            "title": {"type": "string", "minLength": 1},
            "explanation": {"type": "string"},
            "suggestion": {"type": ["string", "null"]},
            "severity": {"type": "integer", "minimum": 1, "maximum": 3},
            "quotes": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
                "description": "Exact words from the SPEAKER transcript.",
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["findings", "first_proposal_quote", "summary", "next_session_goal"],
        "properties": {
            "findings": {"type": "array", "items": finding},
            "first_proposal_quote": {
                "type": ["string", "null"],
                "description": "Speaker words where a solution was first proposed, or null.",
            },
            "summary": {"type": "string"},
            "next_session_goal": {"type": "string"},
        },
    }


def validate_audit(data: object) -> RawAudit:
    """Validate a decoded model answer; raise ValueError with a short message if invalid."""
    try:
        return RawAudit.model_validate(data)
    except ValidationError as exc:
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        raise ValueError("; ".join(parts)) from exc
