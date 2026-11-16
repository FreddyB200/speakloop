"""Command-line interface for SpeakLoop."""

import shutil

import typer

from speakloop import __version__

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


@app.command()
def doctor() -> None:
    """Check that the local environment has what SpeakLoop needs."""
    claude_path = shutil.which("claude")
    if claude_path is None:
        typer.echo("claude: NOT FOUND on PATH. Install Claude Code to enable AI audits.")
        raise typer.Exit(code=1)
    typer.echo(f"claude: found at {claude_path}")


@app.command()
def audit() -> None:
    """Audit a recorded session (not implemented yet)."""
    typer.echo("audit: not implemented yet (milestone M1)", err=True)
    raise typer.Exit(code=2)
