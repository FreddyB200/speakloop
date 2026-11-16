import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from speakloop.models import Transcript, Word
from speakloop.transcribe import (
    BuzzBackend,
    FakeBackend,
    TranscriptionBackend,
    TranscriptionError,
    build_segments,
    resolve_executable,
)
from speakloop.transcribe import buzz as buzz_mod

FIX = Path(__file__).parent / "fixtures" / "transcribe"
SID = "20260101-093000-a1b2"


@pytest.fixture
def audio(tmp_path: Path) -> Path:
    path = tmp_path / "a.wav"
    path.write_bytes(b"RIFF")
    return path


def _make_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def exe(tmp_path: Path) -> Path:
    return _make_exe(tmp_path / "buzz")


class Runner:
    """Stands in for subprocess.run: writes a fixture where Buzz would, records the call."""

    def __init__(
        self, fixture: str | None = "buzz_words.srt", returncode: int = 0, stderr: str = ""
    ) -> None:
        self.fixture, self.returncode, self.stderr = fixture, returncode, stderr
        self.argv: list[str] = []
        self.kwargs: dict[str, Any] = {}
        self.out_dir: Path | None = None

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.argv, self.kwargs = list(argv), kwargs
        self.out_dir = Path(argv[argv.index("-d") + 1])
        if self.fixture:
            name = "sl03 (transcribed on 15-Nov-2026 20-42-14).srt"
            (self.out_dir / name).write_text((FIX / self.fixture).read_text())
        return subprocess.CompletedProcess(argv, self.returncode, "", self.stderr)


def install(monkeypatch: pytest.MonkeyPatch, runner: Callable[..., Any]) -> None:
    monkeypatch.setattr(buzz_mod.subprocess, "run", runner)


