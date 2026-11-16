"""ClaudeCodeBackend tests against a fake `claude` executable (no real model call)."""

import json
import shutil
import stat
import sys
from pathlib import Path

import pytest

from speakloop.audit.base import AuditBackendError
from speakloop.audit.claude_code import ClaudeCodeBackend, extract_json_text, schema_errors
from speakloop.audit.schema import audit_json_schema

FIXTURES = Path(__file__).parent / "fixtures" / "audit"


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake `claude` first on PATH and return its control directory."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "claude"
    body = (FIXTURES / "fake_claude.py").read_text()
    script.write_text(f"#!{sys.executable}\n{body}")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(control))
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.delenv("SPEAKLOOP_CLAUDE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    return control


def respond(control: Path, *names: str) -> None:
    for i, name in enumerate(names, start=1):
        shutil.copy(FIXTURES / name, control / f"response_{i}")


def calls(control: Path) -> list[dict[str, object]]:
    found = sorted(control.glob("call_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    return [json.loads(p.read_text()) for p in found]


def test_valid_structured_answer(fake: Path) -> None:
    respond(fake, "envelope_structured.json")
    out = ClaudeCodeBackend().complete_json("PROMPT TEXT", json_schema=audit_json_schema())
    assert out["summary"] == "ok"
    (call,) = calls(fake)
    assert call["stdin"] == "PROMPT TEXT"


def test_valid_answer_from_text_result_with_fence(fake: Path) -> None:
    respond(fake, "envelope_text.json")
    out = ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())
    assert out["next_session_goal"] == "ask more"


def test_retry_once_after_invalid_json(fake: Path) -> None:
    respond(fake, "envelope_garbage.json", "envelope_structured.json")
    out = ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())
    assert out["summary"] == "ok"
    first, second = calls(fake)
    assert "rejected" in str(second["stdin"])
    assert str(first["stdin"]) == "p"


def test_retry_on_schema_violation_then_success(fake: Path) -> None:
    respond(fake, "envelope_schema_violation.json", "envelope_structured.json")
    ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())
    assert "maximum" in str(calls(fake)[1]["stdin"])


def test_invalid_twice_raises(fake: Path) -> None:
    respond(fake, "envelope_garbage.json")
    with pytest.raises(AuditBackendError, match="twice"):
        ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())
    assert len(calls(fake)) == 2


def test_error_envelope_raises_without_retry(fake: Path) -> None:
    respond(fake, "envelope_error.json")
    with pytest.raises(AuditBackendError, match="login required"):
        ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())
    assert len(calls(fake)) == 1


def test_timeout(fake: Path) -> None:
    respond(fake, "envelope_structured.json")
    (fake / "sleep").write_text("1")
    with pytest.raises(AuditBackendError, match="timed out"):
        ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema(), timeout_s=1.0)


def test_tools_disabled_flags_and_no_shell(fake: Path) -> None:
    respond(fake, "envelope_structured.json")
    ClaudeCodeBackend(model="sonnet").complete_json("p", json_schema=audit_json_schema())
    argv = calls(fake)[0]["argv"]
    assert isinstance(argv, list)
    assert "-p" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--model") + 1] == "sonnet"
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == json.loads(json.dumps(audit_json_schema()))
    # The prompt is never an argv element (it goes through stdin).
    assert "p" not in argv


def test_runs_in_empty_temp_dir_without_api_keys(fake: Path) -> None:
    respond(fake, "envelope_structured.json")
    ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())
    call = calls(fake)[0]
    assert "speakloop-audit-" in str(call["cwd"])
    assert "ANTHROPIC_API_KEY" not in call["env_keys"]  # type: ignore[operator]
    assert not Path(str(call["cwd"])).exists()


def test_env_override_executable(
    fake: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    respond(fake, "envelope_structured.json")
    other = tmp_path / "bin" / "myclaude"
    shutil.copy(tmp_path / "bin" / "claude", other)
    monkeypatch.setenv("SPEAKLOOP_CLAUDE", str(other))
    monkeypatch.setenv("PATH", "/nonexistent")
    ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())
    assert len(calls(fake)) == 1


def test_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.delenv("SPEAKLOOP_CLAUDE", raising=False)
    with pytest.raises(AuditBackendError, match="not found"):
        ClaudeCodeBackend().complete_json("p", json_schema=audit_json_schema())


def test_extract_json_text_with_prose() -> None:
    assert extract_json_text('Here: {"a": 1} done') == {"a": 1}
    with pytest.raises(json.JSONDecodeError):
        extract_json_text("no json")


def test_schema_errors_reports_problems() -> None:
    schema = audit_json_schema()
    assert schema_errors({}, schema)  # missing required fields
    assert schema_errors([], schema)  # wrong type
