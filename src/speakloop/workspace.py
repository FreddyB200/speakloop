"""Filesystem workspace: one folder per session holding JSON artifacts.

Layout under the root (default `~/SpeakLoop`, or `$SPEAKLOOP_HOME`):

    sessions/<session_id>/{session,transcript,metrics,findings}.json and report.md
"""

import contextlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from speakloop.models import Finding, Metrics, Session, Transcript, is_valid_session_id

_FINDINGS = TypeAdapter(tuple[Finding, ...])


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def default(cls) -> "Workspace":
        home = os.environ.get("SPEAKLOOP_HOME")
        return cls(Path(home) if home else Path.home() / "SpeakLoop")

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    def session_dir(self, session_id: str) -> Path:
        """Folder of a session. Rejects ids that are not in the canonical format."""
        if not is_valid_session_id(session_id):
            raise ValueError(f"invalid session id: {session_id!r}")
        return self.sessions_dir / session_id

    def report_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "report.md"

    def save_report(self, session_id: str, text: str) -> Path:
        return self._write(session_id, "report.md", text)

    def _write(self, session_id: str, name: str, text: str) -> Path:
        directory = self.session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise
        return target

    def _read(self, session_id: str, name: str) -> str:
        return (self.session_dir(session_id) / name).read_text(encoding="utf-8")

    def _save_model(self, session_id: str, name: str, model: BaseModel) -> Path:
        return self._write(session_id, name, model.model_dump_json(indent=2) + "\n")

    def save_session(self, session: Session) -> Path:
        return self._save_model(session.id, "session.json", session)

    def load_session(self, session_id: str) -> Session:
        return Session.model_validate_json(self._read(session_id, "session.json"))

    def list_sessions(self) -> list[Session]:
        if not self.sessions_dir.is_dir():
            return []
        ids = sorted(
            p.name
            for p in self.sessions_dir.iterdir()
            if is_valid_session_id(p.name) and (p / "session.json").is_file()
        )
        return [self.load_session(i) for i in ids]

    def save_transcript(self, transcript: Transcript) -> Path:
        return self._save_model(transcript.session_id, "transcript.json", transcript)

    def load_transcript(self, session_id: str) -> Transcript:
        return Transcript.model_validate_json(self._read(session_id, "transcript.json"))

    def save_metrics(self, metrics: Metrics) -> Path:
        return self._save_model(metrics.session_id, "metrics.json", metrics)

    def load_metrics(self, session_id: str) -> Metrics:
        return Metrics.model_validate_json(self._read(session_id, "metrics.json"))

    def save_findings(self, session_id: str, findings: list[Finding]) -> Path:
        payload = json.loads(_FINDINGS.dump_json(tuple(findings)))
        return self._write(session_id, "findings.json", json.dumps(payload, indent=2) + "\n")

    def load_findings(self, session_id: str) -> list[Finding]:
        return list(_FINDINGS.validate_json(self._read(session_id, "findings.json")))
