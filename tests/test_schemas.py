"""Guards that the committed JSON Schemas match the models."""

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "export_schemas", ROOT / "scripts" / "export_schemas.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_schemas_are_up_to_date() -> None:
    script = _load_script()
    for model in script.MODELS:
        path = ROOT / "docs" / "schemas" / f"{model.__name__}.json"
        assert path.read_text(encoding="utf-8") == script.render(model), (
            f"{path.name} is stale: run `uv run python scripts/export_schemas.py`"
        )
