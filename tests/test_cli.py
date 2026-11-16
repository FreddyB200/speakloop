"""Tests for the SpeakLoop command-line interface (no real Buzz or Claude)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from speakloop import __version__, cli
from speakloop.cli import app
from speakloop.transcribe import FakeBackend
from tests.test_pipeline import SPEAKER_TEXT, FakeAuditor, canned, words

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("SPEAKLOOP_HOME", str(root))
    monkeypatch.delenv("SPEAKLOOP_OBSIDIAN_DIR", raising=False)
    monkeypatch.delenv("SPEAKLOOP_BUZZ", raising=False)
    return root


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "session.m4a"
    path.write_bytes(b"not real audio")
    return path


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> FakeAuditor:
    auditor = FakeAuditor(canned())
    monkeypatch.setattr(cli, "make_transcriber", lambda size: FakeBackend(words(SPEAKER_TEXT)))
    monkeypatch.setattr(cli, "make_auditor", lambda: auditor)
    return auditor


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_all_ok(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buzz = tmp_path / "buzz"
    buzz.write_text("#!/bin/sh\n")
    buzz.chmod(0o755)
    monkeypatch.setenv("SPEAKLOOP_BUZZ", str(buzz))
    monkeypatch.setattr("speakloop.cli.shutil.which", lambda _name: "/usr/local/bin/claude")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "claude: found at /usr/local/bin/claude" in result.output
    assert f"buzz: found at {buzz}" in result.output
    assert "is writable" in result.output
    assert home.is_dir()


def test_doctor_claude_missing(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buzz = tmp_path / "buzz"
    buzz.write_text("#!/bin/sh\n")
    buzz.chmod(0o755)
    monkeypatch.setenv("SPEAKLOOP_BUZZ", str(buzz))
    monkeypatch.setattr("speakloop.cli.shutil.which", lambda _name: None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "claude: NOT FOUND" in result.output
    assert "buzz: found" in result.output


def test_doctor_buzz_missing(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("speakloop.cli.shutil.which", lambda _name: "/x/claude")
    monkeypatch.setattr(
        cli,
        "resolve_executable",
        lambda: (_ for _ in ()).throw(cli.TranscriptionError("Buzz executable not found")),
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "buzz: NOT FOUND" in result.output


def test_doctor_workspace_not_writable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("SPEAKLOOP_HOME", str(blocker / "sub"))
    monkeypatch.setattr("speakloop.cli.shutil.which", lambda _name: "/x/claude")
    monkeypatch.setattr(cli, "resolve_executable", lambda: Path("/x/buzz"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "workspace: NOT WRITABLE" in result.output


def test_audit_happy_path(home: Path, audio: Path, fakes: FakeAuditor) -> None:
    result = runner.invoke(app, ["audit", str(audio), "--kind", "discovery"])
    assert result.exit_code == 0, result.output
    assert "session: " in result.output
    assert "wpm: " in result.output
    assert "fillers per 100 words: " in result.output
    assert "findings: 1" in result.output
    assert "dropped quotes: 1" in result.output
    assert "discarded findings: 1" in result.output
    reports = list(home.glob("sessions/*/report.md"))
    assert len(reports) == 1
    assert str(reports[0]) in result.output
    assert "exported" not in result.output


def test_audit_no_audit(home: Path, audio: Path, fakes: FakeAuditor) -> None:
    result = runner.invoke(app, ["audit", str(audio), "--no-audit", "--no-prompt"])
    assert result.exit_code == 0, result.output
    assert "findings: 0" in result.output
    assert "dropped quotes" not in result.output
    assert not fakes.prompts


def test_audit_missing_file(home: Path, tmp_path: Path, fakes: FakeAuditor) -> None:
    result = runner.invoke(app, ["audit", str(tmp_path / "nope.m4a")])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_audit_missing_system_file(home: Path, audio: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["audit", str(audio), "--system", str(tmp_path / "nope.m4a")])
    assert result.exit_code == 1
    assert "system audio file not found" in result.output


def test_audit_invalid_kind(home: Path, audio: Path) -> None:
    result = runner.invoke(app, ["audit", str(audio), "--kind", "bogus"])
    assert result.exit_code == 2


def test_audit_transcription_failure(
    home: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        name = "broken"

        def transcribe(self, *a: object, **k: object) -> None:
            raise cli.TranscriptionError("no buzz")

    monkeypatch.setattr(cli, "make_transcriber", lambda size: Broken())
    monkeypatch.setattr(cli, "make_auditor", lambda: FakeAuditor(canned()))
    result = runner.invoke(app, ["audit", str(audio)])
    assert result.exit_code == 1
    assert "transcription failed" in result.output
    assert "no buzz" in result.output


def test_audit_failure_exits_nonzero_but_writes_report(
    home: Path, audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "make_transcriber", lambda size: FakeBackend(words(SPEAKER_TEXT)))
    monkeypatch.setattr(cli, "make_auditor", lambda: FakeAuditor(fail=True))
    result = runner.invoke(app, ["audit", str(audio)])
    assert result.exit_code == 1
    assert "audit failed" in result.output
    assert len(list(home.glob("sessions/*/report.md"))) == 1


def test_audit_system_track(home: Path, audio: Path, tmp_path: Path, fakes: FakeAuditor) -> None:
    system = tmp_path / "sys.m4a"
    system.write_bytes(b"x")
    result = runner.invoke(app, ["audit", str(audio), "--system", str(system), "--scenario", "s1"])
    assert result.exit_code == 0, result.output


def test_obsidian_option(home: Path, audio: Path, tmp_path: Path, fakes: FakeAuditor) -> None:
    vault = tmp_path / "vault"
    result = runner.invoke(app, ["audit", str(audio), "--obsidian-dir", str(vault)])
    assert result.exit_code == 0, result.output
    assert len(list(vault.glob("*.md"))) == 1
    assert "exported: " in result.output


def test_obsidian_env(
    home: Path, audio: Path, tmp_path: Path, fakes: FakeAuditor, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault-env"
    monkeypatch.setenv("SPEAKLOOP_OBSIDIAN_DIR", str(vault))
    result = runner.invoke(app, ["audit", str(audio)])
    assert result.exit_code == 0, result.output
    assert len(list(vault.glob("*.md"))) == 1


def test_obsidian_relative_dir_fails(home: Path, audio: Path, fakes: FakeAuditor) -> None:
    result = runner.invoke(app, ["audit", str(audio), "--obsidian-dir", "relative/dir"])
    assert result.exit_code == 1
    assert "export failed" in result.output


def test_workspace_option(audio: Path, tmp_path: Path, fakes: FakeAuditor) -> None:
    ws = tmp_path / "custom"
    result = runner.invoke(app, ["audit", str(audio), "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert len(list(ws.glob("sessions/*/report.md"))) == 1
