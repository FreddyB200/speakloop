"""Tests for exporting a report into a folder."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from speakloop.export import export_to_folder
from speakloop.models import Session, SessionKind, Track

SESSION = Session(
    id="20260105-093000-a1b2",
    created_at=datetime(2026, 1, 5, 9, 30, tzinfo=UTC),
    kind=SessionKind.DEEP_DIVE,
    tracks=(Track(id="mic", role="speaker"),),
)


def test_writes_named_file_and_creates_folder(tmp_path: Path) -> None:
    folder = tmp_path / "vault" / "SpeakLoop"
    path = export_to_folder("hello", SESSION, folder)
    assert path == folder / "2026-01-05 deep_dive 20260105-093000-a1b2.md"
    assert path.read_text(encoding="utf-8") == "hello"


def test_never_overwrites(tmp_path: Path) -> None:
    first = export_to_folder("one", SESSION, tmp_path)
    second = export_to_folder("two", SESSION, tmp_path)
    third = export_to_folder("three", SESSION, tmp_path)
    assert second.name == first.stem + " (2).md"
    assert third.name == first.stem + " (3).md"
    assert [p.read_text() for p in (first, second, third)] == ["one", "two", "three"]


def test_no_temp_files_left(tmp_path: Path) -> None:
    export_to_folder("one", SESSION, tmp_path)
    export_to_folder("two", SESSION, tmp_path)
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".md", ".md"]
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".")]


def test_relative_folder_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        export_to_folder("x", SESSION, Path("relative/dir"))


def test_tilde_is_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    path = export_to_folder("x", SESSION, Path("~/notes"))
    assert path.parent == tmp_path / "notes"
