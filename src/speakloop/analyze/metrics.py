"""Deterministic speaking metrics.

Everything here is a pure function of a `Transcript` and a `Session`: no I/O, no clock, no
model calls. The same input always yields the same `Metrics`. Several metrics are heuristics
over text and timestamps; each docstring states what the heuristic cannot see.
"""

import math
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from speakloop.models import (
    Evidence,
    FdeMetrics,
    Metrics,
    Pause,
    Session,
    Track,
    TrackId,
    Transcript,
    Word,
)

MATTR_WINDOW = 50
MIN_LAST_WINDOW_S = 15.0
MAX_LATENCY_S = 30.0
SENTENCE_GAP_S = 0.8
NEXT_STEPS_TAIL_S = 60.0

_EDGE_PUNCTUATION = "\"'.,;:!?()[]{}<>\u2026-\u2014\u2013\u201c\u201d\u2018\u2019`*_/\\"
_SENTENCE_END_STRIP = "\"')]}\u201d\u2019*_"
_CUT_OFF_SUFFIXES = ("-", "\u2014", "\u2013")

REPETITION_ALLOWLIST: frozenset[str] = frozenset({"had", "that"})

RISKY_PHRASES: tuple[str, ...] = (
    "definitely",
    "100%",
    "100 percent",
    "no problem",
    "guarantee",
    "for sure",
    "absolutely",
    "i promise",
    "that's easy",
    "trivial",
)

NEXT_STEP_PHRASES: tuple[str, ...] = (
    "next steps",
    "next step",
    "follow up",
    "i'll send",
    "i will send",
    "let's schedule",
    "by tomorrow",
    "action items",
    "i'll get back",
)


@dataclass(frozen=True)
class FillerLexicon:
    """Lowercase filler entries: single tokens ("um") and phrases ("you know").

    Limits: matching is purely lexical. "kind of" and "sort of" are sometimes legitimate
    ("a kind of cache"), so they inflate the count a little. "like" is excluded from the
    default set because it is far too ambiguous ("I like Python"); add it with `with_entries`
    if you want it counted anyway.
    """

    entries: frozenset[str]

    @property
    def max_words(self) -> int:
        """Number of tokens of the longest entry (0 for an empty lexicon)."""
        return max((len(e.split()) for e in self.entries), default=0)

    def with_entries(self, *extra: str) -> "FillerLexicon":
        """Return a new lexicon with the extra entries added (normalized to lowercase)."""
        added = {" ".join(e.lower().split()) for e in extra if e.strip()}
        return FillerLexicon(entries=self.entries | added)


DEFAULT_FILLERS = FillerLexicon(
    entries=frozenset(
        {
            "um",
            "uh",
            "erm",
            "er",
            "ah",
            "hmm",
            "mm",
            "you know",
            "i mean",
            "sort of",
            "kind of",
        }
    )
)


def normalize_token(text: str) -> str:
    """Lowercase a word and strip surrounding punctuation, keeping internal apostrophes.

    Curly apostrophes become straight ones. Symbols such as "%" are kept ("100%"). May
    return an empty string for punctuation-only words.
    """
    folded = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    return folded.strip(_EDGE_PUNCTUATION + " \t\n")


def is_false_start(text: str) -> bool:
    """True if the raw word text ends with a cut-off marker ("wh-", "we—")."""
    return text.strip().endswith(_CUT_OFF_SUFFIXES)


def find_phrases(tokens: Sequence[str], phrases: Iterable[str]) -> list[tuple[int, int, str]]:
    """Find non-overlapping phrase matches, scanning left to right, longest phrase first.

    Returns `(start_index, end_index_exclusive, phrase)` tuples. Phrases are compared with
    the already normalized tokens, so "you know" matches the tokens ["you", "know"].
    """
    table = {" ".join(p.lower().split()) for p in phrases if p.strip()}
    longest = max((len(p.split()) for p in table), default=0)
    found: list[tuple[int, int, str]] = []
    i = 0
    while i < len(tokens):
        for n in range(min(longest, len(tokens) - i), 0, -1):
            candidate = " ".join(tokens[i : i + n])
            if candidate in table:
                found.append((i, i + n, candidate))
                i += n
                break
        else:
            i += 1
    return found


