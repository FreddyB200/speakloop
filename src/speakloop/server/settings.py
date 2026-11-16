"""Persisted settings: `<workspace>/config.toml` plus the existing `glossary.txt`."""

import contextlib
import json
import logging
import os
import tempfile
import tomllib

from speakloop.server.schemas import SettingsBody
from speakloop.workspace import Workspace

_log = logging.getLogger(__name__)


def _toml_string(value: str) -> str:
    # JSON string escapes (\", \\, \n, \uXXXX) are valid TOML basic-string escapes.
    return json.dumps(value, ensure_ascii=False)


def render_config(settings: SettingsBody) -> str:
    lines = ["# SpeakLoop settings (written by the web app)."]
    if settings.obsidian_dir is not None:
        lines.append(f"obsidian_dir = {_toml_string(settings.obsidian_dir)}")
    lines.append(f"model_size = {_toml_string(settings.model_size)}")
    lines.append(f"language = {_toml_string(settings.language)}")
    return "\n".join(lines) + "\n"


def load_settings(workspace: Workspace) -> SettingsBody:
    """Read settings; missing or unreadable values fall back to defaults."""
    data: dict[str, object] = {}
    try:
        data = tomllib.loads(workspace.config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        _log.warning("ignoring unreadable %s: %s", workspace.config_path, exc)
    picked: dict[str, object] = {
        key: data[key] for key in ("obsidian_dir", "model_size", "language") if key in data
    }
    try:
        glossary = workspace.load_glossary()
    except (OSError, UnicodeDecodeError) as exc:
        _log.warning("ignoring unreadable glossary: %s", exc)
        glossary = []
    try:
        return SettingsBody.model_validate({**picked, "glossary": glossary})
    except ValueError as exc:
        _log.warning("ignoring invalid settings in %s: %s", workspace.config_path, exc)
        return SettingsBody(glossary=glossary)


def save_settings(workspace: Workspace, settings: SettingsBody) -> None:
    workspace.root.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=workspace.root, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(render_config(settings))
        os.replace(tmp_name, workspace.config_path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    workspace.save_glossary(settings.glossary)
