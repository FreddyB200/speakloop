import pytest

from speakloop.packs import list_scenarios, render_interviewer_script
from speakloop.packs.models import Scenario


@pytest.mark.parametrize("scenario", list_scenarios("fde"), ids=lambda s: s.id)
def test_script_contents(scenario: Scenario) -> None:
    script = render_interviewer_script(scenario)
    assert scenario.interviewer_persona in script
    assert scenario.questions[0].text in script
    for follow_up in scenario.questions[1:]:
        assert follow_up.text in script
    for fact in scenario.hidden_facts:
        assert fact.fact in script
        assert f"IF the candidate asks {fact.revealed_when}" in script
    assert "NEVER volunteer" in script or not scenario.hidden_facts
    assert "Never coach" in script


@pytest.mark.parametrize("scenario", list_scenarios("fde"), ids=lambda s: s.id)
def test_script_excludes_auditor_material(scenario: Scenario) -> None:
    script = render_interviewer_script(scenario)
    for focus in scenario.evaluation_focus:
        assert focus not in script
    for question in scenario.questions:
        if question.guidance:
            assert question.guidance not in script
    for phrase in scenario.phrases:
        assert phrase not in script


def test_script_minutes_and_no_facts_section() -> None:
    scenario = next(s for s in list_scenarios("fde") if not s.hidden_facts)
    script = render_interviewer_script(scenario, minutes=12)
    assert "about 12 minutes" in script
    assert "Hidden facts" not in script
