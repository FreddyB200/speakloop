"""Local web server: JSON API plus the built frontend. See docs/ARCHITECTURE.md."""

from speakloop.server.app import create_app

__all__ = ["create_app"]
