"""Pydantic models for mock-interview scenarios."""

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from speakloop.models import SessionKind

_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_DISCOVERY_KINDS = frozenset({SessionKind.DISCOVERY, SessionKind.PRESSURE})
_ROLE_PLAY_KINDS = frozenset(
    {SessionKind.DISCOVERY, SessionKind.PRESSURE, SessionKind.DEEP_DIVE, SessionKind.BEHAVIORAL}
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Question(_Frozen):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    # Short structure hint, shown to the candidate only AFTER the attempt.
    guidance: str | None = Field(default=None, min_length=1)
    time_s: int = Field(default=45, ge=5, le=600)


class HiddenFact(_Frozen):
    id: str = Field(min_length=1)
    fact: str = Field(min_length=1)
    # What kind of question unlocks this fact.
    revealed_when: str = Field(min_length=1)


class Scenario(_Frozen):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: SessionKind
    pack: str = Field(min_length=1)
    difficulty: int = Field(ge=1, le=3)
    candidate_brief: str = Field(min_length=1)
    interviewer_persona: str = Field(min_length=1)
    hidden_facts: tuple[HiddenFact, ...] = ()
    questions: tuple[Question, ...] = Field(min_length=1)
    evaluation_focus: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "Scenario":
        if not _SLUG.match(self.id):
            raise ValueError(f"id must be a lowercase slug, got {self.id!r}")
        if self.kind not in _ROLE_PLAY_KINDS:
            raise ValueError(f"kind {self.kind.value!r} is not valid for an interview scenario")
        if self.kind in _DISCOVERY_KINDS and not self.hidden_facts:
            raise ValueError(f"{self.kind.value} scenarios need at least one hidden fact")
        for label, ids in (
            ("question", [q.id for q in self.questions]),
            ("hidden fact", [f.id for f in self.hidden_facts]),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"duplicate {label} ids")
        for text in (*self.evaluation_focus, *self.phrases):
            if not text.strip():
                raise ValueError("evaluation_focus and phrases must not contain empty text")
        return self
