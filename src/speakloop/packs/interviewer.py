"""Render a self-contained prompt for a voice AI that plays the interviewer."""

from speakloop.packs.models import Scenario


def render_interviewer_script(scenario: Scenario, minutes: int = 8) -> str:
    """Build the text a user pastes into a voice AI (ChatGPT or Claude voice).

    Evaluation focus is deliberately left out: it is for the auditor, not the interviewer.
    """
    first, *follow_ups = scenario.questions
    lines: list[str] = [
        "You are playing a role in a spoken mock interview. Stay in character the whole time.",
        "",
        "## Your role",
        scenario.interviewer_persona,
        "",
        "## Context the candidate has read",
        scenario.candidate_brief,
        "",
        "## Rules",
        "- Speak like a real person on a call: short answers, one to three sentences.",
        "- Open the session yourself with the first question below, then wait for the candidate.",
        "- Never coach, praise, correct or give feedback during the session. Stay in character.",
        "- Do not interrupt long answers. If the candidate goes silent, wait a few seconds, "
        'then say something short such as "Take your time."',
        "- Keep the conversation moving: ask the follow-up questions below one at a time, "
        "naturally, when the topic fits or the conversation slows down.",
        f"- After about {minutes} minutes, wrap up with a brief closing line in character "
        "and stop.",
        "",
        "## Opening question",
        first.text,
        "",
    ]
    if follow_ups:
        lines.append("## Follow-up questions (ask them one at a time, in your own words)")
        lines.extend(f"- {q.text}" for q in follow_ups)
        lines.append("")
    if scenario.hidden_facts:
        lines += [
            "## Hidden facts (secret)",
            "You know the facts below, but the candidate does not. NEVER volunteer them and "
            "never hint at them. Reveal a fact only if the candidate asks a question that "
            "matches its condition, and then answer briefly and naturally. If the candidate "
            "never asks, the fact stays hidden. If the question is vague, answer vaguely and "
            "let the candidate dig deeper.",
            "",
        ]
        for fact in scenario.hidden_facts:
            lines.append(f"- IF the candidate asks {fact.revealed_when}, THEN reveal: {fact.fact}")
        lines.append("")
    lines += [
        "## Start",
        "Begin now by greeting the candidate in one sentence and asking the opening question.",
    ]
    return "\n".join(lines) + "\n"
