"""Quote verification, rubric, prompting and run_audit tests (synthetic data only)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from speakloop.audit.base import AuditBackendError
from speakloop.audit.prompting import render_prompt
from speakloop.audit.rubric import RubricError, load_rubric
from speakloop.audit.run import run_audit
from speakloop.audit.schema import RawAudit, RawFinding, audit_json_schema, validate_audit
from speakloop.audit.verify import locate_quote, verify_audit
from speakloop.models import (
    FdeMetrics,
    FindingCategory,
    Metrics,
    Segment,
    Session,
    SessionKind,
    Track,
    Transcript,
    Word,
)

SID = "20260101-093000-a1b2"


def make_words(text: str, track: str, start: float) -> tuple[Word, ...]:
    words = []
    for i, token in enumerate(text.split()):
        words.append(
            Word(text=token, start=start + i * 0.5, end=start + i * 0.5 + 0.4, track=track)  # type: ignore[arg-type]
        )
    return tuple(words)


def make_segment(text: str, track: str, start: float) -> Segment:
    words = make_words(text, track, start)
    return Segment(
        text=text,
        start=start,
        end=words[-1].end,
        track=track,
        words=words,  # type: ignore[arg-type]
    )


SPEAKER_TEXT = "So, we call API every hour. Um, I don't know, maybe we could add a queue."
TRANSCRIPT = Transcript(
    session_id=SID,
    language="en",
    backend="fake",
    model="fake",
    prompt=None,
    segments=(
        make_segment("What is the main pain point here?", "system", 0.0),
        make_segment(SPEAKER_TEXT, "mic", 65.0),
        make_segment("Interesting, tell me about the queue idea.", "system", 90.0),
    ),
)
SESSION = Session(
    id=SID,
    created_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
    kind=SessionKind.DISCOVERY,
    scenario_id="scn-1",
    tracks=(Track(id="mic", role="speaker"), Track(id="system", role="interlocutor")),
)
METRICS = Metrics(
    session_id=SID,
    speaker_track="mic",
    duration_s=100.0,
    word_count=15,
    wpm_mean=120.0,
    wpm_windows=(),
    wpm_cv=None,
    long_pause_threshold_s=2.0,
    long_pauses=(),
    filler_counts={"um": 1},
    fillers_per_100w=6.0,
    repetitions=0,
    false_starts=0,
    mattr=None,
    response_latencies_s=None,
    fde=FdeMetrics(
        clarifying_questions_before_proposal=None,
        talk_ratio=0.6,
        closed_with_next_steps=None,
    ),
)
SPEAKER_WORDS = TRANSCRIPT.words("mic")


def finding(quotes: list[str], severity: int = 2, title: str = "t") -> RawFinding:
    return RawFinding.model_validate(
        {
            "category": "grammar",
            "title": title,
            "explanation": "e",
            "suggestion": None,
            "severity": severity,
            "quotes": quotes,
        }
    )


def audit_of(findings: list[RawFinding], proposal: str | None = None) -> RawAudit:
    return RawAudit(
        findings=findings, first_proposal_quote=proposal, summary="s", next_session_goal="g"
    )


def test_exact_match_uses_transcript_words_and_timings() -> None:
    result = verify_audit(audit_of([finding(["we call API every hour."])]), TRANSCRIPT, "mic")
    (verified,) = result.findings
    (ev,) = verified.evidence
    assert ev.quote == "we call API every hour."
    assert ev.start == 65.5
    assert ev.track == "mic"
    assert result.dropped_quotes == 0


@pytest.mark.parametrize(
    "quote",
    [
        "WE CALL api EVERY hour",
        "we  call   API every\nhour",
        "we, call API: every hour!",
        "“we call API every hour”",
    ],
)
def test_normalization_variants_match(quote: str) -> None:
    matched = locate_quote(quote, SPEAKER_WORDS)
    assert matched is not None
    assert " ".join(w.text for w in matched) == "we call API every hour."


def test_curly_apostrophe_matches_straight() -> None:
    matched = locate_quote("I don\u2019t know", SPEAKER_WORDS)
    assert matched is not None
    assert " ".join(w.text for w in matched) == "I don't know,"


def test_evidence_quote_is_never_the_model_text() -> None:
    result = verify_audit(audit_of([finding(["WE CALL api"])]), TRANSCRIPT, "mic")
    assert result.findings[0].evidence[0].quote == "we call API"


def test_hallucinated_quote_dropped_but_finding_kept() -> None:
    result = verify_audit(
        audit_of([finding(["we call API", "this was never said"])]), TRANSCRIPT, "mic"
    )
    assert len(result.findings) == 1
    assert len(result.findings[0].evidence) == 1
    assert result.dropped_quotes == 1
    assert result.discarded_findings == 0


def test_finding_without_verified_quote_is_discarded() -> None:
    result = verify_audit(audit_of([finding(["nothing like this"])]), TRANSCRIPT, "mic")
    assert result.findings == ()
    assert result.dropped_quotes == 1
    assert result.discarded_findings == 1


def test_quote_from_interlocutor_not_matched() -> None:
    result = verify_audit(audit_of([finding(["main pain point"])]), TRANSCRIPT, "mic")
    assert result.findings == ()
    assert locate_quote("main pain point", TRANSCRIPT.words("system")) is not None


def test_empty_or_punctuation_only_quote_not_matched() -> None:
    assert locate_quote("...", SPEAKER_WORDS) is None
    assert locate_quote("", SPEAKER_WORDS) is None


def test_proposal_time_located_and_missing() -> None:
    found = verify_audit(audit_of([], "maybe we could add a queue"), TRANSCRIPT, "mic")
    assert found.proposal_time_s == pytest.approx(65.0 + 0.5 * 10)
    missing = verify_audit(audit_of([], "we should rewrite everything"), TRANSCRIPT, "mic")
    assert missing.proposal_time_s is None
    assert verify_audit(audit_of([], None), TRANSCRIPT, "mic").proposal_time_s is None


class FakeBackend:
    name = "fake"

    def __init__(self, answer: dict[str, object]) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete_json(
        self, prompt: str, *, json_schema: dict[str, object], timeout_s: float = 300.0
    ) -> dict[str, object]:
        self.prompts.append(prompt)
        return self.answer


def raw_dict(findings: list[dict[str, object]], proposal: str | None = None) -> dict[str, object]:
    return {
        "findings": findings,
        "first_proposal_quote": proposal,
        "summary": "sum",
        "next_session_goal": "goal",
    }


def raw_finding_dict(quote: str, severity: int, title: str) -> dict[str, object]:
    return {
        "category": "fluency",
        "title": title,
        "explanation": "e",
        "suggestion": "s",
        "severity": severity,
        "quotes": [quote],
    }


def test_run_audit_caps_at_five_sorted_by_severity() -> None:
    quotes = [
        "we call",
        "API every",
        "every hour",
        "I don't",
        "don't know",
        "add a queue",
        "maybe we",
    ]
    severities = [1, 3, 2, 1, 3, 2, 1]
    findings = [
        raw_finding_dict(q, s, f"f{i}")
        for i, (q, s) in enumerate(zip(quotes, severities, strict=True))
    ]
    backend = FakeBackend(raw_dict(findings, "add a queue"))
    result = run_audit(TRANSCRIPT, SESSION, METRICS, backend, load_rubric())
    assert len(result.findings) == 5
    assert [f.severity for f in result.findings] == [3, 3, 2, 2, 1]
    assert [f.id for f in result.findings] == [f"{SID}-audit-{i}" for i in range(1, 6)]
    assert all(f.source == "audit" and f.session_id == SID for f in result.findings)
    assert result.findings[0].category is FindingCategory.FLUENCY
    assert result.discarded_findings == 2
    assert result.proposal_time_s is not None
    assert result.summary == "sum"
    assert result.next_session_goal == "goal"


def test_run_audit_counts_drops_and_discards() -> None:
    findings = [raw_finding_dict("we call", 2, "ok"), raw_finding_dict("invented words", 3, "bad")]
    result = run_audit(TRANSCRIPT, SESSION, METRICS, FakeBackend(raw_dict(findings)), load_rubric())
    assert [f.title for f in result.findings] == ["ok"]
    assert result.dropped_quotes == 1
    assert result.discarded_findings == 1


def test_run_audit_invalid_answer_raises() -> None:
    with pytest.raises(AuditBackendError, match="validation"):
        run_audit(TRANSCRIPT, SESSION, METRICS, FakeBackend({"findings": 3}), load_rubric())


def test_run_audit_prompt_contains_context() -> None:
    backend = FakeBackend(raw_dict([]))
    run_audit(TRANSCRIPT, SESSION, METRICS, backend, load_rubric())
    prompt = backend.prompts[0]
    assert "[01:05] So, we call API" in prompt
    assert "[00:00] What is the main pain point here?" in prompt
    assert "scn-1" in prompt and "discovery" in prompt
    assert "fillers_per_100w" in prompt
    assert "${" not in prompt


def test_render_prompt_without_interlocutor() -> None:
    session = SESSION.model_copy(update={"tracks": (Track(id="mic", role="speaker"),)})
    prompt = render_prompt(
        rubric=load_rubric(), session=session, transcript=TRANSCRIPT, metrics=METRICS
    )
    assert "(none)" in prompt
    assert "main pain point" not in prompt


def test_default_rubric_loads() -> None:
    rubric = load_rubric()
    assert rubric.max_patterns == 5
    assert {c.name for c in rubric.categories} <= {c.value for c in FindingCategory}
    assert rubric.fde_dimensions
    assert "spoken" in rubric.spoken_english_instruction.lower()


@pytest.mark.parametrize(
    "toml",
    [
        "not toml [",
        'version="v"\nmax_patterns=5\nspoken_english_instruction="x"\n',  # no categories
        'version="v"\nmax_patterns=5\nspoken_english_instruction="x"\n'
        '[[categories]]\nname="bogus"\ndescription="d"\n',
        'version="v"\nmax_patterns=0\nspoken_english_instruction="x"\n'
        '[[categories]]\nname="grammar"\ndescription="d"\n',
        'version="v"\nmax_patterns=5\nspoken_english_instruction="x"\nextra=1\n'
        '[[categories]]\nname="grammar"\ndescription="d"\n',
        'version="v"\nmax_patterns=5\nspoken_english_instruction="x"\n'
        '[[categories]]\nname="grammar"\ndescription="d"\n'
        '[[categories]]\nname="grammar"\ndescription="d"\n',
    ],
)
def test_invalid_rubrics_rejected(tmp_path: Path, toml: str) -> None:
    path = tmp_path / "r.toml"
    path.write_text(toml)
    with pytest.raises(RubricError):
        load_rubric(path)


def test_missing_rubric_file(tmp_path: Path) -> None:
    with pytest.raises(RubricError):
        load_rubric(tmp_path / "nope.toml")


def test_schema_and_validator_agree() -> None:
    schema = audit_json_schema()
    assert schema["required"] == [
        "findings",
        "first_proposal_quote",
        "summary",
        "next_session_goal",
    ]
    good = raw_dict([raw_finding_dict("we call", 2, "t")])
    assert validate_audit(good).findings[0].severity == 2
    with pytest.raises(ValueError):
        validate_audit(raw_dict([raw_finding_dict("we call", 7, "t")]))
