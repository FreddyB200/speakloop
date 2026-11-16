"""Markdown session report with YAML front matter (readable in Obsidian and on GitHub).

The front matter keys are a stable contract for future trend dashboards. Missing values
are emitted as `null`:

    type                       always "speakloop-session"
    date                       ISO date of `Session.created_at`
    session_id, kind, scenario scenario is the scenario id or null
    duration_min               minutes, 1 decimal
    word_count                 words by the speaker
    wpm_mean, wpm_cv           mean words per minute (1 decimal), its variation (3 decimals)
    fillers_per_100w           filler words per 100 words (1 decimal)
    long_pauses                count of long pauses
    repetitions, false_starts  counts
    mattr                      lexical diversity (3 decimals)
    response_latency_median_s  median wait before answering (2 decimals), or null
    clarifying_questions       FDE: questions before the first proposal, else null
    talk_ratio                 FDE: speaker share of talk time (3 decimals), else null
    risky_commitments          FDE: count of risky commitments, else null
    closed_with_next_steps     FDE: true/false, else null
    findings                   total number of findings
    top_patterns               titles of the findings shown in the report (inline list)
    next_goal                  the next session goal, or null

Output is deterministic: no clock and no randomness.
"""

import json
import re
import statistics
from collections.abc import Sequence

from speakloop.models import Evidence, Finding, Metrics, Session

MAX_FINDINGS = 5
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]<>#|~])")


