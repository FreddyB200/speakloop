"""Tests for the Markdown report.

Golden files live in `tests/fixtures/export/`. Regenerate them after an intentional change
with `UPDATE_SNAPSHOTS=1 uv run pytest tests/test_export_report.py`.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from speakloop.export import escape_markdown, format_timestamp, render_report
from speakloop.models import (
    Evidence,
    FdeMetrics,
    Finding,
    FindingCategory,
    Metrics,
    Pause,
    Segment,
    Session,
    SessionKind,
    Track,
    Transcript,
)

FIXTURES = Path(__file__).parent / "fixtures" / "export"
SID = "20260105-093000-a1b2"


def _session(two_tracks: bool, kind: SessionKind = SessionKind.FREE) -> Session:
    tracks = [Track(id="mic", role="speaker")]
    if two_tracks:
        tracks.append(Track(id="system", role="interlocutor"))
    return Session(
        id=SID,
        created_at=datetime(2026, 1, 5, 9, 30, tzinfo=UTC),
        kind=kind,
        scenario_id="discovery-call" if two_tracks else None,
        tracks=tuple(tracks),
    )


def _metrics(fde: FdeMetrics | None) -> Metrics:
    return Metrics(
        session_id=SID,
        speaker_track="mic",
        duration_s=372.0,
        word_count=810,
        wpm_mean=130.46,
        wpm_windows=(120.0, 140.0),
        wpm_cv=0.12345,
        long_pause_threshold_s=2.0,
        long_pauses=(Pause(start=10, end=13), Pause(start=50, end=54)),
        filler_counts={"um": 5},
        fillers_per_100w=3.456,
        repetitions=4,
        false_starts=2,
        mattr=0.7123,
        response_latencies_s=(1.0, 3.0, 2.0) if fde else None,
        fde=fde,
    )


def _findings() -> list[Finding]:
    return [
        Finding(
            id="f1",
            session_id=SID,
            category=FindingCategory.GRAMMAR,
            title="Missing article",
            explanation="You often drop 'the' before singular nouns.",
            suggestion="Say 'the pipeline' instead of 'pipeline'.",
            evidence=(Evidence(start=65.2, end=68.0, quote="we deploy pipeline", track="mic"),),
            severity=2,
            source="audit",
        ),
        Finding(
            id="f2",
            session_id=SID,
            category=FindingCategory.CUSTOMER_JUDGMENT,
            title="Promised a date too early",
            explanation="A date was committed before scoping.",
            suggestion=None,
            evidence=(
                Evidence(start=3700.0, end=3702.0, quote="we ship Friday", track="mic"),
                Evidence(start=5.0, end=6.0, quote="when can you ship?", track="system"),
            ),
            severity=3,
            source="audit",
        ),
    ]


def _fde() -> FdeMetrics:
    return FdeMetrics(
        clarifying_questions_before_proposal=1,
        talk_ratio=0.625,
        risky_commitments=(
            Evidence(start=125.0, end=128.0, quote="I guarantee zero downtime", track="mic"),
        ),
        closed_with_next_steps=False,
    )


def _transcript(prompt: str | None = "Um, uh.") -> Transcript:
    def seg(text: str, start: float, track: str) -> Segment:
        return Segment(text=text, start=start, end=start + 2, track=track)  # type: ignore[arg-type]

    return Transcript(
        session_id=SID,
        language="en",
        backend="fasterwhisper",
        model="small.en",
        prompt=prompt,
        segments=(
            seg("We call the *API* daily.", 3.4, "mic"),
            seg("Tell me more.", 12.0, "system"),
            seg("Late talk.", 3723.0, "mic"),
            seg("   ", 20.0, "mic"),
        ),
    )


def _check_snapshot(name: str, text: str) -> None:
    path = FIXTURES / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == text


def _front_matter(text: str) -> dict[str, object]:
    lines = text.split("\n")
    assert lines[0] == "---"
    end = lines.index("---", 1)
    result: dict[str, object] = {}
    for line in lines[1:end]:
        key, _, raw = line.partition(": ")
        result[key] = json.loads(raw)  # null/true/false/numbers/strings/inline lists
    return result


def test_snapshot_single_track() -> None:
    text = render_report(_session(False), _metrics(None), _findings()[:1])
    _check_snapshot("single_track.md", text)


def test_snapshot_two_track_fde() -> None:
    text = render_report(
        _session(True, SessionKind.DISCOVERY),
        _metrics(_fde()),
        _findings(),
        summary="Solid scoping, but a risky promise at the end.",
        next_session_goal="Ask two more questions before proposing.",
    )
    _check_snapshot("two_track_fde.md", text)


def test_snapshot_transcript_section() -> None:
    text = render_report(
        _session(True, SessionKind.DISCOVERY),
        _metrics(_fde()),
        _findings()[:1],
        summary="Short.",
        next_session_goal="Ask more.",
        transcript=_transcript(),
    )
    _check_snapshot("two_track_transcript.md", text)


def test_transcript_section_content() -> None:
    text = render_report(_session(False), _metrics(None), [], transcript=_transcript())
    assert text.rstrip().split("\n\n")[-2] == "## Transcript"
    assert "> [!quote]- Transcript as recognized (fasterwhisper:small.en)" in text
    assert "> **[00:03]** We call the \\*API\\* daily." in text
    assert "other speaker" not in text  # single track: no interlocutor marker
    assert "> **[1:02:03]** Late talk." in text
    assert "> *Initial prompt: Um, uh.*" in text
    assert text.index("[00:03]") < text.index("[00:12]") < text.index("[1:02:03]")


def test_transcript_marks_interlocutor_and_no_prompt() -> None:
    text = render_report(_session(True), _metrics(_fde()), [], transcript=_transcript(prompt=None))
    assert "> **[00:12]** *(other speaker)* Tell me more." in text
    assert "Initial prompt" not in text


def test_no_transcript_section_by_default() -> None:
    assert "## Transcript" not in render_report(_session(False), _metrics(None), [])


def test_front_matter_values_and_nulls() -> None:
    fm = _front_matter(render_report(_session(False), _metrics(None), _findings()))
    assert fm["type"] == "speakloop-session"
    assert fm["date"] == "2026-01-05"
    assert fm["scenario"] is None
    assert fm["duration_min"] == 6.2
    assert fm["long_pauses"] == 2
    assert fm["response_latency_median_s"] is None
    assert fm["clarifying_questions"] is None
    assert fm["risky_commitments"] is None
    assert fm["findings"] == 2
    assert fm["top_patterns"] == ["Promised a date too early", "Missing article"]
    assert fm["next_goal"] is None


def test_front_matter_fde() -> None:
    fm = _front_matter(
        render_report(
            _session(True), _metrics(_fde()), [], next_session_goal='Say "no" politely: yes'
        )
    )
    assert fm["response_latency_median_s"] == 2.0
    assert fm["clarifying_questions"] == 1
    assert fm["talk_ratio"] == 0.625
    assert fm["risky_commitments"] == 1
    assert fm["closed_with_next_steps"] is False
    assert fm["next_goal"] == 'Say "no" politely: yes'
    assert fm["top_patterns"] == []


def test_fde_section_only_with_fde() -> None:
    assert "## FDE" not in render_report(_session(False), _metrics(None), [])
    assert "## FDE" in render_report(_session(True), _metrics(_fde()), [])


def test_at_most_five_findings_shown() -> None:
    base = _findings()[0]
    many = [base.model_copy(update={"title": f"T{i}"}) for i in range(7)]
    text = render_report(_session(False), _metrics(None), many)
    assert text.count("### ") == 5
    assert _front_matter(text)["findings"] == 7


def test_escaping_in_quotes() -> None:
    evidence = Evidence(start=1, end=2, quote='a*b_c|d>e "q"\nnext', track="mic")
    finding = _findings()[0].model_copy(update={"evidence": (evidence,)})
    text = render_report(_session(False), _metrics(None), [finding])
    assert '> a\\*b\\_c\\|d\\>e "q" next (00:01)' in text
    assert escape_markdown("**x**") == "\\*\\*x\\*\\*"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"),
        (5.9, "00:05"),
        (65, "01:05"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3723, "1:02:03"),
    ],
)
def test_format_timestamp(seconds: float, expected: str) -> None:
    assert format_timestamp(seconds) == expected


def test_deterministic() -> None:
    args = (_session(True), _metrics(_fde()), _findings())
    assert render_report(*args) == render_report(*args)
