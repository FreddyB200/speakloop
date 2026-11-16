"""Verify model quotes against the speaker track and compute timings from transcript words.

A quote is matched on normalized tokens (case, quote style, punctuation and whitespace are
ignored). Timings and the stored quote text always come from the matched transcript words,
never from the model's text.
"""

import re
import unicodedata
from dataclasses import dataclass

from speakloop.audit.schema import RawAudit, RawFinding
from speakloop.models import Evidence, TrackId, Transcript, Word

_APOSTROPHE_CODES = (0x2018, 0x2019, 0x201A, 0x201B, 0x2032, 0x02BC, 0x00B4)
_APOSTROPHES = "'`" + "".join(chr(c) for c in _APOSTROPHE_CODES)
_NON_TOKEN = re.compile(r"[^\w]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Normalize text into comparable tokens (lowercase, no apostrophes, no punctuation)."""
    folded = unicodedata.normalize("NFKC", text).lower()
    for char in _APOSTROPHES:
        folded = folded.replace(char, "")
    return [t for t in _NON_TOKEN.split(folded.replace("_", " ")) if t]


def locate_quote(quote: str, words: tuple[Word, ...]) -> tuple[Word, ...] | None:
    """Return the run of consecutive transcript words matching the quote, or None."""
    wanted = tokenize(quote)
    if not wanted:
        return None
    tokens: list[str] = []
    owner: list[int] = []
    for index, word in enumerate(words):
        for token in tokenize(word.text):
            tokens.append(token)
            owner.append(index)
    size = len(wanted)
    for i in range(len(tokens) - size + 1):
        if tokens[i : i + size] == wanted:
            return words[owner[i] : owner[i + size - 1] + 1]
    return None


def _evidence(matched: tuple[Word, ...], track: TrackId) -> Evidence:
    return Evidence(
        start=matched[0].start,
        end=max(w.end for w in matched),
        quote=" ".join(w.text.strip() for w in matched),
        track=track,
    )


@dataclass(frozen=True)
class VerifiedFinding:
    raw: RawFinding
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class VerificationResult:
    findings: tuple[VerifiedFinding, ...]
    proposal_time_s: float | None
    dropped_quotes: int
    discarded_findings: int


def verify_audit(
    audit: RawAudit, transcript: Transcript, speaker_track: TrackId
) -> VerificationResult:
    """Keep only findings with at least one quote found in the speaker track."""
    words = transcript.words(speaker_track)
    kept: list[VerifiedFinding] = []
    dropped = 0
    discarded = 0
    for finding in audit.findings:
        evidence: list[Evidence] = []
        for quote in finding.quotes:
            matched = locate_quote(quote, words)
            if matched is None:
                dropped += 1
            else:
                evidence.append(_evidence(matched, speaker_track))
        if evidence:
            kept.append(VerifiedFinding(raw=finding, evidence=tuple(evidence)))
        else:
            discarded += 1
    proposal: float | None = None
    if audit.first_proposal_quote:
        matched = locate_quote(audit.first_proposal_quote, words)
        if matched is not None:
            proposal = matched[0].start
    return VerificationResult(tuple(kept), proposal, dropped, discarded)
