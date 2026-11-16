"""Response and request bodies of the HTTP API (API contract v0, snake_case fields)."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from speakloop.models import (
    AuditSummary,
    Finding,
    Metrics,
    Session,
    SessionKind,
    TrackId,
    Transcript,
)

JobStatus = Literal["queued", "transcribing", "analyzing", "auditing", "saving", "done", "error"]

_MODEL_SIZE_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


class Health(BaseModel):
    ok: bool
    version: str


class DoctorCheckOut(BaseModel):
    name: str
    ok: bool
    detail: str


class DoctorOut(BaseModel):
    checks: list[DoctorCheckOut]


class SessionSummary(BaseModel):
    id: str
    created_at: datetime
    kind: SessionKind
    scenario_id: str | None
    duration_s: float
    wpm_mean: float
    fillers_per_100w: float
    findings_count: int
    has_audio: bool
    audit_error: str | None


class SessionDetail(BaseModel):
    session: Session
    metrics: Metrics | None
    findings: list[Finding]
    audit: AuditSummary | None
    transcript: Transcript | None
    audio_tracks: list[TrackId]


class JobCreated(BaseModel):
    job_id: str


class JobOut(BaseModel):
    job_id: str
    status: JobStatus
    session_id: str | None
    error: str | None
    audit_error: str | None


class ExportOut(BaseModel):
    path: str


class SettingsBody(BaseModel):
    """Settings as read and written by the API."""

    model_config = ConfigDict(extra="forbid")

    obsidian_dir: str | None = None
    glossary: list[str] = []
    model_size: str = "small.en"
    language: str = "en"

    @field_validator("obsidian_dir")
    @classmethod
    def _folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if "\0" in value or "\n" in value or "\r" in value:
            raise ValueError("invalid folder path")
        if not (
            value.startswith("~") or value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)
        ):
            raise ValueError("folder must be an absolute path")
        return value

    @field_validator("glossary")
    @classmethod
    def _terms(cls, value: list[str]) -> list[str]:
        terms: list[str] = []
        for raw in value:
            term = raw.strip()
            if not term:
                continue
            if "\n" in term or "\r" in term or "#" in term or "\0" in term:
                raise ValueError("glossary terms cannot contain newlines or '#'")
            terms.append(term)
        return list(dict.fromkeys(terms))

    @field_validator("model_size")
    @classmethod
    def _size(cls, value: str) -> str:
        if not _MODEL_SIZE_RE.match(value):
            raise ValueError("invalid model size")
        return value

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str) -> str:
        if not _LANGUAGE_RE.match(value):
            raise ValueError("invalid language code")
        return value
