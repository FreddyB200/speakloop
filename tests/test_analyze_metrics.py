"""Tests for the deterministic metrics engine (synthetic transcripts only)."""

from datetime import UTC, datetime

import pytest

from speakloop.analyze import DEFAULT_FILLERS, FillerLexicon, compute_metrics
from speakloop.analyze.metrics import (
    closed_with_next_steps,
    coefficient_of_variation,
    count_false_starts,
    count_fillers,
    count_repetitions,
    find_phrases,
    long_pauses,
    mattr,
    normalize_token,
    response_latencies,
    split_sentences,
    talk_ratio,
    wpm_windows,
)
from speakloop.models import (
    Metrics,
    Segment,
    Session,
    SessionKind,
    Track,
    TrackId,
    Transcript,
    Word,
)

SID = "20260101-093000-a1b2"


def w(text: str, start: float, end: float, track: TrackId = "mic") -> Word:
    return Word(text=text, start=start, end=end, track=track)


def say(
    text: str, start: float, track: TrackId = "mic", dur: float = 0.5, gap: float = 0.0
) -> list[Word]:
    """Build words from a string: each is `dur` long and `gap` apart."""
    out: list[Word] = []
    t = start
    for token in text.split():
        out.append(w(token, t, t + dur, track))
        t += dur + gap
    return out


def transcript(*groups: list[Word]) -> Transcript:
    segments = []
    for words in groups:
        if not words:
            continue
        segments.append(
            Segment(
                start=words[0].start,
                end=max(x.end for x in words),
                text=" ".join(x.text for x in words),
                track=words[0].track,
                words=tuple(words),
            )
        )
    return Transcript(
        session_id=SID, language="en", backend="t", model="m", prompt=None, segments=tuple(segments)
    )


def session(*, with_other: bool = True, speaker: TrackId = "mic") -> Session:
    other: TrackId = "system" if speaker == "mic" else "mic"
    tracks = [Track(id=speaker, role="speaker")]
    if with_other:
        tracks.append(Track(id=other, role="interlocutor"))
    return Session(
        id=SID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        kind=SessionKind.FREE,
        tracks=tuple(tracks),
    )


def solo(*groups: list[Word], **kwargs: float | None) -> Metrics:
    return compute_metrics(transcript(*groups), session(with_other=False), **kwargs)  # type: ignore[arg-type]


# ---------- helpers ----------


def test_normalize_token() -> None:
    assert normalize_token("Hello,") == "hello"
    assert normalize_token('"Don\'t!"') == "don't"
    assert normalize_token("don\u2019t") == "don't"
    assert normalize_token("100%.") == "100%"
    assert normalize_token("wh-") == "wh"
    assert normalize_token("—") == ""


def test_find_phrases_longest_first_and_non_overlapping() -> None:
    tokens = ["you", "know", "i", "mean", "sort", "of", "um"]
    found = find_phrases(tokens, ["um", "you know", "i mean", "sort of", "know i mean"])
    assert found == [(0, 2, "you know"), (2, 4, "i mean"), (4, 6, "sort of"), (6, 7, "um")]
    # The longer phrase wins at the same position.
    assert find_phrases(["you", "know", "i"], ["you", "you know"]) == [(0, 2, "you know")]


def test_find_phrases_empty() -> None:
    assert find_phrases([], ["um"]) == []
    assert find_phrases(["a"], []) == []


def test_filler_overlap_counts_once() -> None:
    tokens = ["you", "know", "i", "mean"]
    counts, idx = count_fillers(tokens, FillerLexicon(frozenset({"you know", "know i", "i mean"})))
    # "know i" overlaps the already matched "you know" and is not counted.
    assert counts == {"i mean": 1, "you know": 1}
    assert idx == {0, 1, 2, 3}


def test_default_lexicon_and_like_extension() -> None:
    assert "like" not in DEFAULT_FILLERS.entries
    expected = {"um", "uh", "erm", "er", "ah", "hmm", "mm", "you know", "i mean"}
    assert expected <= DEFAULT_FILLERS.entries
    extended = DEFAULT_FILLERS.with_entries("Like", "  you   see ")
    assert {"like", "you see"} <= extended.entries
    assert extended.max_words == 2
    assert FillerLexicon(frozenset()).max_words == 0
    counts, _ = count_fillers(["i", "like", "it"], extended)
    assert counts == {"like": 1}


def test_filler_counts_order() -> None:
    counts, _ = count_fillers(["uh", "um", "um", "er"], DEFAULT_FILLERS)
    assert list(counts.items()) == [("um", 2), ("er", 1), ("uh", 1)]


