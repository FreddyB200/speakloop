"""Deterministic backend for tests and development."""

from collections.abc import Sequence
from pathlib import Path

from speakloop.models import TrackId, Transcript, Word
from speakloop.transcribe.segmenting import build_segments


class FakeBackend:
    """Returns a transcript built from a fixed list of `(text, start, end)` words."""

    name = "fake"

    def __init__(
        self,
        words: Sequence[tuple[str, float, float]],
        *,
        model: str = "fake",
        language: str | None = "en",
    ) -> None:
        self._words = tuple(words)
        self._model = model
        self._language = language
        self.calls: list[Path] = []

    def transcribe(
        self,
        audio: Path,
        *,
        track: TrackId,
        session_id: str,
        language: str | None = None,
        prompt: str | None = None,
        word_timestamps: bool = True,
    ) -> Transcript:
        self.calls.append(audio)
        words = [
            Word(text=t, start=s, end=e, probability=None, track=track) for t, s, e in self._words
        ]
        segments = build_segments(words, track=track)
        if not word_timestamps:
            segments = tuple(seg.model_copy(update={"words": ()}) for seg in segments)
        return Transcript(
            session_id=session_id,
            language=language if language is not None else self._language,
            backend=self.name,
            model=self._model,
            prompt=prompt,
            segments=segments,
        )
