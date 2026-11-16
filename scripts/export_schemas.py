"""Write JSON Schemas of the core models to docs/schemas/<model>.json."""

import json
from pathlib import Path

from pydantic import BaseModel

from speakloop.models import Finding, Item, Metrics, Session, Transcript

MODELS: tuple[type[BaseModel], ...] = (Session, Transcript, Metrics, Finding, Item)
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "docs" / "schemas"


def render(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        (SCHEMAS_DIR / f"{model.__name__}.json").write_text(render(model), encoding="utf-8")


if __name__ == "__main__":
    main()