def test_repetitions() -> None:
    assert count_repetitions(["i", "i", "think", "the", "the", "the"]) == 3
    assert count_repetitions(["he", "had", "had", "said", "that", "that", "is"]) == 0
    assert count_repetitions([]) == 0
    # Filler repeats are not repetitions.
    assert count_repetitions(["um", "um", "ok"], ignore={0, 1}) == 0


def test_false_starts() -> None:
    words = [w("wh-", 0, 0.2), w("what", 0.3, 0.5), w("we—", 0.6, 0.8), w("a-b", 1, 1.2)]
    assert count_false_starts(words) == 2
    assert count_false_starts([]) == 0


def test_mattr_threshold_and_value() -> None:
    assert mattr(["a"] * 49) is None
    assert mattr([]) is None
    assert mattr(["a"] * 50) == pytest.approx(1 / 50)
    assert mattr([str(i) for i in range(50)]) == 1.0
    # Window [1:51] = tokens 1..49 plus "0": still 50 unique.
    assert mattr([str(i) for i in range(50)] + ["0"]) == 1.0
    # Window [1:51] = tokens 1..49 plus "5": 49 unique.
    assert mattr([str(i) for i in range(50)] + ["5"]) == pytest.approx((50 + 49) / (2 * 50))


def test_wpm_windows_boundaries() -> None:
    # 120 s duration, 60 s windows -> exactly two full windows.
    starts = [0.0, 10.0, 59.5, 60.0, 119.0]
    assert wpm_windows(starts, 0.0, 120.0, 60.0) == (3.0, 2.0)
    # A word starting exactly on the boundary belongs to the next window.
    assert wpm_windows([60.0], 0.0, 120.0, 60.0) == (0.0, 1.0)


def test_wpm_windows_partial_last() -> None:
    # 75 s: last window is 15 s long (kept, not shorter than 15): 5 words -> 20 wpm.
    assert wpm_windows([0.0, 1.0, 62.0, 63.0, 64.0, 65.0, 66.0], 0.0, 75.0, 60.0) == (2.0, 20.0)
    # 74.5 s: last window is 14.5 s: dropped.
    assert wpm_windows([0.0, 70.0], 0.0, 74.5, 60.0) == (1.0,)
    # Under 15 s overall -> nothing.
    assert wpm_windows([0.0], 0.0, 10.0, 60.0) == ()
    assert wpm_windows([], 0.0, 0.0, 60.0) == ()
    with pytest.raises(ValueError, match="window_s"):
        wpm_windows([0.0], 0.0, 10.0, 0)


def test_wpm_windows_offset_start() -> None:
    assert wpm_windows([5.0, 6.0], 5.0, 60.0, 60.0) == (2.0,)


def test_coefficient_of_variation() -> None:
    assert coefficient_of_variation([10.0]) is None
    assert coefficient_of_variation([]) is None
    assert coefficient_of_variation([0.0, 0.0]) is None
    assert coefficient_of_variation([10.0, 10.0]) == 0.0
    assert coefficient_of_variation([10.0, 30.0]) == pytest.approx(0.5)


def test_long_pauses_threshold_inclusive() -> None:
    words = [w("a", 0, 1), w("b", 3, 4), w("c", 5.5, 6)]
    pauses = long_pauses(words, [], 2.0)
    assert [(p.start, p.end) for p in pauses] == [(1, 3)]
    assert long_pauses([w("a", 0, 1)], [], 2.0) == ()


def test_long_pause_ignores_interlocutor_turn() -> None:
    speaker = [w("a", 0, 1), w("b", 10, 11), w("c", 14, 15)]
    other = [w("hey", 2, 3, "system")]
    pauses = long_pauses(speaker, other, 2.0)
    assert [(p.start, p.end) for p in pauses] == [(11, 14)]


def test_response_latencies() -> None:
    speaker = [w("a", 5, 5.5), w("b", 20, 20.5), w("c", 100, 100.5), w("d", 106, 106.5)]
    other = [w("q", 1, 2, "system"), w("r", 3, 4, "system"), w("s", 15, 16, "system")]
    other += [w("t", 50, 51, "system"), w("u", 105, 106.2, "system")]
    # turn1 ends 4 -> speaker at 5: 1.0; turn2 ends 16 -> 20: 4.0;
    # turn3 (50-51) -> 100: 49 capped to 30; turn4 ends 106.2 -> 106 negative: ignored.
    assert response_latencies(speaker, other) == (1.0, 4.0, 30.0)


def test_response_latencies_trailing_turn_and_none() -> None:
    assert response_latencies([w("a", 0, 1)], [w("q", 2, 3, "system")]) == ()
    assert response_latencies([], []) == ()