def count_fillers(tokens: Sequence[str], lexicon: FillerLexicon) -> tuple[dict[str, int], set[int]]:
    """Count fillers; return `(counts, indices of tokens that belong to a filler)`.

    Counts are ordered by descending count, then alphabetically.
    """
    counts: Counter[str] = Counter()
    indices: set[int] = set()
    for start, end, phrase in find_phrases(tokens, lexicon.entries):
        counts[phrase] += 1
        indices.update(range(start, end))
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return ordered, indices


def count_repetitions(
    tokens: Sequence[str],
    ignore: Iterable[int] = (),
    allowlist: frozenset[str] = REPETITION_ALLOWLIST,
) -> int:
    """Count immediate repetitions of the same token ("I I", "the the").

    A run "a a a" counts 2. Tokens at indices in `ignore` (fillers, so "um um" is not
    counted twice) and allowlisted legitimate doubles ("had had", "that that") are skipped.
    Heuristic: it also flags deliberate emphasis ("very very") and misses repeated phrases
    ("I think I think").
    """
    skipped = set(ignore)
    total = 0
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1] and tokens[i] not in allowlist:
            if i in skipped or (i - 1) in skipped:
                continue
            total += 1
    return total


def count_false_starts(words: Iterable[Word]) -> int:
    """Count words ending in "-" or "—", which Whisper uses for cut-off words ("wh-").

    Heuristic: it depends on the transcription backend marking cut-offs; a backend that
    silently drops or completes them yields 0. A normal hyphen at the end of a word is rare.
    """
    return sum(1 for w in words if is_false_start(w.text))


def mattr(tokens: Sequence[str], window: int = MATTR_WINDOW) -> float | None:
    """Moving-average type-token ratio: mean of unique/window over every window of tokens.

    Returns None when there are fewer than `window` tokens. Callers pass non-filler tokens.
    Limit: it measures lexical variety only, not richness or correctness.
    """
    if window < 1 or len(tokens) < window:
        return None
    counts: Counter[str] = Counter(tokens[:window])
    total = len(counts)
    for i in range(window, len(tokens)):
        leaving = tokens[i - window]
        counts[leaving] -= 1
        if counts[leaving] == 0:
            del counts[leaving]
        counts[tokens[i]] += 1
        total += len(counts)
    return total / ((len(tokens) - window + 1) * window)


