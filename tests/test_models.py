"""Tests for the core data contracts."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from speakloop.models import (
    Evidence,
    FdeMetrics,
    Finding,
    FindingCategory,
    Item,
    ItemKind,
    ItemUse,
    Metrics,
    Pause,
    Segment,
    Session,
    SessionKind,
    Track,
    Transcript,
    Word,
    is_valid_session_id,
    new_session_id,
    normalize_key,
)

SID = "20260101-093000-a1b2"


def word(text: str, start: float, end: float, track: str = "mic") -> Word:
    return Word(text=text, start=start, end=end, probability=0.9, track=track)  # type: ignore[arg-type]


def evidence() -> Evidence:
    return Evidence(quote="I has went", start=1.0, end=2.0, track="mic")


def session() -> Session:
    return Session(
        id=SID,
        created_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
        kind=SessionKind.DISCOVERY,
        tracks=(
            Track(id="mic", role="speaker", audio_path=Path("mic.wav")),
            Track(id="system", role="interlocutor"),
        ),
    )


def transcript() -> Transcript:
    return Transcript(
        session_id=SID,
        language="en",
        backend="fake",
        model="tiny",
        prompt=None,
        segments=(
            Segment(
                text="hello there",
                start=0.0,
                end=2.0,
                track="mic",
                words=(word("hello", 0.0, 0.5), word("there", 0.6, 1.0)),
            ),
            Segment(
                text="hi",
                start=0.5,
                end=1.5,
                track="system",
                words=(word("hi", 0.55, 0.8, "system"),),
            ),
        ),
    )


def metrics() -> Metrics:
    return Metrics(
        session_id=SID,
        speaker_track="mic",
        duration_s=60.0,
        word_count=120,
        wpm_mean=120.0,
        wpm_windows=(110.0, 130.0),
        wpm_cv=0.1,
        long_pause_threshold_s=2.0,
        long_pauses=(Pause(start=3.0, end=6.0),),
        filler_counts={"um": 3},
        fillers_per_100w=2.5,
        repetitions=1,
        false_starts=0,
        mattr=0.7,
        response_latencies_s=(1.2,),
        fde=FdeMetrics(
            clarifying_questions_before_proposal=2,
            talk_ratio=0.4,
            risky_commitments=(evidence(),),
            closed_with_next_steps=True,
        ),
    )


def finding() -> Finding:
    return Finding(
        id="f1",
        session_id=SID,
        category=FindingCategory.GRAMMAR,
        title="present perfect vs past simple",
        explanation="x",
        suggestion=None,
        evidence=(evidence(),),
        severity=2,
        source="audit",
    )


def item() -> Item:
    return Item(
        id="i1",
        kind=ItemKind.GRAMMAR_PATTERN,
        key="grammar:x",
        front="f",
        back="b",
        examples=("e",),
        source_finding_ids=("f1",),
    )


@pytest.mark.parametrize(
    "model",
    [
        session(),
        transcript(),
        metrics(),
        finding(),
        item(),
        ItemUse(item_id="i1", session_id=SID, correct=True, evidence=evidence()),
    ],
)
def test_json_round_trip(model: BaseModel) -> None:
    again = type(model).model_validate_json(model.model_dump_json())
    assert again == model


def test_frozen_and_extra_forbidden() -> None:
    w = word("a", 0, 1)
    with pytest.raises(ValidationError):
        w.text = "b"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Word.model_validate(
            {"text": "a", "start": 0, "end": 1, "probability": None, "track": "mic", "extra": 1}
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": "", "start": 0, "end": 1},
        {"text": "a", "start": -1, "end": 1},
        {"text": "a", "start": 2, "end": 1},
        {"text": "a", "start": 0, "end": 1, "probability": 1.5},
    ],
)
def test_word_validation(kwargs: dict[str, Any]) -> None:
    base: dict[str, Any] = {"probability": None, "track": "mic"} | kwargs
    with pytest.raises(ValidationError):
        Word(**base)


def test_segment_words_must_lie_within_bounds() -> None:
    with pytest.raises(ValidationError):
        Segment(text="a", start=0, end=1, track="mic", words=(word("a", 0.5, 1.5),))


def test_transcript_words_and_text() -> None:
    t = transcript()
    assert [w.text for w in t.words()] == ["hello", "hi", "there"]
    assert [w.text for w in t.words("mic")] == ["hello", "there"]
    assert t.text() == "hello there hi"
    assert t.text("system") == "hi"
    assert t.text("mic") == "hello there"


def test_session_id_format() -> None:
    assert is_valid_session_id(SID)
    assert not is_valid_session_id("../x")
    assert not is_valid_session_id("20260101-093000-A1B2")
    assert not is_valid_session_id("20261399-093000-a1b2")  # month 13, day 99
    assert not is_valid_session_id("20260101-256100-a1b2")  # hour 25
    generated = new_session_id(datetime(2026, 1, 1, 9, 30, 0, tzinfo=UTC))
    assert generated.startswith("20260101-093000-")
    assert is_valid_session_id(generated)
    assert is_valid_session_id(new_session_id())


def _session_kwargs(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": SID,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        "kind": SessionKind.FREE,
        "tracks": (Track(id="mic", role="speaker"),),
    }
    return base | over


@pytest.mark.parametrize(
    "over",
    [
        {"id": "bad"},
        {"created_at": datetime(2026, 1, 1)},
        {"tracks": ()},
        {"tracks": (Track(id="mic", role="speaker"), Track(id="mic", role="interlocutor"))},
        {"tracks": (Track(id="mic", role="interlocutor"),)},
        {"tracks": (Track(id="mic", role="speaker"), Track(id="system", role="speaker"))},
    ],
)
def test_session_validation(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Session(**_session_kwargs(**over))


def test_session_valid_minimal() -> None:
    assert Session(**_session_kwargs()).scenario_id is None


@pytest.mark.parametrize("quote", ["", "  "])
def test_evidence_quote_rules(quote: str) -> None:
    with pytest.raises(ValidationError):
        Evidence(quote=quote, start=0, end=1, track="mic")


def test_evidence_quote_is_stripped() -> None:
    assert Evidence(quote="  I has went \n", start=0, end=1, track="mic").quote == "I has went"


def test_evidence_and_pause_order() -> None:
    with pytest.raises(ValidationError):
        Evidence(quote="a", start=2, end=1, track="mic")
    assert Pause(start=1, end=3.5).duration == 2.5
    with pytest.raises(ValidationError):
        Pause(start=3, end=1)


def test_metrics_validation() -> None:
    data = metrics().model_dump()
    for bad in (
        {"duration_s": -1},
        {"long_pause_threshold_s": 0},
        {"mattr": 1.5},
        {"word_count": -1},
        {"fillers_per_100w": -1},
    ):
        with pytest.raises(ValidationError):
            Metrics.model_validate(data | bad)
    with pytest.raises(ValidationError):
        FdeMetrics(
            clarifying_questions_before_proposal=None, talk_ratio=2, closed_with_next_steps=None
        )


def test_finding_validation() -> None:
    data = finding().model_dump()
    for bad in ({"evidence": ()}, {"severity": 4}, {"title": ""}, {"source": "other"}):
        with pytest.raises(ValidationError):
            Finding.model_validate(data | bad)


@pytest.mark.parametrize(
    ("kind", "text", "expected"),
    [
        (
            ItemKind.GRAMMAR_PATTERN,
            "Present Perfect vs. Past Simple",
            "grammar_pattern:present-perfect-vs-past-simple",
        ),
        (ItemKind.WORD, "  Café  Déjà-vu!! ", "word:cafe-deja-vu"),
        (ItemKind.PHRASE, "it's -- a  trade-off", "phrase:it-s-a-trade-off"),
        (ItemKind.SOUND, "/θ/ as in think", "sound:as-in-think"),
    ],
)
def test_normalize_key(kind: ItemKind, text: str, expected: str) -> None:
    assert normalize_key(kind, text) == expected
