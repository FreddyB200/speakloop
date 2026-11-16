"""In-process job queue: one background worker runs the pipeline for one upload at a time."""

import logging
import queue
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from speakloop.models import SessionKind
from speakloop.server.schemas import JobOut, JobStatus

_log = logging.getLogger(__name__)


@dataclass
class JobState:
    job_id: str
    status: JobStatus = "queued"
    session_id: str | None = None
    error: str | None = None
    audit_error: str | None = None

    def to_out(self) -> JobOut:
        return JobOut(
            job_id=self.job_id,
            status=self.status,
            session_id=self.session_id,
            error=self.error,
            audit_error=self.audit_error,
        )


@dataclass(frozen=True)
class JobRequest:
    job_id: str
    upload_dir: Path
    mic: Path
    system: Path | None
    kind: SessionKind
    scenario_id: str | None
    audit: bool


# A runner executes one job, reporting progress through `set_status`, and returns
# `(session_id, audit_error)`. It raises on failure; the message becomes the job error.
Runner = Callable[[JobRequest, Callable[[JobStatus], None]], tuple[str, str | None]]


class JobManager:
    def __init__(self, runner: Runner) -> None:
        self._runner = runner
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()
        self._queue: queue.Queue[JobRequest] = queue.Queue()
        self._worker: threading.Thread | None = None

    def new_job_id(self) -> str:
        return uuid.uuid4().hex

    def submit(self, request: JobRequest) -> None:
        with self._lock:
            self._jobs[request.job_id] = JobState(request.job_id)
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._work, name="speakloop-jobs", daemon=True
                )
                self._worker.start()
        self._queue.put(request)

    def get(self, job_id: str) -> JobOut | None:
        with self._lock:
            state = self._jobs.get(job_id)
            return state.to_out() if state else None

    def _update(self, job_id: str, **changes: object) -> None:
        with self._lock:
            state = self._jobs[job_id]
            for key, value in changes.items():
                setattr(state, key, value)

    def _work(self) -> None:
        while True:
            request = self._queue.get()
            try:
                self._run(request)
            finally:
                shutil.rmtree(request.upload_dir, ignore_errors=True)
                self._queue.task_done()

    def _run(self, request: JobRequest) -> None:
        job_id = request.job_id
        try:
            session_id, audit_error = self._runner(
                request, lambda status: self._update(job_id, status=status)
            )
        except Exception as exc:
            _log.exception("job %s failed", job_id)
            self._update(job_id, status="error", error=str(exc) or type(exc).__name__)
        else:
            self._update(job_id, status="done", session_id=session_id, audit_error=audit_error)

    def wait_idle(self) -> None:
        """Block until every submitted job has finished (used by tests)."""
        self._queue.join()
