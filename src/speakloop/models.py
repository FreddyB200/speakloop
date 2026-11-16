"""Core data contracts shared by every SpeakLoop module.

All models are immutable and reject unknown fields. Times are float seconds from the start
of the recording.
"""

import re
import secrets
import unicodedata
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TrackId = Literal["mic", "system"]

SESSION_ID_PATTERN = r"^\d{8}-\d{6}-[0-9a-f]{4}$"
_SESSION_ID_RE = re.compile(SESSION_ID_PATTERN)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def is_valid_session_id(value: str) -> bool:
    """Return True if value matches `YYYYMMDD-HHMMSS-xxxx` and the date-time part is real."""
    if _SESSION_ID_RE.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return False
    return True


def new_session_id(now: datetime | None = None) -> str:
    """Create a session id like `20260101-093000-a1b2` (4 random lowercase hex chars)."""
    moment = now if now is not None else datetime.now(UTC)
    return f"{moment:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


class _Span(_Frozen):
    start: float = Field(ge=0)
    end: float

    @model_validator(mode="after")
    def _check_order(self) -> "_Span":
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class Track(_Frozen):
    id: TrackId
    role: Literal["speaker", "interlocutor"]
    audio_path: Path | None = None


class Word(_Span):
    text: str = Field(min_length=1)
    probability: float | None = Field(default=None, ge=0, le=1)
    track: TrackId


class Segment(_Span):
    text: str
    track: TrackId
    words: tuple[Word, ...] = ()

    @model_validator(mode="after")
    def _check_words(self) -> "Segment":
        for word in self.words:
            if word.start < self.start or word.end > self.end:
                raise ValueError("every word must lie within the segment bounds")
        return self


class Transcript(_Frozen):
    session_id: str
    language: str | None
    backend: str
    model: str
    prompt: str | None
    segments: tuple[Segment, ...]

    def words(self, track: TrackId | None = None) -> tuple[Word, ...]:
        """All words ordered by start time, optionally restricted to one track."""
        found = [w for s in self.segments if track is None or s.track == track for w in s.words]
        return tuple(sorted(found, key=lambda w: w.start))

    def text(self, track: TrackId | None = None) -> str:
        """Segment texts joined with single spaces, ordered by start time."""
        chosen = sorted(
            (s for s in self.segments if track is None or s.track == track),
            key=lambda s: s.start,
        )
        return " ".join(s.text.strip() for s in chosen if s.text.strip())


class SessionKind(StrEnum):
    DISCOVERY = "discovery"
    PRESSURE = "pressure"
    DEEP_DIVE = "deep_dive"
    THINK_ALOUD = "think_aloud"
    BEHAVIORAL = "behavioral"
    DEMO = "demo"
    FREE = "free"
    SHADOWING = "shadowing"
    RETELL_432 = "retell_432"


class Session(_Frozen):
    id: str = Field(pattern=SESSION_ID_PATTERN)
    created_at: datetime
    kind: SessionKind
    scenario_id: str | None = None
    tracks: tuple[Track, ...] = Field(min_length=1)
    notes: str | None = None

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _check_tracks(self) -> "Session":
        ids = [t.id for t in self.tracks]
        if len(set(ids)) != len(ids):
            raise ValueError("at most one track per id")
        if sum(1 for t in self.tracks if t.role == "speaker") != 1:
            raise ValueError("exactly one track must have role 'speaker'")
        return self


class Evidence(_Span):
    quote: str = Field(min_length=1)
    track: TrackId

    @field_validator("quote", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        # Model output often carries stray whitespace: strip it instead of rejecting the quote.
        return value.strip() if isinstance(value, str) else value


class Pause(_Span):
    @property
    def duration(self) -> float:
        return self.end - self.start


class FdeMetrics(_Frozen):
    clarifying_questions_before_proposal: int | None
    talk_ratio: float | None = Field(ge=0, le=1)
    risky_commitments: tuple[Evidence, ...] = ()
    closed_with_next_steps: bool | None


class Metrics(_Frozen):
    session_id: str
    speaker_track: TrackId
    duration_s: float = Field(ge=0)
    word_count: int = Field(ge=0)
    wpm_mean: float = Field(ge=0)
    wpm_windows: tuple[float, ...]
    wpm_cv: float | None
    long_pause_threshold_s: float = Field(gt=0)
    long_pauses: tuple[Pause, ...]
    # A plain dict (word -> count): pydantic copies it on validation and the model is
    # frozen, so fields cannot be reassigned. JSON round trips and schemas stay simple.
    filler_counts: dict[str, int]
    fillers_per_100w: float = Field(ge=0)
    repetitions: int = Field(ge=0)
    false_starts: int = Field(ge=0)
    mattr: float | None = Field(ge=0, le=1)
    response_latencies_s: tuple[float, ...] | None
    fde: FdeMetrics | None = None


class FindingCategory(StrEnum):
    GRAMMAR = "grammar"
    VOCABULARY = "vocabulary"
    NATURALNESS = "naturalness"
    PRONUNCIATION = "pronunciation"
    FLUENCY = "fluency"
    STRUCTURE = "structure"
    TECHNICAL_ACCURACY = "technical_accuracy"
    CUSTOMER_JUDGMENT = "customer_judgment"


class Finding(_Frozen):
    id: str
    session_id: str
    category: FindingCategory
    title: str = Field(min_length=1)
    explanation: str
    suggestion: str | None
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    severity: Literal[1, 2, 3]
    source: Literal["metrics", "audit"]


class AuditSummary(_Frozen):
    """Outcome of the AI audit besides the findings, saved so reports can be re-rendered."""

    summary: str | None
    next_session_goal: str | None
    proposal_time_s: float | None
    dropped_quotes: int = Field(ge=0)
    discarded_findings: int = Field(ge=0)
    rubric_version: str | None
    error: str | None


class ItemKind(StrEnum):
    GRAMMAR_PATTERN = "grammar_pattern"
    PHRASE = "phrase"
    WORD = "word"
    SOUND = "sound"


class ItemStatus(StrEnum):
    NEW = "new"
    LEARNING = "learning"
    MASTERED = "mastered"


def normalize_key(kind: ItemKind, text: str) -> str:
    """Build a de-duplication key: `<kind>:<lowercase-ascii-dashed-text>`."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return f"{kind.value}:{slug}"


class Item(_Frozen):
    id: str
    kind: ItemKind
    key: str
    front: str
    back: str
    examples: tuple[str, ...] = ()
    source_finding_ids: tuple[str, ...] = ()
    status: ItemStatus = ItemStatus.NEW
    uses_correct: int = 0
    uses_incorrect: int = 0
    last_seen_session: str | None = None


class ItemUse(_Frozen):
    item_id: str
    session_id: str
    correct: bool
    evidence: Evidence