def test_talk_ratio() -> None:
    assert talk_ratio([w("a", 0, 3)], [w("b", 3, 4, "system")]) == 0.75
    assert talk_ratio([], []) is None
    assert talk_ratio([w("a", 0, 1)], []) == 1.0


def test_split_sentences() -> None:
    words = [
        w("Hi.", 0, 0.5),
        w("Can", 0.6, 1),
        w("you", 1, 1.5),
        w('help?"', 1.5, 2),
        w("so", 3, 3.5),
        w("yes", 3.5, 4),
    ]
    sentences = split_sentences(words)
    assert [[x.text for x in s] for s in sentences] == [
        ["Hi."],
        ["Can", "you", 'help?"'],
        ["so", "yes"],
    ]
    assert split_sentences([]) == []


def test_split_sentences_on_gap_only() -> None:
    words = [w("a", 0, 1), w("b", 1.75, 2), w("c", 2.8125, 3)]
    assert [len(s) for s in split_sentences(words)] == [2, 1]


def test_closed_with_next_steps_helper() -> None:
    assert closed_with_next_steps([], []) is None
    words = [w("next", 0, 1), w("steps", 1, 2), w("ok", 100, 101)]
    tokens = ["next", "steps", "ok"]
    # Last speech ends at 101; cutoff 41: "next steps" is out of the tail.
    assert closed_with_next_steps(words, tokens) is False
    assert closed_with_next_steps(words, tokens, tail_s=200) is True


# ---------- compute_metrics ----------


def test_empty_transcript() -> None:
    m = compute_metrics(transcript(), session())
    assert m.speaker_track == "mic"
    assert (m.duration_s, m.word_count, m.wpm_mean) == (0.0, 0, 0.0)
    assert m.wpm_windows == ()
    assert m.wpm_cv is None
    assert m.long_pauses == ()
    assert m.filler_counts == {}
    assert m.fillers_per_100w == 0.0
    assert (m.repetitions, m.false_starts) == (0, 0)
    assert m.mattr is None
    assert m.response_latencies_s == ()
    assert m.fde is not None
    assert m.fde.talk_ratio is None
    assert m.fde.closed_with_next_steps is None
    assert m.fde.risky_commitments == ()
    assert m.fde.clarifying_questions_before_proposal is None


def test_single_word() -> None:
    m = solo([w("Hello", 2.0, 2.5)])
    assert m.word_count == 1
    assert m.duration_s == 0.5
    assert m.wpm_mean == pytest.approx(120.0)
    assert m.wpm_windows == ()
    assert m.wpm_cv is None
    assert m.response_latencies_s is None
    assert m.fde is not None
    assert m.fde.talk_ratio is None
    assert m.fde.closed_with_next_steps is False


def test_zero_duration_word() -> None:
    m = solo([w("Hi", 1.0, 1.0)])
    assert (m.duration_s, m.word_count, m.wpm_mean) == (0.0, 1, 0.0)


def test_one_track_only_core_values() -> None:
    m = solo(say("so um I I think you know the the plan wh- works", 10.0))
    assert m.word_count == 12
    assert m.duration_s == 6.0
    assert m.wpm_mean == pytest.approx(120.0)
    assert m.filler_counts == {"um": 1, "you know": 1}
    assert m.fillers_per_100w == pytest.approx(2 / 12 * 100)
    assert m.repetitions == 2
    assert m.false_starts == 1
    assert m.mattr is None
    assert m.response_latencies_s is None
    assert m.fde is not None
    assert m.fde.talk_ratio is None


def test_speaker_track_can_be_system() -> None:
    words = say("hello there", 0.0, track="system")
    m = compute_metrics(transcript(words), session(speaker="system"))
    assert m.speaker_track == "system"
    assert m.word_count == 2


def test_two_tracks_with_overlap() -> None:
    speaker = [w("Well", 5.0, 5.5), w("okay", 5.5, 6.0), w("then", 12.0, 12.5)]
    other = [w("So", 0.0, 1.0, "system"), w("tell", 1.0, 2.0, "system")]
    other += [w("me", 2.0, 5.2, "system"), w("more", 10.0, 10.5, "system")]
    m = compute_metrics(transcript(speaker, other), session())
    # Latency: first turn ends 5.2 but the speaker starts at 5.0 (overlap), so no latency
    # there; the turn at 10.0-10.5 is followed by the speaker at 12.0.
    assert m.response_latencies_s == (pytest.approx(1.5),)
    # Gap 6.0 -> 12.0 contains the interlocutor word at 10.0: not a hesitation.
    assert m.long_pauses == ()
    # Speaker time 1.5 s, interlocutor 1 + 1 + 3.2 + 0.5 = 5.7 s.
    assert m.fde is not None
    assert m.fde.talk_ratio == pytest.approx(1.5 / 7.2)


