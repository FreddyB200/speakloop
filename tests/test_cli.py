"""Tests for the SpeakLoop command-line interface."""

import pytest
from typer.testing import CliRunner

from speakloop import __version__
from speakloop.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_claude_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("speakloop.cli.shutil.which", lambda _name: "/usr/local/bin/claude")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "found at /usr/local/bin/claude" in result.output


def test_doctor_claude_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("speakloop.cli.shutil.which", lambda _name: None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "NOT FOUND" in result.output


def test_audit_stub() -> None:
    result = runner.invoke(app, ["audit"])
    assert result.exit_code == 2
    assert "not implemented yet (milestone M1)" in result.output
