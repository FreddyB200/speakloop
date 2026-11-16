"""Security, upload limits, static frontend and `serve` wiring."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from speakloop import cli
from speakloop.server import app as server_app
from speakloop.server.app import create_app
from speakloop.transcribe import FakeBackend
from speakloop.workspace import Workspace
from tests.test_pipeline import SPEAKER_TEXT, FakeAuditor, canned, words

runner = CliRunner()


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "make_transcriber", lambda size: FakeBackend(words(SPEAKER_TEXT)))
    monkeypatch.setattr(cli, "make_auditor", lambda: FakeAuditor(canned()))
    monkeypatch.delenv("SPEAKLOOP_ALLOWED_ORIGINS", raising=False)


def make(tmp_path: Path, **kwargs: object) -> TestClient:
    app = create_app(Workspace(tmp_path / "ws"), static_dir=tmp_path / "dist", **kwargs)  # type: ignore[arg-type]
    return TestClient(app, base_url="http://localhost:8765")


def test_host_header(tmp_path: Path) -> None:
    c = make(tmp_path)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/health", headers={"Host": "127.0.0.1:8765"}).status_code == 200
    assert c.get("/api/health", headers={"Host": "[::1]:8765"}).status_code == 200
    assert c.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 403
    assert c.get("/api/health", headers={"Host": "evil.example.com:80"}).status_code == 403
    assert c.get("/", headers={"Host": "evil.example.com"}).status_code == 403


def test_origin_on_writes(tmp_path: Path) -> None:
    c = make(tmp_path)
    body = {"obsidian_dir": None, "glossary": [], "model_size": "small.en", "language": "en"}
    assert (
        c.put("/api/settings", json=body, headers={"Origin": "http://evil.com"}).status_code == 403
    )
    assert c.put("/api/settings", json=body, headers={"Origin": "null"}).status_code == 403
    ok = c.put("/api/settings", json=body, headers={"Origin": "http://localhost:8765"})
    assert ok.status_code == 200
    assert c.put("/api/settings", json=body).status_code == 200
    # Reads are not restricted by Origin.
    assert c.get("/api/health", headers={"Origin": "http://evil.com"}).status_code == 200


def test_extra_origin_allowed(tmp_path: Path) -> None:
    c = make(tmp_path, extra_origins=["http://localhost:5173"])
    body = {"obsidian_dir": None, "glossary": [], "model_size": "small.en", "language": "en"}
    resp = c.put("/api/settings", json=body, headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200


def test_no_cors_headers(tmp_path: Path) -> None:
    resp = make(tmp_path).get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in resp.headers


def test_upload_content_type(tmp_path: Path) -> None:
    c = make(tmp_path)
    resp = c.post("/api/sessions", files={"mic": ("a.txt", b"hello", "text/plain")})
    assert resp.status_code == 415
    resp = c.post(
        "/api/sessions",
        files={"mic": ("a.wav", b"x", "audio/wav"), "system": ("b.txt", b"y", "text/plain")},
    )
    assert resp.status_code == 415


def test_upload_missing_empty_and_bad_fields(tmp_path: Path) -> None:
    c = make(tmp_path)
    assert c.post("/api/sessions").status_code == 422
    assert c.post("/api/sessions", files={"mic": ("a.wav", b"", "audio/wav")}).status_code == 400
    audio = {"mic": ("a.wav", b"x", "audio/wav")}
    assert c.post("/api/sessions", files=audio, data={"kind": "nope"}).status_code == 422
    assert c.post("/api/sessions", files=audio, data={"scenario_id": "../x"}).status_code == 422


def test_upload_size_limit(tmp_path: Path) -> None:
    c = make(tmp_path, max_upload_bytes=100)
    resp = c.post("/api/sessions", files={"mic": ("a.wav", b"x" * 101, "audio/wav")})
    assert resp.status_code == 413
    assert (
        c.post("/api/sessions", files={"mic": ("a.wav", b"x" * 100, "audio/wav")}).status_code
        == 202
    )
    huge = c.post(
        "/api/sessions",
        files={"mic": ("a.wav", b"x", "audio/wav")},
        headers={"Content-Length": str(10_000_000)},
    )
    assert huge.status_code == 413


def test_no_frontend_page(tmp_path: Path) -> None:
    resp = make(tmp_path).get("/")
    assert resp.status_code == 200
    assert "npm run build" in resp.text


def test_static_and_spa_fallback(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    c = make(tmp_path)
    assert c.get("/").text == "<html>app</html>"
    assert c.get("/sessions/abc").text == "<html>app</html>"
    assert "console.log" in c.get("/assets/app.js").text
    assert c.get("/..%2fsecret.txt").text == "<html>app</html>"
    assert c.get("/api/unknown").status_code == 404
    assert c.get("/api/health").status_code == 200


def test_serve_wiring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(server_app.uvicorn, "run", lambda app, **kw: calls.append(kw))
    opened: list[str] = []

    class FakeTimer:
        def __init__(self, delay: float, fn: object, args: tuple[str, ...]) -> None:
            self.args = args
            self.daemon = False

        def start(self) -> None:
            opened.extend(self.args)

    monkeypatch.setattr(server_app.threading, "Timer", FakeTimer)
    ws = tmp_path / "ws"
    result = runner.invoke(cli.app, ["serve", "--port", "9999", "--workspace", str(ws)])
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "127.0.0.1", "port": 9999, "log_level": "info"}]
    assert opened == ["http://127.0.0.1:9999/"]

    opened.clear()
    result = runner.invoke(cli.app, ["serve", "--no-open", "--workspace", str(ws)])
    assert result.exit_code == 0
    assert opened == []
    assert calls[-1]["port"] == 8791


def test_default_port_matches_cli() -> None:
    from speakloop import cli
    from speakloop.server import app as server_app

    assert cli.DEFAULT_PORT == server_app.DEFAULT_PORT


def test_find_free_port_skips_a_busy_port() -> None:
    import socket

    from speakloop.server.app import find_free_port

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        assert find_free_port("127.0.0.1", taken) != taken
