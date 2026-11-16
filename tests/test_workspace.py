"""Tests for the filesystem workspace."""

import os
from pathlib import Path

import pytest

from speakloop.models import Session, SessionKind, Track
from speakloop.workspace import Workspace
from tests.test_models import SID, finding, metrics, session, transcript


def test_default_uses_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SPEAKLOOP_HOME", str(tmp_path / "home"))
    assert Workspace.default().root == tmp_path / "home"
    monkeypatch.delenv("SPEAKLOOP_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert Workspace.default().root == Path.home() / "SpeakLoop"


def test_save_and_load_everything(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    ws.save_session(session())
    ws.save_transcript(transcript())
    ws.save_metrics(metrics())
    ws.save_findings(SID, [finding()])
    assert ws.load_session(SID) == session()
    assert ws.load_transcript(SID) == transcript()
    assert ws.load_metrics(SID) == metrics()
    assert ws.load_findings(SID) == [finding()]
    assert ws.report_path(SID) == tmp_path / "sessions" / SID / "report.md"
    assert not ws.report_path(SID).exists()
    assert sorted(p.name for p in ws.session_dir(SID).iterdir()) == [
        "findings.json",
        "metrics.json",
        "session.json",
        "transcript.json",
    ]


def test_list_sessions_sorted(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    assert ws.list_sessions() == []
    ids = ["20260102-000000-bbbb", "20260101-000000-aaaa"]
    for sid in ids:
        ws.save_session(
            Session(
                id=sid,
                created_at=session().created_at,
                kind=SessionKind.FREE,
                tracks=(Track(id="mic", role="speaker"),),
            )
        )
    (tmp_path / "sessions" / "junk").mkdir()
    assert [s.id for s in ws.list_sessions()] == sorted(ids)


@pytest.mark.parametrize("bad", ["../evil", "..", "", "a/b", "20260101-000000-ZZZZ"])
def test_path_traversal_rejected(tmp_path: Path, bad: str) -> None:
    ws = Workspace(tmp_path / "root")
    for call in (ws.session_dir, ws.report_path, ws.load_session, ws.load_findings):
        with pytest.raises(ValueError, match="invalid session id"):
            call(bad)
    assert not (tmp_path / "root").exists()


def test_atomic_write_keeps_old_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = Workspace(tmp_path)
    ws.save_session(session())
    before = (ws.session_dir(SID) / "session.json").read_text()

    def boom(src: object, dst: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        ws.save_session(session().model_copy(update={"notes": "changed"}))
    assert (ws.session_dir(SID) / "session.json").read_text() == before
    assert [p.name for p in ws.session_dir(SID).iterdir()] == ["session.json"]


def test_save_report_is_atomic_and_overwrites(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    path = ws.save_report(SID, "one\n")
    ws.save_report(SID, "two\n")
    assert path == ws.report_path(SID)
    assert path.read_text(encoding="utf-8") == "two\n"
    assert [p.name for p in path.parent.iterdir()] == ["report.md"]


def test_audit_roundtrip_and_missing(tmp_path: Path) -> None:
    from speakloop.models import AuditSummary

    ws = Workspace(tmp_path)
    sid = "20260105-093000-a1b2"
    assert ws.load_audit(sid) is None
    audit = AuditSummary(
        summary="s",
        next_session_goal=None,
        proposal_time_s=12.5,
        dropped_quotes=1,
        discarded_findings=2,
        rubric_version="1",
        error=None,
    )
    path = ws.save_audit(sid, audit)
    assert path.name == "audit.json"
    assert ws.load_audit(sid) == audit


def test_glossary_file(tmp_path: Path) -> None:
    ws = Workspace(tmp_path)
    assert ws.load_glossary() == []
    ws.glossary_path.write_text(
        "# my terms\nTransMilenio\n\n  Datos Abiertos  # open data\n", encoding="utf-8"
    )
    assert ws.load_glossary() == ["TransMilenio", "Datos Abiertos"]
