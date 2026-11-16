"""Command-line interface for SpeakLoop."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

import typer

from speakloop import __version__
from speakloop.audit.base import AuditBackend, AuditBackendError
from speakloop.audit.claude_code import ClaudeCodeBackend
from speakloop.audit.rubric import RubricError, load_rubric
from speakloop.export.obsidian import export_to_folder
from speakloop.export.report import render_report
from speakloop.models import SessionKind
from speakloop.pipeline import DEFAULT_TRANSCRIPTION_PROMPT, PipelineError, run_session
from speakloop.transcribe.base import TranscriptionBackend, TranscriptionError
from speakloop.transcribe.buzz import BuzzBackend, resolve_executable
from speakloop.workspace import Workspace

OBSIDIAN_ENV_VAR = "SPEAKLOOP_OBSIDIAN_DIR"

app = typer.Typer(
    name="speakloop",
    help="A local-first speaking coach.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """A local-first speaking coach."""


@app.command()
def version() -> None:
    """Print the installed SpeakLoop version."""
    typer.echo(f"speakloop {__version__}")


def _check_workspace(workspace: Workspace) -> str | None:
    """Return an error message if the workspace folder cannot be created or written."""
    try:
        workspace.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=workspace.root, prefix=".doctor-"):
            pass
    except OSError as exc:
        return f"{exc.strerror or exc}"
    return None


@app.command()
def doctor() -> None:
    """Check that the local environment has what SpeakLoop needs."""
    ok = True
    claude_path = shutil.which("claude")
    if claude_path is None:
        ok = False
        typer.echo("claude: NOT FOUND on PATH. Install Claude Code to enable AI audits.")
    else:
        typer.echo(f"claude: found at {claude_path}")
    try:
        typer.echo(f"buzz: found at {resolve_executable()}")
    except TranscriptionError as exc:
        ok = False
        typer.echo(f"buzz: NOT FOUND. {exc}")
    workspace = Workspace.default()
    problem = _check_workspace(workspace)
    if problem is None:
        typer.echo(f"workspace: {workspace.root} is writable")
    else:
        ok = False
        typer.echo(f"workspace: NOT WRITABLE {workspace.root}: {problem}")
    if not ok:
        raise typer.Exit(code=1)


def make_transcriber(model_size: str) -> TranscriptionBackend:
    """Build the real transcription backend (replaced by fakes in tests)."""
    return BuzzBackend(model_size=model_size)


def make_auditor() -> AuditBackend:
    """Build the real audit backend (replaced by fakes in tests)."""
    return ClaudeCodeBackend()


def _export_dir(option: Path | None) -> Path | None:
    if option is not None:
        return option
    env = os.environ.get(OBSIDIAN_ENV_VAR)
    return Path(env) if env else None


def _fail(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code=1)


@app.command()
def audit(
    audio: Annotated[Path, typer.Argument(help="Audio file with the speaker (mic) track.")],
    system: Annotated[
        Path | None, typer.Option("--system", help="Audio file with the other side of the call.")
    ] = None,
    kind: Annotated[
        SessionKind, typer.Option("--kind", help="Type of session.")
    ] = SessionKind.FREE,
    scenario: Annotated[str | None, typer.Option("--scenario", help="Scenario id.")] = None,
    language: Annotated[str, typer.Option("--language", help="Spoken language code.")] = "en",
    no_prompt: Annotated[
        bool, typer.Option("--no-prompt", help="Do not send the disfluency initial prompt.")
    ] = False,
    model_size: Annotated[
        str, typer.Option("--model-size", help="Whisper model size.")
    ] = "small.en",
    glossary: Annotated[
        str | None,
        typer.Option(
            "--glossary",
            help="Comma-separated names and terms to help transcription "
            "(added to <workspace>/glossary.txt).",
        ),
    ] = None,
    no_audit: Annotated[
        bool, typer.Option("--no-audit", help="Skip the AI audit (transcript and metrics only).")
    ] = False,
    workspace_path: Annotated[
        Path | None, typer.Option("--workspace", help="Workspace folder.")
    ] = None,
    obsidian_dir: Annotated[
        Path | None,
        typer.Option(
            "--obsidian-dir", help=f"Also export the report here (env {OBSIDIAN_ENV_VAR})."
        ),
    ] = None,
) -> None:
    """Transcribe, measure and audit a recorded session, then write a report."""
    for label, path in (("audio", audio), ("system audio", system)):
        if path is not None and not path.expanduser().is_file():
            raise _fail(f"{label} file not found: {path}")
    workspace = Workspace(workspace_path.expanduser()) if workspace_path else Workspace.default()
    export_dir = _export_dir(obsidian_dir)
    try:
        terms = workspace.load_glossary()
    except (OSError, UnicodeDecodeError) as exc:
        raise _fail(f"cannot read glossary file {workspace.glossary_path}: {exc}") from exc
    if glossary:
        terms += [t.strip() for t in glossary.split(",") if t.strip()]
    try:
        rubric = load_rubric()
    except RubricError as exc:
        raise _fail(str(exc)) from exc

    try:
        result = run_session(
            audio.expanduser(),
            audio_system=system.expanduser() if system else None,
            kind=kind,
            scenario_id=scenario,
            workspace=workspace,
            transcriber=make_transcriber(model_size),
            auditor=None if no_audit else make_auditor(),
            rubric=rubric,
            language=language,
            prompt=None if no_prompt else DEFAULT_TRANSCRIPTION_PROMPT,
            glossary=terms,
        )
    except (PipelineError, AuditBackendError, TranscriptionError) as exc:
        raise _fail(str(exc)) from exc

    m = result.metrics
    typer.echo(f"session: {result.session.id}")
    typer.echo(f"duration: {m.duration_s:.1f} s")
    typer.echo(f"wpm: {m.wpm_mean:.1f}")
    typer.echo(f"fillers per 100 words: {m.fillers_per_100w:.1f}")
    typer.echo(f"findings: {len(result.findings)}")
    if result.dropped_quotes is not None:
        typer.echo(f"dropped quotes: {result.dropped_quotes}")
        typer.echo(f"discarded findings: {result.discarded_findings}")
    typer.echo(f"report: {result.report_path}")

    failed = False
    if export_dir is not None:
        try:
            text = result.report_path.read_text(encoding="utf-8")
            typer.echo(f"exported: {export_to_folder(text, result.session, export_dir)}")
        except (OSError, ValueError) as exc:
            typer.echo(f"error: export failed: {exc}", err=True)
            failed = True
    if result.audit_error is not None:
        typer.echo(f"error: {result.audit_error} (report written without patterns)", err=True)
        failed = True
    if failed:
        raise typer.Exit(code=1)


@app.command()
def report(
    session_id: Annotated[str, typer.Argument(help="Session id, e.g. 20260105-093000-a1b2.")],
    workspace_path: Annotated[
        Path | None, typer.Option("--workspace", help="Workspace folder.")
    ] = None,
    obsidian_dir: Annotated[
        Path | None,
        typer.Option(
            "--obsidian-dir",
            help=f"Replace the exported report in this folder (env {OBSIDIAN_ENV_VAR}).",
        ),
    ] = None,
    no_transcript: Annotated[
        bool, typer.Option("--no-transcript", help="Leave the transcript section out.")
    ] = False,
) -> None:
    """Re-render the report of a saved session, optionally replacing its exported copy."""
    workspace = Workspace(workspace_path.expanduser()) if workspace_path else Workspace.default()
    if not workspace.has_session(session_id):
        raise _fail(f"unknown session id {session_id!r} in workspace {workspace.root}")
    try:
        session = workspace.load_session(session_id)
        transcript = workspace.load_transcript(session_id)
        metrics = workspace.load_metrics(session_id)
        findings = workspace.load_findings(session_id)
        saved_audit = workspace.load_audit(session_id)
    except (OSError, ValueError) as exc:
        raise _fail(f"cannot load session {session_id}: {exc}") from exc
    text = render_report(
        session,
        metrics,
        findings,
        summary=saved_audit.summary if saved_audit else None,
        next_session_goal=saved_audit.next_session_goal if saved_audit else None,
        transcript=None if no_transcript else transcript,
    )
    typer.echo(f"report: {workspace.save_report(session_id, text)}")
    export_dir = _export_dir(obsidian_dir)
    if export_dir is not None:
        try:
            typer.echo(f"exported: {export_to_folder(text, session, export_dir, replace=True)}")
        except (OSError, ValueError) as exc:
            raise _fail(f"export failed: {exc}") from exc
