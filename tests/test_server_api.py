"""HTTP API tests with FastAPI's TestClient (fake backends, synthetic data)."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from speakloop import cli
from speakloop.server.app import create_app
from speakloop.server.jobs import JobManager
from speakloop.transcribe import FakeBackend
from speakloop.workspace import Workspace
from tests.test_pipeline import SPEAKER_TEXT, FakeAuditor, canned, words

AUDIO = b"RIFF-not-real-audio-" * 50


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "ws")


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> FakeAuditor:
    auditor = FakeAuditor(canned())
    monkeypatch.setattr(cli, "make_transcriber", lambda size: FakeBackend(words(SPEAKER_TEXT)))
    monkeypatch.setattr(cli, "make_auditor", lambda: auditor)
    monkeypatch.delenv("SPEAKLOOP_OBSIDIAN_DIR", raising=False)
    monkeypatch.delenv("SPEAKLOOP_ALLOWED_ORIGINS", raising=False)
    return auditor


@pytest.fixture
def client(workspace: Workspace, tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(workspace, static_dir=tmp_path / "no-dist")
    with TestClient(app, base_url="http://localhost:8765") as c:
        yield c


def upload(client: TestClient, **extra: object) -> str:
    data = {"kind": "discovery", **{k: str(v) for k, v in extra.items()}}
    resp = client.post("/api/sessions", files={"mic": ("talk.m4a", AUDIO, "audio/mp4")}, data=data)
    assert resp.status_code == 202, resp.text
    return str(resp.json()["job_id"])


def wait_job(client: TestClient, job_id: str) -> dict[str, object]:
    manager: JobManager = client.app.state.jobs  # type: ignore[attr-defined]
    manager.wait_idle()
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return dict(job)
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def make_session(client: TestClient, **extra: object) -> str:
    job = wait_job(client, upload(client, **extra))
    assert job["status"] == "done", job
    return str(job["session_id"])


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["version"]


def test_openapi(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    assert "/api/sessions/{session_id}" in spec["paths"]


def test_doctor(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("speakloop.cli.shutil.which", lambda _n: None)
    checks = {c["name"]: c for c in client.get("/api/doctor").json()["checks"]}
    assert set(checks) == {"claude", "buzz", "workspace"}
    assert checks["claude"]["ok"] is False
    assert checks["workspace"]["ok"] is True


def test_empty_list(client: TestClient) -> None:
    assert client.get("/api/sessions").json() == []


def test_job_lifecycle_and_detail(client: TestClient, workspace: Workspace) -> None:
    job_id = upload(client, scenario_id="demo-1")
    job = wait_job(client, job_id)
    assert job["status"] == "done"
    assert job["error"] is None
    sid = str(job["session_id"])

    listing = client.get("/api/sessions").json()
    assert [s["id"] for s in listing] == [sid]
    row = listing[0]
    assert row["kind"] == "discovery"
    assert row["scenario_id"] == "demo-1"
    assert row["has_audio"] is True
    assert row["findings_count"] == 1
    assert row["audit_error"] is None

    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["session"]["id"] == sid
    assert detail["metrics"]["session_id"] == sid
    assert len(detail["findings"]) == 1
    assert detail["audit"]["summary"] == "Good session."
    assert detail["transcript"]["segments"]
    assert detail["audio_tracks"] == ["mic"]
    assert detail["session"]["tracks"][0]["audio_path"] == "audio/mic.m4a"
    assert (workspace.session_dir(sid) / "audio" / "mic.m4a").read_bytes() == AUDIO

    report = client.get(f"/api/sessions/{sid}/report.md")
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/markdown")
    assert "Good session." in report.text


def test_newest_first_and_no_audit(client: TestClient, fakes: FakeAuditor) -> None:
    first = make_session(client, audit="false")
    assert fakes.prompts == []
    time.sleep(1.1)
    second = make_session(client)
    ids = [s["id"] for s in client.get("/api/sessions").json()]
    assert ids == [second, first]


def test_audit_error_reported(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "make_auditor", lambda: FakeAuditor(fail=True))
    job = wait_job(client, upload(client))
    assert job["status"] == "done"
    assert "audit failed" in str(job["audit_error"])
    sid = str(job["session_id"])
    assert "audit failed" in client.get("/api/sessions").json()[0]["audit_error"]
    assert client.get(f"/api/sessions/{sid}").json()["audit"]["error"]


def test_job_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(size: str) -> FakeBackend:
        raise RuntimeError("no buzz")

    monkeypatch.setattr(cli, "make_transcriber", boom)
    job = wait_job(client, upload(client))
    assert job["status"] == "error"
    assert "no buzz" in str(job["error"])
    assert job["session_id"] is None


def test_two_tracks(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions",
        files={
            "mic": ("a.wav", AUDIO, "audio/wav"),
            "system": ("b.mp3", AUDIO, "audio/mpeg"),
        },
    )
    job = wait_job(client, resp.json()["job_id"])
    sid = str(job["session_id"])
    assert client.get(f"/api/sessions/{sid}").json()["audio_tracks"] == ["mic", "system"]
    assert client.get(f"/api/sessions/{sid}/audio/system").headers["content-type"] == "audio/mpeg"


def test_not_found(client: TestClient) -> None:
    sid = make_session(client)
    for path in (
        "/api/sessions/nope",
        "/api/sessions/20200101-000000-abcd",
        "/api/sessions/20200101-000000-abcd/report.md",
        "/api/sessions/20200101-000000-abcd/audio/mic",
        f"/api/sessions/{sid}/audio/system",
        f"/api/sessions/{sid}/audio/other",
        "/api/jobs/unknown",
        "/api/nothing",
    ):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/sessions/nope/export").status_code == 404


def test_audio_range(client: TestClient) -> None:
    sid = make_session(client)
    full = client.get(f"/api/sessions/{sid}/audio/mic")
    assert full.status_code == 200
    assert full.headers["content-type"] == "audio/mp4"
    assert full.content == AUDIO
    part = client.get(f"/api/sessions/{sid}/audio/mic", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == AUDIO[10:20]
    assert part.headers["content-range"] == f"bytes 10-19/{len(AUDIO)}"


def test_audio_absolute_path_not_served(client: TestClient, workspace: Workspace) -> None:
    sid = make_session(client)
    session = workspace.load_session(sid)
    outside = workspace.root / "outside.wav"
    outside.write_bytes(b"x")
    track = session.tracks[0].model_copy(update={"audio_path": outside})
    workspace.save_session(session.model_copy(update={"tracks": (track,)}))
    assert client.get(f"/api/sessions/{sid}/audio/mic").status_code == 404
    traversal = session.tracks[0].model_copy(update={"audio_path": Path("../../outside.wav")})
    workspace.save_session(session.model_copy(update={"tracks": (traversal,)}))
    assert client.get(f"/api/sessions/{sid}/audio/mic").status_code == 404


def test_settings_round_trip(client: TestClient, workspace: Workspace, tmp_path: Path) -> None:
    assert client.get("/api/settings").json() == {
        "obsidian_dir": None,
        "glossary": [],
        "model_size": "small.en",
        "language": "en",
    }
    body = {
        "obsidian_dir": str(tmp_path / 'vault "x"'),
        "glossary": ["Kubernetes", " gRPC ", "Kubernetes"],
        "model_size": "medium.en",
        "language": "en",
    }
    resp = client.put("/api/settings", json=body)
    assert resp.status_code == 200
    expected = {**body, "glossary": ["Kubernetes", "gRPC"]}
    assert resp.json() == expected
    assert client.get("/api/settings").json() == expected
    assert workspace.load_glossary() == ["Kubernetes", "gRPC"]
    assert workspace.config_path.is_file()


@pytest.mark.parametrize(
    "patch",
    [
        {"obsidian_dir": "relative/dir"},
        {"glossary": ["a\nb"]},
        {"glossary": ["a # b"]},
        {"model_size": "../x"},
        {"language": "english!!"},
        {"unknown": 1},
    ],
)
def test_settings_validation(client: TestClient, patch: dict[str, object]) -> None:
    base = {"obsidian_dir": None, "glossary": [], "model_size": "small.en", "language": "en"}
    assert client.put("/api/settings", json={**base, **patch}).status_code == 422


def test_export(client: TestClient, tmp_path: Path) -> None:
    sid = make_session(client)
    assert client.post(f"/api/sessions/{sid}/export").status_code == 400
    vault = tmp_path / "vault"
    client.put(
        "/api/settings",
        json={
            "obsidian_dir": str(vault),
            "glossary": [],
            "model_size": "small.en",
            "language": "en",
        },
    )
    first = client.post(f"/api/sessions/{sid}/export")
    assert first.status_code == 200
    path = Path(first.json()["path"])
    assert path.is_file() and sid in path.name
    second = client.post(f"/api/sessions/{sid}/export")
    assert second.json()["path"] == str(path)
    assert len(list(vault.glob("*.md"))) == 1


def test_export_env_fallback(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = make_session(client)
    monkeypatch.setenv("SPEAKLOOP_OBSIDIAN_DIR", str(tmp_path / "envvault"))
    assert client.post(f"/api/sessions/{sid}/export").status_code == 200


def test_unreadable_config_falls_back(client: TestClient, workspace: Workspace) -> None:
    workspace.root.mkdir(parents=True, exist_ok=True)
    workspace.config_path.write_text("not = [valid", encoding="utf-8")
    assert client.get("/api/settings").json()["model_size"] == "small.en"
