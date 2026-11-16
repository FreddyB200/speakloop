from pathlib import Path

import pytest

from speakloop.models import SessionKind
from speakloop.packs import PackError, get_scenario, list_scenarios
from speakloop.packs.loader import load_all, load_scenario_file
from speakloop.packs.models import Scenario

VALID = """\
id = "demo-one"
title = "Demo"
kind = "discovery"
pack = "demo"
difficulty = 1
candidate_brief = "Brief."
interviewer_persona = "Persona."

[[hidden_facts]]
id = "f1"
fact = "A secret."
revealed_when = "about secrets"

[[questions]]
id = "q1"
text = "First question?"
"""


def _write(root: Path, pack: str, name: str, text: str) -> Path:
    folder = root / pack
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_bundled_scenarios_load() -> None:
    scenarios = list_scenarios()
    assert len(scenarios) == 10
    assert all(s.pack == "fde" for s in scenarios)
    ids = [s.id for s in scenarios]
    assert len(set(ids)) == len(ids)


def test_discovery_and_pressure_have_hidden_facts() -> None:
    for s in list_scenarios("fde"):
        if s.kind in (SessionKind.DISCOVERY, SessionKind.PRESSURE):
            assert 3 <= len(s.hidden_facts) <= 5, s.id
        assert s.questions, s.id
        assert s.evaluation_focus, s.id
        assert s.phrases, s.id


def test_kinds_cover_expected_types() -> None:
    kinds = {s.kind for s in list_scenarios("fde")}
    assert kinds == {
        SessionKind.DISCOVERY,
        SessionKind.PRESSURE,
        SessionKind.DEEP_DIVE,
        SessionKind.BEHAVIORAL,
    }


def test_get_scenario_and_unknown() -> None:
    assert get_scenario("project-deep-dive").kind is SessionKind.DEEP_DIVE
    with pytest.raises(PackError, match="unknown scenario id"):
        get_scenario("nope")


def test_list_filters_by_pack(tmp_path: Path) -> None:
    _write(tmp_path, "demo", "one.toml", VALID)
    assert [s.id for s in list_scenarios("demo", data_dir=tmp_path)] == ["demo-one"]
    assert list_scenarios("other", data_dir=tmp_path) == ()


def test_malformed_toml_names_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "demo", "broken.toml", "id = [")
    with pytest.raises(PackError, match=r"broken\.toml"):
        load_scenario_file(path)


def test_invalid_scenario_names_the_file(tmp_path: Path) -> None:
    _write(tmp_path, "demo", "bad.toml", VALID.replace("difficulty = 1", "difficulty = 9"))
    with pytest.raises(PackError, match=r"bad\.toml"):
        load_all(tmp_path)


def test_pack_must_match_folder(tmp_path: Path) -> None:
    _write(tmp_path, "other", "one.toml", VALID)
    with pytest.raises(PackError, match="does not match folder"):
        load_all(tmp_path)


def test_duplicate_ids_across_files(tmp_path: Path) -> None:
    _write(tmp_path, "demo", "a.toml", VALID)
    _write(tmp_path, "demo", "b.toml", VALID)
    with pytest.raises(PackError, match="duplicate scenario id"):
        load_all(tmp_path)


def _scenario(**overrides: object) -> Scenario:
    data: dict[str, object] = {
        "id": "demo",
        "title": "T",
        "kind": "discovery",
        "pack": "p",
        "difficulty": 1,
        "candidate_brief": "b",
        "interviewer_persona": "p",
        "hidden_facts": [{"id": "f", "fact": "x", "revealed_when": "y"}],
        "questions": [{"id": "q", "text": "t"}],
    }
    data.update(overrides)
    return Scenario.model_validate(data)


def test_model_validation_rules() -> None:
    assert _scenario().questions[0].time_s == 45
    with pytest.raises(ValueError, match="hidden fact"):
        _scenario(hidden_facts=[])
    with pytest.raises(ValueError, match="not valid for an interview"):
        _scenario(kind="shadowing")
    with pytest.raises(ValueError, match="slug"):
        _scenario(id="Bad Id")
    with pytest.raises(ValueError, match="duplicate question"):
        _scenario(questions=[{"id": "q", "text": "a"}, {"id": "q", "text": "b"}])
    with pytest.raises(ValueError, match="duplicate hidden fact"):
        _scenario(
            hidden_facts=[
                {"id": "f", "fact": "x", "revealed_when": "y"},
                {"id": "f", "fact": "z", "revealed_when": "w"},
            ]
        )
    with pytest.raises(ValueError):
        _scenario(questions=[])
    with pytest.raises(ValueError):
        _scenario(questions=[{"id": "q", "text": ""}])
    with pytest.raises(ValueError, match="empty text"):
        _scenario(phrases=["  "])
    assert _scenario(kind="behavioral", hidden_facts=[]).hidden_facts == ()
