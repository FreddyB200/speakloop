"""Audit backend that runs Claude Code in headless mode through the user's subscription.

Flags chosen, from `claude --help` (Claude Code CLI):

- `-p` / `--print`: "Print response and exit (useful for pipes)", i.e. non-interactive mode.
  The prompt is sent on stdin so long transcripts never hit argv limits or `ps` listings.
- `--output-format json`: "json (single result)": one JSON envelope on stdout, easy to parse.
- `--json-schema <schema>`: "JSON Schema for structured output validation (only works with
  --print)". The validated object comes back in the envelope's `structured_output`. If it is
  missing, the JSON is extracted from the text `result` instead (the prompt asks for JSON).
- `--tools ""`: "Use \"\" to disable all tools". The model cannot read files, run commands or
  browse: the transcript reaches it only through the prompt.
- `--strict-mcp-config`: "Only use MCP servers from --mcp-config, ignoring all other MCP
  configurations". No --mcp-config is given, so no MCP server is loaded.
- `--disable-slash-commands`: "Disable all skills and commands".
- `--no-session-persistence`: "sessions will not be saved to disk" (no transcript is left in
  the Claude Code history).
- `--permission-mode dontAsk` and `--permission-prompts none`: "anything that would prompt is
  denied automatically", a second line of defense behind `--tools ""`.
- `--setting-sources user`: "Comma-separated list of setting sources to load (user, project,
  local)". Only user settings (which carry the login) are read; the working directory is also a
  fresh empty temporary directory.

`--bare` is deliberately not used: its help says auth is strictly ANTHROPIC_API_KEY, which
would break the subscription login. ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are removed
from the child environment so the subscription is always the credential.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

from speakloop.audit.base import AuditBackendError

CLAUDE_ENV_VAR = "SPEAKLOOP_CLAUDE"
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def resolve_executable() -> str:
    """Return the `claude` executable: SPEAKLOOP_CLAUDE if set, else `claude` on PATH."""
    override = os.environ.get(CLAUDE_ENV_VAR)
    found = shutil.which(override) if override else shutil.which("claude")
    if found is None:
        raise AuditBackendError(
            f"Claude Code CLI not found: install `claude` or set {CLAUDE_ENV_VAR}"
        )
    return found


def build_argv(executable: str, json_schema: dict[str, object], model: str | None) -> list[str]:
    """Build the argument list (never joined into a shell string)."""
    argv = [
        executable,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(json_schema),
        "--tools",
        "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--setting-sources",
        "user",
    ]
    if model:
        argv += ["--model", model]
    return argv


def extract_json_text(text: str) -> object:
    """Decode a JSON object from model text, tolerating code fences and surrounding prose."""
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    if fenced:
        stripped = fenced.group(1)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def _type_ok(value: object, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def schema_errors(value: object, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Validate a JSON value against the small JSON Schema subset used by the audit schema."""
    errors: list[str] = []
    expected = schema.get("type")
    types = [expected] if isinstance(expected, str) else list(expected or [])
    if types and not any(_type_ok(value, t) for t in types):
        return [f"{path}: expected {'/'.join(types)}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: too short")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errors += schema_errors(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        properties: dict[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required field '{key}'")
        for key, item in value.items():
            if key in properties:
                errors += schema_errors(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected field '{key}'")
    return errors


class ClaudeCodeBackend:
    """AuditBackend that calls `claude -p` with tools disabled."""

    name = "claude-code"

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def complete_json(
        self,
        prompt: str,
        *,
        json_schema: dict[str, object],
        timeout_s: float = 300.0,
    ) -> dict[str, object]:
        executable = resolve_executable()
        attempt_prompt = prompt
        last_error = ""
        for attempt in range(2):
            text = self._call(executable, attempt_prompt, json_schema, timeout_s)
            try:
                data = self._decode(text)
            except (json.JSONDecodeError, AuditBackendError) as exc:
                last_error = f"invalid JSON ({exc})"
            else:
                problems = schema_errors(data, json_schema)
                if not problems:
                    assert isinstance(data, dict)
                    return {str(k): v for k, v in data.items()}
                last_error = "; ".join(problems[:5])
            if attempt == 0:
                attempt_prompt = (
                    f"{prompt}\n\nYour previous answer was rejected: {last_error}\n"
                    "Answer again with one JSON object that follows the schema exactly."
                )
        raise AuditBackendError(f"Claude Code returned unusable output twice: {last_error}")

    def _call(
        self, executable: str, prompt: str, json_schema: dict[str, object], timeout_s: float
    ) -> object:
        env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV}
        argv = build_argv(executable, json_schema, self.model)
        with tempfile.TemporaryDirectory(prefix="speakloop-audit-") as workdir:
            try:
                proc = subprocess.run(
                    argv,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    cwd=workdir,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise AuditBackendError(f"Claude Code timed out after {timeout_s:.0f}s") from exc
            except OSError as exc:
                raise AuditBackendError(f"cannot run Claude Code: {exc.strerror or exc}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().replace("\n", " ")[:200]
            raise AuditBackendError(f"Claude Code exited with {proc.returncode}: {detail}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AuditBackendError("Claude Code printed an unreadable JSON envelope") from exc
        if not isinstance(envelope, dict):
            raise AuditBackendError("Claude Code envelope is not a JSON object")
        if envelope.get("is_error"):
            detail = str(envelope.get("result", ""))[:200]
            raise AuditBackendError(f"Claude Code reported an error: {detail}")
        return envelope

    @staticmethod
    def _decode(envelope: object) -> object:
        assert isinstance(envelope, dict)
        structured = envelope.get("structured_output")
        if structured is not None:
            return structured
        result = envelope.get("result")
        if not isinstance(result, str):
            raise AuditBackendError("envelope has no result")
        return extract_json_text(result)
