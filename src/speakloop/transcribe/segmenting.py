"""Group timed words into segments. Shared by every backend so segmentation is consistent."""

from collections.abc import Sequence

from speakloop.models import Segment, TrackId, Word

GAP_SPLIT_S = 0.8
_SENTENCE_END = (".", "?", "!", "…")
_CLOSERS = "\"')]}\N{RIGHT DOUBLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"


def ends_sentence(text: str) -> bool:
    """True if the token ends with sentence-final punctuation (ignoring closing quotes)."""
    return text.rstrip(_CLOSERS).endswith(_SENTENCE_END)


def build_segments(
    words: Sequence[Word], *, track: TrackId, gap_s: float = GAP_SPLIT_S
) -> tuple[Segment, ...]:
    """Split words (ordered by time) on gaps >= gap_s or after sentence-ending punctuation."""
    groups: list[list[Word]] = []
    for word in words:
        if groups:
            prev = groups[-1][-1]
            if not (word.start - prev.end >= gap_s or ends_sentence(prev.text)):
                groups[-1].append(word)
                continue
        groups.append([word])
    return tuple(
        Segment(
            start=min(w.start for w in group),
            end=max(w.end for w in group),
            text=" ".join(w.text for w in group),
            track=track,
            words=tuple(group),
        )
        for group in groups
    )