def test_pause_not_excluded_when_interlocutor_silent() -> None:
    speaker = [w("a", 0, 1), w("b", 4, 5)]
    other = [w("x", 20, 21, "system")]
    m = compute_metrics(transcript(speaker, other), session())
    assert [(p.start, p.end) for p in m.long_pauses] == [(1, 4)]
    assert m.long_pause_threshold_s == 2.0


def test_custom_threshold_and_validation() -> None:
    speaker = [w("a", 0, 1), w("b", 2, 3)]
    m = solo(speaker, long_pause_threshold_s=0.5)
    assert len(m.long_pauses) == 1
    assert m.long_pause_threshold_s == 0.5
    with pytest.raises(ValueError, match="long_pause_threshold_s"):
        compute_metrics(transcript(speaker), session(), long_pause_threshold_s=0)
    with pytest.raises(ValueError, match="window_s"):
        compute_metrics(transcript(speaker), session(), window_s=-1)


def test_window_boundaries_end_to_end() -> None:
    # One word per second for 120 s, starts 0..119: 60 words in each 60 s window.
    words = [w("word", float(i), i + 0.5) for i in range(120)]
    m = solo(words)
    assert m.duration_s == 119.5
    assert m.wpm_mean == pytest.approx(120 / (119.5 / 60))
    # Two windows: the second has real length 59.5 s.
    assert m.wpm_windows == (pytest.approx(60.0), pytest.approx(60 / (59.5 / 60)))
    assert m.wpm_cv is not None
    assert m.wpm_cv < 0.01


def test_wpm_cv_uneven_windows() -> None:
    words = [w("a", float(i), i + 0.5) for i in range(30)]  # 30 words in the first minute
    words += [w("b", 60.0 + i * 2, 60.5 + i * 2) for i in range(15)]  # 15 in the second
    words.append(w("end", 119.0, 120.0))  # 16th word of the second minute
    m = solo(words)
    assert m.duration_s == 120.0
    assert m.wpm_windows == (30.0, 16.0)
    assert m.wpm_cv == pytest.approx(7 / 23)


def test_fillers_phrase_overlap_and_case() -> None:
    m = solo(say("You know, I mean Um, kind of sort of ok", 0.0))
    assert m.filler_counts == {
        "i mean": 1,
        "kind of": 1,
        "sort of": 1,
        "um": 1,
        "you know": 1,
    }
    assert m.fillers_per_100w == pytest.approx(5 / 10 * 100)


def test_custom_lexicon_with_like() -> None:
    words = say("it was like um like good", 0.0)
    assert solo(words).filler_counts == {"um": 1}
    m2 = solo(words, fillers=DEFAULT_FILLERS.with_entries("like"))  # type: ignore[arg-type]
    assert m2.filler_counts == {"like": 2, "um": 1}


def test_mattr_below_and_above_threshold() -> None:
    few = say(" ".join(f"w{i}" for i in range(49)), 0.0)
    assert solo(few).mattr is None
    enough = say(" ".join(f"w{i}" for i in range(50)), 0.0)
    assert solo(enough).mattr == 1.0
    # Fillers are not tokens for MATTR: 49 distinct words plus a filler stays below 50.
    plus_filler = say(" ".join(f"w{i}" for i in range(49)) + " um", 0.0)
    assert solo(plus_filler).mattr is None


def test_risky_commitments_evidence() -> None:
    speaker = [
        w("We", 1.0, 1.2),
        w("can", 1.2, 1.4),
        w("Definitely,", 1.4, 2.0),
        w("do", 2.0, 2.1),
        w("it", 2.1, 2.3),
        w("100", 3.0, 3.3),
        w("percent.", 3.3, 3.9),
        w("It's", 5.0, 5.2),
        w("100%", 5.2, 5.8),
        w("fine", 5.8, 6.0),
        w("that's", 7.0, 7.2),
        w("easy,", 7.2, 7.6),
    ]
    m = solo(speaker)
    assert m.fde is not None
    got = [(e.quote, e.start, e.end, e.track) for e in m.fde.risky_commitments]
    assert got == [
        ("Definitely,", 1.4, 2.0, "mic"),
        ("100 percent.", 3.0, 3.9, "mic"),
        ("100%", 5.2, 5.8, "mic"),
        ("that's easy,", 7.0, 7.6, "mic"),
    ]


