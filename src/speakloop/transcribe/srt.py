"""Strict parser for the SRT and WebVTT subtitle files that Buzz writes."""

import re
from dataclasses import dataclass

__all__ = ["Cue", "SubtitleParseError", "parse_srt", "parse_subtitles", "parse_vtt"]


class SubtitleParseError(ValueError):
    """Raised when subtitle text is malformed."""


@dataclass(frozen=True)
class Cue:
    """One subtitle cue. Times are seconds from the start of the audio."""

    start: float
    end: float
    text: str


# SRT uses `HH:MM:SS,mmm`; VTT uses `HH:MM:SS.mmm` or `MM:SS.mmm`. Accept both separators.
_TS = r"(?:(\d{1,3}):)?(\d{2}):(\d{2})[,.](\d{3})"
_TIMING_RE = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}(?:\s+.*)?$")


def _seconds(h: str | None, m: str, s: str, ms: str) -> float:
    if int(m) > 59 or int(s) > 59:
        raise SubtitleParseError(f"invalid timestamp component in {m}:{s}")
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _blocks(text: str) -> list[list[str]]:
    normalized = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in normalized.split("\n"):
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_blocks(blocks: list[list[str]]) -> list[Cue]:
    cues: list[Cue] = []
    for block in blocks:
        timing_idx = next((i for i, line in enumerate(block) if "-->" in line), None)
        if timing_idx is None:
            raise SubtitleParseError(f"cue block without a timing line: {block[0]!r}")
        if timing_idx > 1:
            raise SubtitleParseError(f"unexpected lines before the timing line: {block[0]!r}")
        match = _TIMING_RE.match(block[timing_idx])
        if match is None:
            raise SubtitleParseError(f"malformed timing line: {block[timing_idx]!r}")
        g = match.groups()
        start = _seconds(*g[0:4])
        end = _seconds(*g[4:8])
        if end < start:
            raise SubtitleParseError(f"cue ends before it starts: {block[timing_idx]!r}")
        text = " ".join(line.strip() for line in block[timing_idx + 1 :] if line.strip())
        if text:  # Empty cues carry no information.
            cues.append(Cue(start=start, end=end, text=text))
    return cues


def parse_srt(text: str) -> list[Cue]:
    """Parse SRT text. Multi-line cues are joined with a single space; empty cues are dropped."""
    return _parse_blocks(_blocks(text))


def parse_vtt(text: str) -> list[Cue]:
    """Parse WebVTT text. Requires the `WEBVTT` header; NOTE/STYLE/REGION blocks are skipped."""
    blocks = _blocks(text)
    if not blocks or not blocks[0][0].startswith("WEBVTT"):
        raise SubtitleParseError("missing WEBVTT header")
    rest = [b for b in blocks[1:] if not b[0].startswith(("NOTE", "STYLE", "REGION"))]
    # A header block directly followed by a cue (no blank line) is malformed but harmless.
    if len(blocks[0]) > 1 and "-->" in blocks[0][1]:
        rest.insert(0, blocks[0][1:])
    return _parse_blocks(rest)


def parse_subtitles(text: str) -> list[Cue]:
    """Parse SRT or WebVTT text, detected from the header."""
    if text.lstrip("﻿").lstrip().startswith("WEBVTT"):
        return parse_vtt(text)
    return parse_srt(text)
