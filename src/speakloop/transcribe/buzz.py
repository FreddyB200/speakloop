"""Transcription through the local Buzz CLI (no network, no paid APIs)."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from speakloop.models import Segment, TrackId, Transcript, Word
from speakloop.transcribe.base import TranscriptionError
from speakloop.transcribe.segmenting import build_segments
from speakloop.transcribe.srt import Cue, SubtitleParseError, parse_srt

_ENV_VAR = "SPEAKLOOP_BUZZ"
_DEFAULT_VENV_PATH = Path("~/.venvs/buzz/bin/buzz")
_STDERR_TAIL_LINES = 8
_STDERR_TAIL_CHARS = 1200


def resolve_executable(explicit: Path | None = None) -> Path:
    """Find Buzz: explicit arg, env SPEAKLOOP_BUZZ, ~/.venvs/buzz/bin/buzz, then PATH."""
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser())
    elif env := os.environ.get(_ENV_VAR):
        candidates.append(Path(env).expanduser())
    if explicit is None:
        candidates.append(_DEFAULT_VENV_PATH.expanduser())
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    if explicit is None and (found := shutil.which("buzz")):
        return Path(found)
    tried = ", ".join(str(c) for c in candidates) or "none"
    raise TranscriptionError(
        f"Buzz executable not found (tried: {tried}, then PATH). "
        f"Install Buzz or set {_ENV_VAR} to its path."
    )


def _tail(text: str) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(lines[-_STDERR_TAIL_LINES:])[-_STDERR_TAIL_CHARS:]


def _is_single_token(cue: Cue) -> bool:
    return len(cue.text.split()) == 1


class BuzzBackend:
    """Runs `buzz add` on one audio file and normalizes the SRT into a `Transcript`."""

    name = "buzz"

    def __init__(
        self,
        executable: Path | None = None,
        model_type: str = "fasterwhisper",
        model_size: str = "small.en",
        timeout_s: float = 1800.0,
    ) -> None:
        if model_type == "openaiapi":
            raise TranscriptionError("The OpenAI API model type is not allowed (no paid APIs)")
        self._explicit = executable
        self.model_type = model_type
        self.model_size = model_size
        self.timeout_s = timeout_s

    @property
    def model(self) -> str:
        return f"{self.model_type}:{self.model_size}"

    def _argv(
        self,
        exe: Path,
        audio: Path,
        out_dir: Path,
        language: str | None,
        prompt: str | None,
        word_timestamps: bool,
    ) -> list[str]:
        argv = [
            str(exe),
            "add",
            "-t",
            "transcribe",
            "-m",
            self.model_type,
            "-s",
            self.model_size,
        ]
        if language:
            argv += ["-l", language]
        if prompt:
            argv += ["-p", prompt]
        if word_timestamps:
            argv.append("-w")
        argv += ["-d", str(out_dir), "--srt", "--hide-gui", str(audio)]
        return argv

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
        audio = audio.expanduser().resolve()
        if not audio.is_file():
            raise TranscriptionError(f"Audio file not found: {audio}")
        exe = resolve_executable(self._explicit)
        # BUZZ_DISABLE_TELEMETRY: Buzz otherwise sends an "app_launched" event with a user
        # identifier to PostHog on every start (buzz/widgets/application.py). SpeakLoop is
        # local-first, so it is always disabled.
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "BUZZ_DISABLE_TELEMETRY": "1"}
        with tempfile.TemporaryDirectory(prefix="speakloop-buzz-") as tmp:
            out_dir = Path(tmp)
            argv = self._argv(exe, audio, out_dir, language, prompt, word_timestamps)
            try:
                proc = subprocess.run(  # argv list, never a shell
                    argv,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=self.timeout_s,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise TranscriptionError(f"Buzz timed out after {self.timeout_s:g}s") from exc
            except OSError as exc:
                raise TranscriptionError(f"Could not run Buzz at {exe}: {exc}") from exc
            # Buzz exits 0 even when the transcription fails, so the output file is the
            # real success signal.
            srt_files = sorted(out_dir.glob("*.srt"))
            if proc.returncode != 0 or not srt_files:
                reason = f"exit code {proc.returncode}" if proc.returncode != 0 else "no SRT output"
                raise TranscriptionError(
                    f"Buzz failed ({reason}): {_tail(proc.stderr or proc.stdout or '')}"
                )
            try:
                cues = parse_srt(srt_files[0].read_text(encoding="utf-8-sig"))
            except (SubtitleParseError, UnicodeDecodeError, OSError) as exc:
                raise TranscriptionError(f"Could not parse Buzz output: {exc}") from exc
        return Transcript(
            session_id=session_id,
            language=language,
            backend=self.name,
            model=self.model,
            prompt=prompt,
            segments=self._segments(cues, track, word_timestamps),
        )

    @staticmethod
    def _segments(cues: list[Cue], track: TrackId, word_timestamps: bool) -> tuple[Segment, ...]:
        if word_timestamps and cues and all(_is_single_token(c) for c in cues):
            words = [
                Word(text=c.text, start=c.start, end=c.end, probability=None, track=track)
                for c in cues
            ]
            return build_segments(words, track=track)
        # Segment-level cues (or cues that are not single words): keep them without words.
        return tuple(Segment(start=c.start, end=c.end, text=c.text, track=track) for c in cues)
