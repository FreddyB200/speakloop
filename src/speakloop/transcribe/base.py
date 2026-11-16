"""Interface every speech-to-text backend implements."""

from pathlib import Path
from typing import Protocol

from speakloop.models import TrackId, Transcript


class TranscriptionError(Exception):
    """Raised when a backend fails to transcribe audio."""


class TranscriptionBackend(Protocol):
    name: str

    def transcribe(
        self,
        audio: Path,
        *,
        track: TrackId,
        session_id: str,
        language: str | None = None,
        prompt: str | None = None,
        word_timestamps: bool = True,
    ) -> Transcript: ...
