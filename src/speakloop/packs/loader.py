"""Discover and load scenario packs stored as TOML under ``packs/data/<pack>/``."""

import tomllib
from pathlib import Path

from pydantic import ValidationError

from speakloop.packs.models import Scenario

DATA_DIR = Path(__file__).parent / "data"


class PackError(ValueError):
    """Raised when a scenario file is missing, malformed or invalid, or an id is unknown."""


def load_scenario_file(path: Path, expected_pack: str | None = None) -> Scenario:
    """Load and validate one scenario file."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise PackError(f"cannot read scenario {path}: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PackError(f"invalid TOML in scenario {path}: {exc}") from exc
    try:
        scenario = Scenario.model_validate(data)
    except ValidationError as exc:
        raise PackError(f"invalid scenario {path}: {exc}") from exc
    if expected_pack is not None and scenario.pack != expected_pack:
        raise PackError(
            f"invalid scenario {path}: pack {scenario.pack!r} does not match "
            f"folder {expected_pack!r}"
        )
    return scenario


def load_all(data_dir: Path | None = None) -> tuple[Scenario, ...]:
    """Load every scenario under ``data_dir`` (default: bundled data), sorted by pack and id."""
    root = data_dir if data_dir is not None else DATA_DIR
    found: list[Scenario] = []
    seen: dict[str, Path] = {}
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for path in sorted(pack_dir.glob("*.toml")):
            scenario = load_scenario_file(path, expected_pack=pack_dir.name)
            if scenario.id in seen:
                raise PackError(
                    f"duplicate scenario id {scenario.id!r} in {path} and {seen[scenario.id]}"
                )
            seen[scenario.id] = path
            found.append(scenario)
    return tuple(sorted(found, key=lambda s: (s.pack, s.id)))


def list_scenarios(pack: str | None = None, data_dir: Path | None = None) -> tuple[Scenario, ...]:
    """List scenarios, optionally filtered by pack name."""
    scenarios = load_all(data_dir)
    if pack is None:
        return scenarios
    return tuple(s for s in scenarios if s.pack == pack)


def get_scenario(scenario_id: str, data_dir: Path | None = None) -> Scenario:
    """Return one scenario by id or raise ``PackError``."""
    for scenario in load_all(data_dir):
        if scenario.id == scenario_id:
            return scenario
    raise PackError(f"unknown scenario id {scenario_id!r}")
