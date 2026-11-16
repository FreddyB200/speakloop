"""Interface for AI audit backends.

The only planned backend is Claude Code headless (`claude -p`) through the user's own
subscription. API keys and paid API backends are never used.
"""

from typing import Protocol


class AuditBackendError(Exception):
    """Raised when an audit backend fails or returns unusable output."""


class AuditBackend(Protocol):
    name: str

    def complete_json(
        self,
        prompt: str,
        *,
        json_schema: dict[str, object],
        timeout_s: float = 300.0,
    ) -> dict[str, object]: ...