def test_success_words(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    runner = Runner()
    install(monkeypatch, runner)
    tr = BuzzBackend(exe, model_type="fasterwhisper", model_size="tiny.en").transcribe(
        audio, track="mic", session_id=SID, language="en", prompt="FDE"
    )
    assert isinstance(tr, Transcript)
    assert (tr.backend, tr.model, tr.prompt, tr.language) == (
        "buzz",
        "fasterwhisper:tiny.en",
        "FDE",
        "en",
    )
    # The sentence end after "first." splits the 18 words into 2 segments.
    assert [s.text for s in tr.segments] == [
        "Hello, um, I think we should, ah, ask the customer first.",
        "What does success look like for you?",
    ]
    words = tr.words()
    assert len(words) == 18
    assert all(w.track == "mic" and w.probability is None for w in words)
    assert words[0].start == 0.0
    assert words[-1].end == 6.4
    assert runner.out_dir is not None
    assert not runner.out_dir.exists()  # temp dir cleaned


def test_argv(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    runner = Runner()
    install(monkeypatch, runner)
    BuzzBackend(exe).transcribe(
        audio, track="system", session_id=SID, language="en", prompt="Um, FDE."
    )
    argv = runner.argv
    assert argv[0] == str(exe)
    assert argv[1] == "add"
    assert argv[argv.index("-l") + 1] == "en"
    assert argv[argv.index("-p") + 1] == "Um, FDE."
    assert "-w" in argv
    assert "--srt" in argv
    assert "--hide-gui" in argv
    assert argv[-1] == str(audio.resolve())
    assert "openaiapi" not in argv
    assert runner.kwargs.get("shell") in (None, False)
    assert runner.kwargs["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert runner.kwargs["env"]["BUZZ_DISABLE_TELEMETRY"] == "1"
    assert runner.kwargs["timeout"] == 1800.0


def test_optional_flags_omitted(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    runner = Runner(fixture="buzz_segments.srt")
    install(monkeypatch, runner)
    tr = BuzzBackend(exe).transcribe(audio, track="mic", session_id=SID, word_timestamps=False)
    assert "-l" not in runner.argv
    assert "-p" not in runner.argv
    assert "-w" not in runner.argv
    assert tr.language is None
    assert tr.prompt is None
    assert len(tr.segments) == 1
    assert tr.segments[0].words == ()
    assert tr.segments[0].end == 6.43


def test_segment_cues_without_words_when_words_requested(
    monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path
) -> None:
    install(monkeypatch, Runner(fixture="buzz_segments.srt"))
    tr = BuzzBackend(exe).transcribe(audio, track="mic", session_id=SID)
    assert tr.segments[0].words == ()


def test_nonzero_exit(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    install(monkeypatch, Runner(fixture=None, returncode=3, stderr="a\nboom happened\n"))
    with pytest.raises(TranscriptionError, match=r"exit code 3(?s:.*)boom happened"):
        BuzzBackend(exe).transcribe(audio, track="mic", session_id=SID)


def test_exit_zero_without_output_is_failure(
    monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path
) -> None:
    install(monkeypatch, Runner(fixture=None, stderr="whisper-cli failed with return code -6"))
    with pytest.raises(TranscriptionError, match=r"no SRT output(?s:.*)return code -6"):
        BuzzBackend(exe).transcribe(audio, track="mic", session_id=SID)


def test_stderr_tail_is_short(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    stderr = "\n".join(f"line{i}" for i in range(500))
    install(monkeypatch, Runner(fixture=None, returncode=1, stderr=stderr))
    with pytest.raises(TranscriptionError) as info:
        BuzzBackend(exe).transcribe(audio, track="mic", session_id=SID)
    assert "line499" in str(info.value)
    assert "line0\n" not in str(info.value)


def test_timeout(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    def boom(argv: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    install(monkeypatch, boom)
    with pytest.raises(TranscriptionError, match="timed out after 5s"):
        BuzzBackend(exe, timeout_s=5).transcribe(audio, track="mic", session_id=SID)


def test_exec_oserror(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    def boom(argv: list[str], **kwargs: Any) -> None:
        raise PermissionError("nope")

    install(monkeypatch, boom)
    with pytest.raises(TranscriptionError, match="Could not run Buzz"):
        BuzzBackend(exe).transcribe(audio, track="mic", session_id=SID)


def test_unparseable_output(monkeypatch: pytest.MonkeyPatch, audio: Path, exe: Path) -> None:
    def write_bad(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        (Path(argv[argv.index("-d") + 1]) / "x.srt").write_text("1\ngarbage\ntext\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    install(monkeypatch, write_bad)
    with pytest.raises(TranscriptionError, match="parse"):
        BuzzBackend(exe).transcribe(audio, track="mic", session_id=SID)


def test_missing_audio(exe: Path, tmp_path: Path) -> None:
    with pytest.raises(TranscriptionError, match="Audio file not found"):
        BuzzBackend(exe).transcribe(tmp_path / "nope.wav", track="mic", session_id=SID)


def test_openai_api_rejected() -> None:
    with pytest.raises(TranscriptionError, match="paid"):
        BuzzBackend(model_type="openaiapi")


def test_missing_executable(audio: Path, tmp_path: Path) -> None:
    with pytest.raises(TranscriptionError, match="not found"):
        BuzzBackend(tmp_path / "missing").transcribe(audio, track="mic", session_id=SID)


def test_resolution_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exe: Path) -> None:
    home = tmp_path / "home"
    venv = _make_exe(home / ".venvs" / "buzz" / "bin" / "buzz")
    path_buzz = _make_exe(tmp_path / "pathbin" / "buzz")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(path_buzz.parent))
    monkeypatch.delenv("SPEAKLOOP_BUZZ", raising=False)

    assert resolve_executable(exe) == exe
    monkeypatch.setenv("SPEAKLOOP_BUZZ", str(exe))
    assert resolve_executable() == exe
    monkeypatch.delenv("SPEAKLOOP_BUZZ")
    assert resolve_executable() == venv
    venv.unlink()
    assert resolve_executable() == path_buzz
    path_buzz.unlink()
    with pytest.raises(TranscriptionError, match="SPEAKLOOP_BUZZ"):
        resolve_executable()


def test_fake_backend(audio: Path) -> None:
    fake = FakeBackend([("Hello.", 0.0, 0.5), ("Next", 0.6, 1.0), ("one", 2.0, 2.2)])
    backend: TranscriptionBackend = fake
    tr = backend.transcribe(audio, track="system", session_id=SID, prompt="p")
    assert [s.text for s in tr.segments] == ["Hello.", "Next", "one"]  # sentence end, then gap
    assert tr.backend == "fake"
    assert tr.prompt == "p"
    assert tr.language == "en"
    assert all(w.track == "system" for w in tr.words())
    assert fake.calls == [audio]
    bare = fake.transcribe(audio, track="mic", session_id=SID, word_timestamps=False)
    assert not any(s.words for s in bare.segments)


def test_build_segments_gap_threshold() -> None:
    def w(t: str, s: float, e: float) -> Word:
        return Word(text=t, start=s, end=e, track="mic")

    below = build_segments([w("a", 0, 1), w("b", 1.79, 2)], track="mic")
    at = build_segments([w("a", 0, 1), w("b", 1.8, 2)], track="mic")
    quoted = build_segments([w('end."', 0, 1), w("next", 1.1, 2)], track="mic")
    assert len(below) == 1
    assert len(at) == 2
    assert len(quoted) == 2


@pytest.mark.integration
def test_buzz_end_to_end(tmp_path: Path) -> None:
    if os.environ.get("SPEAKLOOP_RUN_INTEGRATION") != "1":
        pytest.skip("set SPEAKLOOP_RUN_INTEGRATION=1 to run")
    try:
        resolve_executable()
    except TranscriptionError:
        pytest.skip("Buzz executable not found")
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        pytest.skip("needs macOS `say` and ffmpeg")
    aiff, wav = tmp_path / "s.aiff", tmp_path / "s.wav"
    speech = "Hello. We should ask the customer first."
    subprocess.run(["say", "-o", str(aiff), speech], check=True)
    ffmpeg = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-ar", "16000", "-ac", "1"]
    subprocess.run([*ffmpeg, str(wav)], check=True)
    tr = BuzzBackend(model_size="tiny.en", timeout_s=900).transcribe(
        wav, track="mic", session_id=SID, language="en"
    )
    assert "customer" in tr.text().lower()
    assert len(tr.words()) >= 5
