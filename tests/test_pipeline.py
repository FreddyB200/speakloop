"""Pipeline tests with fake backends (synthetic data, no Buzz, no Claude)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from speakloop.audit.base import AuditBackendError
from speakloop.audit.rubric import load_rubric
from speakloop.models import SessionKind, Transcript
from speakloop.pipeline import (
    DEFAULT_TRANSCRIPTION_PROMPT,
    PipelineError,
    build_transcription_prompt,
    merge_transcripts,
    run_session,
)
from speakloop.transcribe import FakeBackend
from speakloop.transcribe.base import TranscriptionError
from speakloop.workspace import Workspace

NOW = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)

SPEAKER_TEXT = "Um we call API every hour . so we could add a queue and then I think we are done"


def words(text: str, step: float = 0.5) -> list[tuple[str, float, float]]:
    return [(w, i * step, i * step + 0.4) for i, w in enumerate(text.split())]


class FakeAuditor:
    name = "fake-audit"

    def __init__(self, answer: dict[str, object] | None = None, fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.prompts: list[str] = []

    def complete_json(
        self, prompt: str, *, json_schema: dict[str, object], timeout_s: float = 300.0
    ) -> dict[str, object]:
        self.prompts.append(prompt)
        if self.fail:
            raise AuditBackendError("boom")
        assert self.answer is not None
        return self.answer


def canned() -> dict[str, object]:
    return {
        "findings": [
            {
                "category": "grammar",
                "title": "Missing article",
                "explanation": "x",
                "suggestion": "the API",
                "severity": 2,
                "quotes": ["we call API every hour"],
            },
            {
                "category": "naturalness",
                "title": "Invented",
                "explanation": "x",
                "suggestion": None,
                "severity": 1,
                "quotes": ["this never happened"],
            },
        ],
        "first_proposal_quote": "we could add a queue",
        "summary": "Good session.",
        "next_session_goal": "Ask more questions.",
    }


def run(tmp_path: Path, **kwargs: object):  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "audio_system": None,
        "kind": SessionKind.DISCOVERY,
        "scenario_id": None,
        "workspace": Workspace(tmp_path / "ws"),
        "transcriber": FakeBackend(words(SPEAKER_TEXT)),
        "auditor": None,
        "rubric": load_rubric(),
        "now": NOW,
    }
    defaults.update(kwargs)
    return run_session(tmp_path / "mic.wav", **defaults)  # type: ignore[arg-type]


def test_end_to_end_two_tracks(tmp_path: Path) -> None:
    class PerTrack(FakeBackend):
        def transcribe(self, audio: Path, **kw):  # type: ignore[no-untyped-def]
            self.calls.append(audio)
            self._words = tuple(
                words("tell me about the pipeline", 0.5)
                if kw["track"] == "system"
                else words(SPEAKER_TEXT, 0.5)
            )
            return super().transcribe(audio, **kw)

    ws = Workspace(tmp_path / "ws")
    auditor = FakeAuditor(canned())
    result = run(
        tmp_path,
        audio_system=tmp_path / "sys.wav",
        workspace=ws,
        transcriber=PerTrack(()),
        auditor=auditor,
    )
    assert [t.id for t in result.session.tracks] == ["mic", "system"]
    assert result.session.created_at == NOW
    assert {s.track for s in result.transcript.segments} == {"mic", "system"}
    assert result.transcript.prompt == DEFAULT_TRANSCRIPTION_PROMPT
    starts = [s.start for s in result.transcript.segments]
    assert starts == sorted(starts)
    assert len(result.findings) == 1
    assert result.dropped_quotes == 1
    assert result.discarded_findings == 1
    assert result.audit_error is None
    # proposal time was passed on, so clarifying questions are computable
    assert result.metrics.fde is not None
    assert result.metrics.fde.clarifying_questions_before_proposal is not None
    assert result.metrics.fde.talk_ratio is not None
    sid = result.session.id
    assert ws.load_session(sid) == result.session
    assert ws.load_transcript(sid) == result.transcript
    assert ws.load_metrics(sid) == result.metrics
    assert ws.load_findings(sid) == list(result.findings)
    report = ws.report_path(sid).read_text(encoding="utf-8")
    assert result.report_path == ws.report_path(sid)
    assert "Missing article" in report
    assert "Good session." in report
    assert "Ask more questions." in report
    assert "Invented" not in report
    assert auditor.prompts


def test_no_auditor(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.findings == ()
    assert result.dropped_quotes is None
    assert result.discarded_findings is None
    assert result.metrics.fde is not None
    assert result.metrics.fde.clarifying_questions_before_proposal is None
    assert "No patterns found." in result.report_path.read_text(encoding="utf-8")


def test_no_prompt(tmp_path: Path) -> None:
    result = run(tmp_path, prompt=None)
    assert result.transcript.prompt is None


def test_audit_failure_keeps_session(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    result = run(tmp_path, workspace=ws, auditor=FakeAuditor(fail=True))
    assert result.audit_error is not None
    assert "audit failed" in result.audit_error
    assert "boom" in result.audit_error
    sid = result.session.id
    assert ws.load_transcript(sid).segments
    assert ws.load_metrics(sid).word_count > 0
    assert ws.load_findings(sid) == []
    assert "No patterns found." in ws.report_path(sid).read_text(encoding="utf-8")


def test_transcription_failure(tmp_path: Path) -> None:
    class Broken:
        name = "broken"

        def transcribe(self, audio: Path, **kw: object) -> Transcript:
            raise TranscriptionError("no model")

    ws = Workspace(tmp_path / "ws")
    with pytest.raises(PipelineError, match="transcription failed for track mic: no model"):
        run(tmp_path, workspace=ws, transcriber=Broken())
    assert not ws.list_sessions()


def test_merge_transcripts() -> None:
    a = FakeBackend(words("hello there"), model="m1", language=None).transcribe(
        Path("a"), track="mic", session_id="20260102-093000-abcd"
    )
    b = FakeBackend(words("ok"), model="m2", language="en").transcribe(
        Path("b"), track="system", session_id="20260102-093000-abcd", prompt="p"
    )
    merged = merge_transcripts("20260102-093000-abcd", a, b)
    assert merged.language == "en"
    assert merged.model == "m1+m2"
    assert merged.backend == "fake"
    assert merged.prompt == "p"
    assert len(merged.segments) == 2
    with pytest.raises(ValueError):
        merge_transcripts("20260102-093000-abcd")


def test_prompt_with_glossary(tmp_path: Path) -> None:
    result = run(tmp_path, glossary=["TransMilenio", "Datos Abiertos"])
    assert result.transcript.prompt == (
        DEFAULT_TRANSCRIPTION_PROMPT + " Names and terms: TransMilenio, Datos Abiertos."
    )


def test_glossary_not_applied_without_prompt_or_terms(tmp_path: Path) -> None:
    assert run(tmp_path, prompt=None, glossary=["X"]).transcript.prompt is None
    assert run(tmp_path, glossary=[]).transcript.prompt == DEFAULT_TRANSCRIPTION_PROMPT


def test_glossary_truncated_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    terms = [f"Term{i:03d}" for i in range(200)]
    with caplog.at_level("WARNING"):
        prompt = build_transcription_prompt(DEFAULT_TRANSCRIPTION_PROMPT, terms)
    assert len(prompt) <= 800
    assert prompt.startswith(DEFAULT_TRANSCRIPTION_PROMPT + " Names and terms: Term000, Term001")
    assert prompt.endswith(".")
    assert "glossary truncated" in caplog.text


def test_saves_audit_and_transcript_in_report(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    result = run(tmp_path, workspace=ws, auditor=FakeAuditor(canned()))
    audit = ws.load_audit(result.session.id)
    assert audit is not None
    assert audit.summary == "Good session."
    assert audit.next_session_goal == "Ask more questions."
    assert audit.dropped_quotes == 1
    assert audit.discarded_findings == 1
    assert audit.rubric_version and audit.error is None
    assert audit.proposal_time_s is not None
    assert "## Transcript" in result.report_path.read_text(encoding="utf-8")


def test_audit_error_and_no_audit_persistence(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    failed = run(tmp_path, workspace=ws, auditor=FakeAuditor(fail=True))
    saved = ws.load_audit(failed.session.id)
    assert saved is not None
    assert saved.error is not None and "boom" in saved.error
    assert saved.summary is None
    skipped = run(tmp_path, workspace=ws)
    assert ws.load_audit(skipped.session.id) is None


def test_on_step_and_keep_audio(tmp_path: Path) -> None:
    audio = tmp_path / "in.m4a"
    audio.write_bytes(b"abc")
    steps: list[str] = []
    ws = Workspace(tmp_path / "ws2")
    result = run_session(
        audio,
        audio_system=None,
        kind=SessionKind.FREE,
        scenario_id=None,
        workspace=ws,
        transcriber=FakeBackend(words(SPEAKER_TEXT)),
        auditor=FakeAuditor(canned()),
        rubric=load_rubric(),
        on_step=steps.append,
        keep_audio=True,
    )
    assert steps == ["transcribing", "analyzing", "auditing", "saving"]
    stored = ws.load_session(result.session.id).tracks[0].audio_path
    assert stored == Path("audio/mic.m4a")
    assert (ws.session_dir(result.session.id) / "audio" / "mic.m4a").read_bytes() == b"abc"
