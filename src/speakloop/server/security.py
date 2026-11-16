"""Protections for a local-only server: Host allow-list and same-origin writes."""

from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def hostname_of(host_header: str) -> str:
    """Host name part of a Host header value (port and IPv6 brackets removed)."""
    value = host_header.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def install_security(app: FastAPI, *, extra_origins: Iterable[str] = ()) -> None:
    """Reject foreign Host headers (DNS rebinding) and cross-origin state-changing requests."""
    allowed_origins = {o.rstrip("/").lower() for o in extra_origins}

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = request.headers.get("host", "")
        if hostname_of(host) not in ALLOWED_HOSTS:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None:
                parts = urlsplit(origin)
                same = parts.scheme == "http" and parts.netloc.lower() == host.strip().lower()
                if not same and origin.rstrip("/").lower() not in allowed_origins:
                    return JSONResponse({"detail": "forbidden origin"}, status_code=403)
        return await call_next(request)
