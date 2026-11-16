"""Pluggable speech-to-text backends."""

from speakloop.transcribe.base import TranscriptionBackend, TranscriptionError
from speakloop.transcribe.buzz import BuzzBackend, resolve_executable
from speakloop.transcribe.fake import FakeBackend
from speakloop.transcribe.segmenting import build_segments
from speakloop.transcribe.srt import Cue, SubtitleParseError, parse_srt, parse_subtitles, parse_vtt

__all__ = [
    "BuzzBackend",
    "Cue",
    "FakeBackend",
    "SubtitleParseError",
    "TranscriptionBackend",
    "TranscriptionError",
    "build_segments",
    "parse_srt",
    "parse_subtitles",
    "parse_vtt",
    "resolve_executable",
]