def test_risky_phrases_only_from_speaker() -> None:
    other = [w("definitely", 0.0, 1.0, "system")]
    speaker = [w("hello", 2.0, 2.5)]
    m = compute_metrics(transcript(speaker, other), session())
    assert m.fde is not None
    assert m.fde.risky_commitments == ()


def test_clarifying_questions_and_proposal_time() -> None:
    speaker = [
        w("What", 0.0, 0.5),
        w("is", 0.5, 1.0),
        w("the", 1.0, 1.5),
        w("goal?", 1.5, 2.0),
        w("Who", 2.2, 2.5),
        w("owns", 2.5, 3.0),
        w("it?", 3.0, 3.5),
        w("I", 10.0, 10.5),
        w("propose", 10.5, 11.0),
        w("X.", 11.0, 11.5),
        w("Right?", 12.0, 12.5),
    ]
    none_case = solo(speaker).fde
    assert none_case is not None
    assert none_case.clarifying_questions_before_proposal is None
    for proposal, expected in [(10.0, 2), (3.5, 1), (3.6, 2), (2.0, 0), (100.0, 3)]:
        fde = solo(speaker, proposal_time_s=proposal).fde
        assert fde is not None
        assert fde.clarifying_questions_before_proposal == expected, proposal


def test_closed_with_next_steps_end_to_end() -> None:
    early = say("let's schedule a call", 0.0)
    closing_ok = [w("ok", 200.0, 200.5)]
    fde = solo(early + closing_ok).fde
    assert fde is not None
    assert fde.closed_with_next_steps is False
    late = say("so the next steps are clear", 190.0)
    fde = solo(early + late).fde
    assert fde is not None
    assert fde.closed_with_next_steps is True
    fde = solo(say("I'll send a summary", 190.0)).fde
    assert fde is not None
    assert fde.closed_with_next_steps is True


def test_punctuation_only_words_ignored() -> None:
    m = solo([w("Hello", 0, 0.5), w("—", 0.5, 0.6), w("world", 0.6, 1.0)])
    assert m.word_count == 2
    # The standalone dash is ignored as a word but counts as an abandoned start.
    assert m.false_starts == 1
    assert solo([w("Hello", 0, 0.5), w("\u2014", 0.5, 0.6)]).false_starts == 0


def test_deterministic() -> None:
    words = say("um the the plan is definitely fine you know", 0.0)
    t, s = transcript(words), session()
    assert compute_metrics(t, s) == compute_metrics(t, s)


# ---------- standalone dashes and negation ----------


def _fs(text: str) -> int:
    return count_false_starts(say(text, 0.0))


def test_false_start_standalone_dash_between_words() -> None:
    assert _fs("I - I don't know") == 1
    assert _fs("the \u2014 like the bus") == 1
    assert _fs("We \u2013 which are provided") == 1
    assert _fs("I - I the - like the bus") == 2


def test_false_start_dash_not_between_words() -> None:
    assert _fs("tele -transported") == 0
    assert _fs("- I know") == 0
    assert _fs("I know -") == 0
    assert _fs("-") == 0
    assert _fs("I - - know") == 0


def test_false_start_not_counted_twice() -> None:
    assert _fs("wh- - what") == 1
    assert _fs("wh- what we - I") == 2


def test_false_start_standalone_dash_in_compute_metrics() -> None:
    m = solo(say("I - I don't know the - like the bus", 0.0))
    assert m.false_starts == 2
    assert m.word_count == 8


def _risky(text: str) -> list[str]:
    m = solo(say(text, 0.0))
    assert m.fde is not None
    return [e.quote for e in m.fde.risky_commitments]


def test_risky_skipped_after_negation() -> None:
    assert _risky("I can't guarantee that") == []
    assert _risky("it is not trivial") == []
    assert _risky("we never ship late but i promise") == ["i promise"]
    assert _risky("it isn't definitely safe") == []
    assert _risky("we don\u2019t guarantee it") == []
    assert _risky("no way it absolutely works") == []


def test_risky_negation_window_and_exemption() -> None:
    assert _risky("no problem") == ["no problem"]
    assert _risky("I can't say no problem") == ["no problem"]
    # Negation more than 3 tokens before the phrase does not cancel it.
    assert _risky("not that I think we can guarantee it") == ["guarantee"]
    assert _risky("I can guarantee that") == ["guarantee"]


def test_risky_negation_after_phrase_is_not_seen() -> None:
    assert _risky("I definitely can't promise") == ["definitely"]


def test_next_steps_ignores_negation() -> None:
    words = say("don't forget to follow up", 0.0)
    tokens = [normalize_token(x.text) for x in words]
    assert closed_with_next_steps(words, tokens) is True