def wpm_windows(
    word_starts: Sequence[float],
    first_start: float,
    duration_s: float,
    window_s: float = 60.0,
) -> tuple[float, ...]:
    """Words per minute in consecutive windows of `window_s` from `first_start`.

    A word belongs to the window in which it starts. The last partial window uses its real
    length and is dropped when shorter than 15 s (too noisy), so a recording shorter than
    15 s gets no windows. Silent stretches count: this is speech rate with pauses included.
    """
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    if duration_s <= 0:
        return ()
    total = math.ceil(duration_s / window_s)
    last_len = duration_s - (total - 1) * window_s
    kept = total - 1 if last_len < MIN_LAST_WINDOW_S and last_len < window_s else total
    counts = [0] * total
    for start in word_starts:
        index = min(max(int((start - first_start) // window_s), 0), total - 1)
        counts[index] += 1
    result: list[float] = []
    for i in range(kept):
        length = window_s if i < total - 1 else last_len
        result.append(counts[i] / (length / 60.0))
    return tuple(result)


def coefficient_of_variation(values: Sequence[float]) -> float | None:
    """Population standard deviation divided by the mean; None if < 2 values or mean 0."""
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    if mean == 0:
        return None
    return statistics.pstdev(values) / mean


def long_pauses(
    speaker_words: Sequence[Word],
    interlocutor_words: Sequence[Word],
    threshold_s: float,
) -> tuple[Pause, ...]:
    """Gaps between consecutive speaker words that are >= `threshold_s`.

    A gap overlapped by any interlocutor word is skipped: the speaker was listening (a turn
    change), not hesitating. Limit: if the interlocutor mumbles and is not transcribed, the
    silence still counts as a pause.
    """
    ordered = sorted(speaker_words, key=lambda w: w.start)
    found: list[Pause] = []
    for prev, nxt in pairwise(ordered):
        if nxt.start - prev.end < threshold_s:
            continue
        if any(o.start < nxt.start and o.end > prev.end for o in interlocutor_words):
            continue
        found.append(Pause(start=prev.end, end=nxt.start))
    return tuple(found)


def response_latencies(
    speaker_words: Sequence[Word], interlocutor_words: Sequence[Word]
) -> tuple[float, ...]:
    """Silence between the end of an interlocutor turn and the next speaker word.

    A turn is a run of interlocutor words with no speaker word between them (by start
    time). Latency = first following speaker word start - latest interlocutor word end in
    the run. Negative values (overlap) are ignored; values above 30 s are capped at 30.
    Limit: a speaker backchannel ("mm-hm") in the middle of a turn splits it.
    """
    merged = sorted(
        [(w.start, 0, w) for w in interlocutor_words] + [(w.start, 1, w) for w in speaker_words],
        key=lambda item: (item[0], item[1]),
    )
    latencies: list[float] = []
    turn_end: float | None = None
    for _, kind, w in merged:
        if kind == 0:
            turn_end = w.end if turn_end is None else max(turn_end, w.end)
        elif turn_end is not None:
            latency = w.start - turn_end
            if latency >= 0:
                latencies.append(min(latency, MAX_LATENCY_S))
            turn_end = None
    return tuple(latencies)


def talk_ratio(speaker_words: Iterable[Word], interlocutor_words: Iterable[Word]) -> float | None:
    """Speaker speaking time / total speaking time (sum of word durations).

    None when nobody spoke. Limit: word timestamps from the transcriber approximate speaking
    time; silences inside long words are counted as speech.
    """
    mine = sum(w.end - w.start for w in speaker_words)
    theirs = sum(w.end - w.start for w in interlocutor_words)
    if mine + theirs <= 0:
        return None
    return mine / (mine + theirs)


def split_sentences(words: Sequence[Word], gap_s: float = SENTENCE_GAP_S) -> list[list[Word]]:
    """Split ordered words into sentences.

    A sentence ends after a word whose raw text ends in ".", "?" or "!" (trailing quotes and
    brackets ignored), or when the next word starts >= `gap_s` after this one ends. Limit:
    relies on the transcriber's punctuation.
    """
    sentences: list[list[Word]] = []
    current: list[Word] = []
    for i, w in enumerate(words):
        current.append(w)
        stripped = w.text.strip().rstrip(_SENTENCE_END_STRIP)
        ends = stripped.endswith((".", "?", "!"))
        has_gap = i + 1 < len(words) and words[i + 1].start - w.end >= gap_s
        if ends or has_gap:
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return sentences


def clarifying_questions_before(speaker_words: Sequence[Word], proposal_time_s: float) -> int:
    """Count speaker sentences ending in "?" that end strictly before `proposal_time_s`.

    Limit: any question counts, including rhetorical ones or "does that make sense?", and
    questions without a final "?" (missing punctuation) are missed.
    """
    count = 0
    for sentence in split_sentences(speaker_words):
        last = sentence[-1]
        closed = last.text.strip().rstrip(_SENTENCE_END_STRIP)
        if closed.endswith("?") and last.end < proposal_time_s:
            count += 1
    return count


def risky_commitments(
    speaker_words: Sequence[Word],
    tokens: Sequence[str],
    speaker_track: TrackId,
    phrases: Iterable[str] = RISKY_PHRASES,
) -> tuple[Evidence, ...]:
    """Find over-promising phrases; `tokens[i]` must be the normalized `speaker_words[i]`.

    Each match becomes an `Evidence` whose quote is the matched words exactly as written in
    the transcript, joined with spaces, with start/end taken from those words. Limit: purely
    lexical, so "I can't guarantee" or "not trivial" are flagged too; the audit judges context.
    """
    found: list[Evidence] = []
    for start, end, _ in find_phrases(tokens, phrases):
        matched = speaker_words[start:end]
        quote = " ".join(w.text.strip() for w in matched)
        found.append(
            Evidence(quote=quote, start=matched[0].start, end=matched[-1].end, track=speaker_track)
        )
    return tuple(found)


def closed_with_next_steps(
    speaker_words: Sequence[Word],
    tokens: Sequence[str],
    phrases: Iterable[str] = NEXT_STEP_PHRASES,
    tail_s: float = NEXT_STEPS_TAIL_S,
) -> bool | None:
    """True if a next-step phrase appears in the speaker's last `tail_s` seconds of speech.

    The tail is every speaker word starting at or after (last word end - tail_s). None if the
    speaker said nothing. Heuristic: wording only; a closing that proposes a concrete next
    step in other words is missed, and the audit may refine it later.
    """
    if not speaker_words:
        return None
    cutoff = max(w.end for w in speaker_words) - tail_s
    tail = [t for w, t in zip(speaker_words, tokens, strict=True) if w.start >= cutoff]
    return bool(find_phrases(tail, phrases))


def _other_track(session: Session, speaker: Track) -> Track | None:
    for track in session.tracks:
        if track.id != speaker.id:
            return track
    return None


def compute_metrics(
    transcript: Transcript,
    session: Session,
    *,
    long_pause_threshold_s: float = 2.0,
    window_s: float = 60.0,
    fillers: FillerLexicon | None = None,
    proposal_time_s: float | None = None,
) -> Metrics:
    """Compute all metrics for one session. Pure and deterministic.

    The speaker track is the session track with role "speaker"; the other track, if any, is
    the interlocutor. Words whose normalized text is empty (lone punctuation) are ignored.
    Definitions live in the helper functions of this module. `proposal_time_s` is the moment
    of the first proposal (marked later by the audit); without it the clarifying-question
    count is None.
    """
    if long_pause_threshold_s <= 0:
        raise ValueError("long_pause_threshold_s must be positive")
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    lexicon = fillers if fillers is not None else DEFAULT_FILLERS

    speaker = next(t for t in session.tracks if t.role == "speaker")
    other = _other_track(session, speaker)
    words = [w for w in transcript.words(speaker.id) if normalize_token(w.text)]
    tokens = [normalize_token(w.text) for w in words]
    other_words = (
        [w for w in transcript.words(other.id) if normalize_token(w.text)] if other else []
    )

    word_count = len(words)
    first_start = words[0].start if words else 0.0
    duration = max(w.end for w in words) - first_start if words else 0.0
    wpm_mean = word_count / (duration / 60.0) if duration > 0 else 0.0
    windows = wpm_windows([w.start for w in words], first_start, duration, window_s)

    filler_counts, filler_idx = count_fillers(tokens, lexicon)
    content = [t for i, t in enumerate(tokens) if i not in filler_idx]

    fde = FdeMetrics(
        clarifying_questions_before_proposal=(
            clarifying_questions_before(words, proposal_time_s)
            if proposal_time_s is not None
            else None
        ),
        talk_ratio=talk_ratio(words, other_words) if other is not None else None,
        risky_commitments=risky_commitments(words, tokens, speaker.id),
        closed_with_next_steps=closed_with_next_steps(words, tokens),
    )
    return Metrics(
        session_id=session.id,
        speaker_track=speaker.id,
        duration_s=duration,
        word_count=word_count,
        wpm_mean=wpm_mean,
        wpm_windows=windows,
        wpm_cv=coefficient_of_variation(windows),
        long_pause_threshold_s=long_pause_threshold_s,
        long_pauses=long_pauses(words, other_words, long_pause_threshold_s),
        filler_counts=filler_counts,
        fillers_per_100w=sum(filler_counts.values()) / word_count * 100 if word_count else 0.0,
        repetitions=count_repetitions(tokens, filler_idx),
        false_starts=count_false_starts(words),
        mattr=mattr(content),
        response_latencies_s=response_latencies(words, other_words) if other is not None else None,
        fde=fde,
    )
