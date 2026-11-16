"""FastAPI application: JSON API under `/api` plus the built frontend (`web/dist`)."""

import mimetypes
import os
import re
import shutil
import socket
import tempfile
import threading
import webbrowser
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Annotated, cast

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from speakloop import __version__, cli
from speakloop.audit.rubric import load_rubric
from speakloop.export.obsidian import export_to_folder
from speakloop.export.report import render_report
from speakloop.models import Session, SessionKind, TrackId, is_valid_session_id
from speakloop.pipeline import DEFAULT_TRANSCRIPTION_PROMPT, run_session
from speakloop.server.jobs import JobManager, JobRequest
from speakloop.server.schemas import (
    DoctorCheckOut,
    DoctorOut,
    ExportOut,
    Health,
    JobCreated,
    JobOut,
    JobStatus,
    SessionDetail,
    SessionSummary,
    SettingsBody,
)
from speakloop.server.security import install_security
from speakloop.server.settings import load_settings, save_settings
from speakloop.workspace import Workspace

DEFAULT_MAX_UPLOAD_BYTES = 500 * 1024 * 1024
DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"
EXTRA_ORIGINS_ENV = "SPEAKLOOP_ALLOWED_ORIGINS"
_CHUNK = 1024 * 1024
_SCENARIO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,8}$")
_AUDIO_TYPES = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".aac": "audio/aac",
}
_NO_FRONTEND_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>SpeakLoop</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto;">
<h1>SpeakLoop API is running</h1>
<p>The web interface has not been built yet. From the repository root run:</p>
<pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>Then restart <code>speakloop serve</code>. The API is available under
<a href="/api/docs">/api/docs</a>.</p>
</body></html>
"""


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def _stored_audio(workspace: Workspace, session: Session, track: TrackId) -> Path | None:
    """Path of a stored audio file, or None. Only files inside the session folder count."""
    for item in session.tracks:
        if item.id != track or item.audio_path is None or item.audio_path.is_absolute():
            continue
        base = workspace.session_dir(session.id).resolve()
        path = (base / item.audio_path).resolve()
        if path.is_relative_to(base) and path.is_file():
            return path
    return None


def _content_type_of(path: Path) -> str:
    return (
        _AUDIO_TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or ("application/octet-stream")
    )


def _upload_suffix(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if _EXT_RE.match(suffix):
        return suffix
    guessed = mimetypes.guess_extension((upload.content_type or "").split(";")[0].strip())
    return guessed if guessed and _EXT_RE.match(guessed) else ".bin"


def _save_upload(upload: UploadFile, target: Path, limit: int) -> None:
    total = 0
    with target.open("wb") as out:
        while chunk := upload.file.read(_CHUNK):
            total += len(chunk)
            if total > limit:
                raise HTTPException(status_code=413, detail="upload too large")
            out.write(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="empty upload")


def _check_media_type(upload: UploadFile, field: str) -> None:
    media = (upload.content_type or "").split(";")[0].strip().lower()
    if not (media.startswith("audio/") or media.startswith("video/")):
        raise HTTPException(status_code=415, detail=f"{field} must be an audio or video file")


def create_app(
    workspace: Workspace,
    *,
    static_dir: Path | None = None,
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    extra_origins: Iterable[str] | None = None,
) -> FastAPI:
    """Build the app for one workspace (backends come from the `speakloop.cli` factories)."""
    app = FastAPI(
        title="SpeakLoop",
        version=__version__,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    origins = (
        list(extra_origins)
        if extra_origins is not None
        else [o for o in os.environ.get(EXTRA_ORIGINS_ENV, "").split(",") if o.strip()]
    )
    install_security(app, extra_origins=origins)
    dist = static_dir if static_dir is not None else DEFAULT_STATIC_DIR

    def runner(
        request: JobRequest, set_status: Callable[[JobStatus], None]
    ) -> tuple[str, str | None]:
        settings = load_settings(workspace)
        rubric = load_rubric()
        result = run_session(
            request.mic,
            audio_system=request.system,
            kind=request.kind,
            scenario_id=request.scenario_id,
            workspace=workspace,
            transcriber=cli.make_transcriber(settings.model_size),
            auditor=cli.make_auditor() if request.audit else None,
            rubric=rubric,
            language=settings.language,
            prompt=DEFAULT_TRANSCRIPTION_PROMPT,
            glossary=settings.glossary,
            on_step=lambda name: set_status(cast(JobStatus, name)),
            keep_audio=True,
        )
        return result.session.id, result.audit_error

    jobs = JobManager(runner)
    app.state.jobs = jobs
    app.state.workspace = workspace

    def require_session(session_id: str) -> Session:
        if not is_valid_session_id(session_id) or not workspace.has_session(session_id):
            raise _not_found("session")
        try:
            return workspace.load_session(session_id)
        except (OSError, ValueError) as exc:
            raise _not_found("session") from exc

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health(ok=True, version=__version__)

    @app.get("/api/doctor", response_model=DoctorOut)
    def doctor() -> DoctorOut:
        return DoctorOut(
            checks=[
                DoctorCheckOut(name=c.name, ok=c.ok, detail=c.detail)
                for c in cli.doctor_checks(workspace)
            ]
        )

    @app.get("/api/sessions", response_model=list[SessionSummary])
    def list_sessions() -> list[SessionSummary]:
        out: list[SessionSummary] = []
        for session in reversed(workspace.list_sessions()):
            try:
                metrics = workspace.load_metrics(session.id)
            except (OSError, ValueError):
                continue
            try:
                findings_count = len(workspace.load_findings(session.id))
            except (OSError, ValueError):
                findings_count = 0
            try:
                audit = workspace.load_audit(session.id)
            except (OSError, ValueError):
                audit = None
            out.append(
                SessionSummary(
                    id=session.id,
                    created_at=session.created_at,
                    kind=session.kind,
                    scenario_id=session.scenario_id,
                    duration_s=metrics.duration_s,
                    wpm_mean=metrics.wpm_mean,
                    fillers_per_100w=metrics.fillers_per_100w,
                    findings_count=findings_count,
                    has_audio=any(
                        _stored_audio(workspace, session, t.id) is not None for t in session.tracks
                    ),
                    audit_error=audit.error if audit else None,
                )
            )
        return out

    @app.get("/api/sessions/{session_id}", response_model=SessionDetail)
    def get_session(session_id: str) -> SessionDetail:
        session = require_session(session_id)

        def optional[T](load: Callable[[str], T]) -> T | None:
            try:
                return load(session_id)
            except (OSError, ValueError):
                return None

        return SessionDetail(
            session=session,
            metrics=optional(workspace.load_metrics),
            findings=optional(workspace.load_findings) or [],
            audit=optional(workspace.load_audit),
            transcript=optional(workspace.load_transcript),
            audio_tracks=[
                t.id for t in session.tracks if _stored_audio(workspace, session, t.id) is not None
            ],
        )

    @app.get("/api/sessions/{session_id}/report.md")
    def get_report(session_id: str) -> Response:
        require_session(session_id)
        try:
            text = workspace.report_path(session_id).read_text(encoding="utf-8")
        except OSError as exc:
            raise _not_found("report") from exc
        return Response(text, media_type="text/markdown; charset=utf-8")

    @app.get("/api/sessions/{session_id}/audio/{track}")
    def get_audio(session_id: str, track: str) -> FileResponse:
        session = require_session(session_id)
        if track not in ("mic", "system"):
            raise _not_found("audio track")
        path = _stored_audio(workspace, session, cast(TrackId, track))
        if path is None:
            raise _not_found("audio")
        return FileResponse(path, media_type=_content_type_of(path))

    @app.post("/api/sessions", status_code=202, response_model=JobCreated)
    def create_session(
        request: Request,
        mic: Annotated[UploadFile, File()],
        system: Annotated[UploadFile | None, File()] = None,
        kind: Annotated[SessionKind, Form()] = SessionKind.FREE,
        scenario_id: Annotated[str | None, Form()] = None,
        audit: Annotated[bool, Form()] = True,
    ) -> JobCreated:
        if scenario_id is not None and not _SCENARIO_RE.match(scenario_id):
            raise HTTPException(status_code=422, detail="invalid scenario_id")
        if system is not None and not system.filename:
            system = None
        _check_media_type(mic, "mic")
        if system is not None:
            _check_media_type(system, "system")
        upload_dir = Path(tempfile.mkdtemp(prefix="speakloop-upload-"))
        try:
            mic_path = upload_dir / f"mic{_upload_suffix(mic)}"
            _save_upload(mic, mic_path, max_upload_bytes)
            system_path: Path | None = None
            if system is not None:
                system_path = upload_dir / f"system{_upload_suffix(system)}"
                _save_upload(system, system_path, max_upload_bytes)
            job_id = jobs.new_job_id()
            jobs.submit(
                JobRequest(
                    job_id=job_id,
                    upload_dir=upload_dir,
                    mic=mic_path,
                    system=system_path,
                    kind=kind,
                    scenario_id=scenario_id,
                    audit=audit,
                )
            )
        except BaseException:
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise
        return JobCreated(job_id=job_id)

    @app.middleware("http")
    async def limit_upload(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "POST" and request.url.path == "/api/sessions":
            length = request.headers.get("content-length")
            if (
                length is not None
                and length.isdigit()
                and int(length) > 2 * max_upload_bytes + (1 << 20)
            ):
                return JSONResponse({"detail": "upload too large"}, status_code=413)
        return await call_next(request)

    @app.get("/api/jobs/{job_id}", response_model=JobOut)
    def get_job(job_id: str) -> JobOut:
        job = jobs.get(job_id)
        if job is None:
            raise _not_found("job")
        return job

    @app.post("/api/sessions/{session_id}/export", response_model=ExportOut)
    def export_session(session_id: str) -> ExportOut:
        session = require_session(session_id)
        folder = load_settings(workspace).obsidian_dir or os.environ.get(cli.OBSIDIAN_ENV_VAR)
        if not folder:
            raise HTTPException(status_code=400, detail="no Obsidian folder configured")
        try:
            text = render_report(
                session,
                workspace.load_metrics(session_id),
                workspace.load_findings(session_id),
                summary=(a.summary if (a := workspace.load_audit(session_id)) else None),
                next_session_goal=(a.next_session_goal if a else None),
                transcript=workspace.load_transcript(session_id),
            )
            workspace.save_report(session_id, text)
            path = export_to_folder(text, session, Path(folder), replace=True)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"export failed: {exc}") from exc
        return ExportOut(path=str(path))

    @app.get("/api/settings", response_model=SettingsBody)
    def get_settings() -> SettingsBody:
        return load_settings(workspace)

    @app.put("/api/settings", response_model=SettingsBody)
    def put_settings(body: SettingsBody) -> SettingsBody:
        try:
            save_settings(workspace, body)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"cannot save settings: {exc}") from exc
        return load_settings(workspace)

    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        include_in_schema=False,
    )
    def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse({"detail": "not found"}, status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse(_NO_FRONTEND_HTML)
        base = dist.resolve()
        candidate = (base / path).resolve()
        if path and candidate.is_relative_to(base) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index, media_type="text/html")

    return app


DEFAULT_PORT = 8791


def find_free_port(host: str, start: int, attempts: int = 20) -> int:
    """Return `start` if it is free on `host`, else the next free port within `attempts` tries."""
    for candidate in range(start, start + attempts):
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as probe:
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return candidate
    raise OSError(f"no free port between {start} and {start + attempts - 1} on {host}")


def run_server(app: FastAPI, *, host: str, port: int, open_browser: bool) -> None:
    """Serve the app with uvicorn, opening the browser shortly after start.

    If `port` is taken by another program, the next free port is used instead.
    """
    free = find_free_port(host, port)
    if free != port:
        print(f"Port {port} is in use; using {free} instead.")
    port = free
    print(f"SpeakLoop is running at http://{host}:{port}/ (Ctrl+C to stop)")
    if open_browser:
        shown = "localhost" if host in ("0.0.0.0", "::") else host
        timer = threading.Timer(1.0, webbrowser.open, args=(f"http://{shown}:{port}/",))
        timer.daemon = True
        timer.start()
    uvicorn.run(app, host=host, port=port, log_level="info")