def format_timestamp(seconds: float) -> str:
    """Format seconds as `mm:ss`, or `h:mm:ss` from one hour on."""
    total = int(max(seconds, 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def escape_markdown(text: str) -> str:
    """Escape Markdown-sensitive characters and collapse whitespace to single spaces."""
    return _MD_SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _scalar(value: str | float | bool | None) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def _num(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _front_matter(
    session: Session,
    metrics: Metrics,
    findings: Sequence[Finding],
    shown: Sequence[Finding],
    next_goal: str | None,
) -> str:
    fde = metrics.fde
    latency = metrics.response_latencies_s
    entries: list[tuple[str, str]] = [
        ("type", _scalar("speakloop-session")),
        ("date", _scalar(session.created_at.date().isoformat())),
        ("session_id", _scalar(session.id)),
        ("kind", _scalar(session.kind.value)),
        ("scenario", _scalar(session.scenario_id)),
        ("duration_min", _scalar(round(metrics.duration_s / 60, 1))),
        ("word_count", _scalar(metrics.word_count)),
        ("wpm_mean", _scalar(round(metrics.wpm_mean, 1))),
        ("wpm_cv", _scalar(_num(metrics.wpm_cv, 3))),
        ("fillers_per_100w", _scalar(round(metrics.fillers_per_100w, 1))),
        ("long_pauses", _scalar(len(metrics.long_pauses))),
        ("repetitions", _scalar(metrics.repetitions)),
        ("false_starts", _scalar(metrics.false_starts)),
        ("mattr", _scalar(_num(metrics.mattr, 3))),
        (
            "response_latency_median_s",
            _scalar(round(statistics.median(latency), 2) if latency else None),
        ),
        (
            "clarifying_questions",
            _scalar(fde.clarifying_questions_before_proposal if fde else None),
        ),
        ("talk_ratio", _scalar(_num(fde.talk_ratio, 3) if fde else None)),
        ("risky_commitments", _scalar(len(fde.risky_commitments) if fde else None)),
        ("closed_with_next_steps", _scalar(fde.closed_with_next_steps if fde else None)),
        ("findings", _scalar(len(findings))),
        ("top_patterns", "[" + ", ".join(_scalar(f.title) for f in shown) + "]"),
        ("next_goal", _scalar(next_goal)),
    ]
    body = "\n".join(f"{key}: {value}" for key, value in entries)
    return f"---\n{body}\n---"


def _na(value: str | None) -> str:
    return "n/a" if value is None else value


def _metrics_table(metrics: Metrics) -> str:
    latency = metrics.response_latencies_s
    rows = [
        ("Duration", f"{metrics.duration_s / 60:.1f} min", "Length of the recording."),
        ("Words", str(metrics.word_count), "Words you spoke."),
        ("Pace", f"{metrics.wpm_mean:.0f} wpm", "Average words per minute."),
        (
            "Pace variation",
            _na(None if metrics.wpm_cv is None else f"{metrics.wpm_cv:.2f}"),
            "How much the pace changes between windows; higher means less even.",
        ),
        (
            "Fillers",
            f"{metrics.fillers_per_100w:.1f} per 100 words",
            "Filler words and phrases such as um, uh or you know.",
        ),
        (
            "Long pauses",
            f"{len(metrics.long_pauses)} (over {metrics.long_pause_threshold_s:g} s)",
            "Silences longer than the threshold.",
        ),
        ("Repetitions", str(metrics.repetitions), "Words or phrases repeated back to back."),
        ("False starts", str(metrics.false_starts), "Sentences begun and then abandoned."),
        (
            "Lexical diversity",
            _na(None if metrics.mattr is None else f"{metrics.mattr:.2f}"),
            "MATTR: share of distinct words in a sliding window; higher means more varied.",
        ),
        (
            "Response latency",
            _na(None if not latency else f"{statistics.median(latency):.1f} s (median)"),
            "Time between the other person finishing and you starting.",
        ),
    ]
    lines = ["| Metric | Value | Meaning |", "| --- | --- | --- |"]
    lines += [f"| {name} | {value} | {meaning} |" for name, value, meaning in rows]
    return "\n".join(lines)


def _quote(evidence: Evidence, show_track: bool) -> str:
    label = format_timestamp(evidence.start)
    if show_track:
        label += f", {evidence.track}"
    return f"> {escape_markdown(evidence.quote)} ({label})"


def _finding_block(finding: Finding, show_track: bool) -> str:
    lines = [
        f"### {escape_markdown(finding.title)}",
        "",
        f"*{finding.category.value.replace('_', ' ')}, severity {finding.severity} of 3*",
        "",
        escape_markdown(finding.explanation),
    ]
    if finding.suggestion:
        lines += ["", f"**Suggestion:** {escape_markdown(finding.suggestion)}"]
    lines.append("")
    lines += [_quote(e, show_track) + "  " for e in finding.evidence]
    return "\n".join(lines).rstrip()


def _fde_section(metrics: Metrics, show_track: bool) -> str | None:
    fde = metrics.fde
    if fde is None:
        return None
    count = fde.clarifying_questions_before_proposal
    questions = "n/a" if count is None else str(count)
    ratio = "n/a" if fde.talk_ratio is None else f"{fde.talk_ratio * 100:.0f}%"
    closed = "n/a" if fde.closed_with_next_steps is None else _yes_no(fde.closed_with_next_steps)
    lines = [
        "## FDE",
        "",
        f"- Clarifying questions before the first proposal: {questions}",
        f"- Talk ratio (your share of the talking): {ratio}",
        f"- Closed with next steps: {closed}",
        f"- Risky commitments: {len(fde.risky_commitments)}",
    ]
    if fde.risky_commitments:
        lines.append("")
        lines += [_quote(e, show_track) + "  " for e in fde.risky_commitments]
    return "\n".join(lines).rstrip()


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def render_report(
    session: Session,
    metrics: Metrics,
    findings: Sequence[Finding],
    *,
    summary: str | None = None,
    next_session_goal: str | None = None,
) -> str:
    """Render the Markdown report of a session."""
    show_track = len(session.tracks) > 1
    ordered = sorted(findings, key=lambda f: -f.severity)  # stable: ties keep input order
    shown = ordered[:MAX_FINDINGS]
    kind = session.kind.value.replace("_", " ")
    parts = [
        _front_matter(session, metrics, findings, shown, next_session_goal),
        f"# {kind.capitalize()} session, {session.created_at.date().isoformat()}",
    ]
    if summary:
        parts.append(escape_markdown(summary))
    parts += ["## Metrics", _metrics_table(metrics)]
    parts.append("## Patterns")
    if shown:
        parts += [_finding_block(f, show_track) for f in shown]
    else:
        parts.append("No patterns found.")
    fde = _fde_section(metrics, show_track)
    if fde is not None:
        parts.append(fde)
    parts += [
        "## Next session goal",
        escape_markdown(next_session_goal) if next_session_goal else "No goal set.",
    ]
    return "\n\n".join(parts) + "\n"
