"""Typed audit rubric loaded from a TOML file and validated."""

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from speakloop.models import FindingCategory

DEFAULT_RUBRIC_PATH = Path(__file__).parent / "rubric" / "default.toml"


class RubricError(ValueError):
    """Raised when a rubric file is missing, malformed or invalid."""


class RubricEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class Rubric(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    max_patterns: int = Field(ge=1, le=20)
    spoken_english_instruction: str = Field(min_length=1)
    categories: tuple[RubricEntry, ...] = Field(min_length=1)
    fde_dimensions: tuple[RubricEntry, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "Rubric":
        valid = {c.value for c in FindingCategory}
        names = [c.name for c in self.categories]
        unknown = sorted(set(names) - valid)
        if unknown:
            raise ValueError(f"unknown category names: {', '.join(unknown)}")
        if len(set(names)) != len(names):
            raise ValueError("duplicate category names")
        dims = [d.name for d in self.fde_dimensions]
        if len(set(dims)) != len(dims):
            raise ValueError("duplicate FDE dimension names")
        return self


def load_rubric(path: Path | None = None) -> Rubric:
    """Load and validate a rubric; the bundled default is used when no path is given."""
    target = path if path is not None else DEFAULT_RUBRIC_PATH
    try:
        with target.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise RubricError(f"cannot read rubric {target}: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RubricError(f"invalid TOML in rubric {target}: {exc}") from exc
    try:
        return Rubric.model_validate(data)
    except ValidationError as exc:
        raise RubricError(f"invalid rubric {target}: {exc}") from exc
