"""Write a report into a user-chosen folder (for example an Obsidian vault)."""

import contextlib
import os
import tempfile
from pathlib import Path

from speakloop.models import Session


def _target_folder(folder: Path) -> Path:
    expanded = folder.expanduser()
    if not expanded.is_absolute():
        raise ValueError(f"export folder must be an absolute path: {folder}")
    return expanded


def export_to_folder(report: str, session: Session, folder: Path) -> Path:
    """Save the report as `<YYYY-MM-DD> <kind> <session_id>.md`; never overwrites.

    If the name is taken, " (2)", " (3)" ... is appended. The write is atomic: the text goes
    to a temp file in the same folder, which is then hard-linked to the final name (fails if
    the name exists) and removed.
    """
    directory = _target_folder(folder)
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{session.created_at.date().isoformat()} {session.kind.value} {session.id}"
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".speakloop-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(report)
            handle.flush()
            os.fsync(handle.fileno())
        number = 1
        while True:
            name = f"{base}.md" if number == 1 else f"{base} ({number}).md"
            target = directory / name
            try:
                os.link(tmp_name, target)
            except FileExistsError:
                number += 1
                continue
            return target
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
