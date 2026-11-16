from pathlib import Path

import pytest

from speakloop.transcribe.srt import (
    Cue,
    SubtitleParseError,
    parse_srt,
    parse_subtitles,
    parse_vtt,
)

FIX = Path(__file__).parent / "fixtures" / "transcribe"


def test_real_word_srt() -> None:
    cues = parse_srt((FIX / "buzz_words.srt").read_text())
    assert len(cues) == 18
    assert cues[0] == Cue(0.0, 0.42, "Hello,")
    assert cues[-1] == Cue(6.04, 6.4, "you?")
    assert cues[9].start == cues[9].end == 3.76  # zero-duration word is preserved


def test_real_segment_srt() -> None:
    cues = parse_srt((FIX / "buzz_segments.srt").read_text())
    assert len(cues) == 1
    assert cues[0].text.startswith("Hello, um, I think")
    assert cues[0].end == 6.43


def test_vtt_matches_srt_on_real_fixtures() -> None:
    for name in ("buzz_words", "buzz_segments"):
        vtt = parse_vtt((FIX / f"{name}.vtt").read_text())
        assert vtt == parse_srt((FIX / f"{name}.srt").read_text())


def test_parse_subtitles_detects_format() -> None:
    assert parse_subtitles((FIX / "buzz_words.vtt").read_text())[0].text == "Hello,"
    assert parse_subtitles((FIX / "buzz_words.srt").read_text())[0].text == "Hello,"


def test_bom_crlf_and_period_separator() -> None:
    text = (
        "﻿1\r\n00:00:01.500 --> 00:00:02.250\r\nHi\r\n\r\n"
        "2\r\n01:00:00,000 --> 01:00:01,000\r\nthere\r\n"
    )
    assert parse_srt(text) == [Cue(1.5, 2.25, "Hi"), Cue(3600.0, 3601.0, "there")]


def test_multiline_and_empty_cues() -> None:
    text = (
        "1\n00:00:00,000 --> 00:00:01,000\nfirst\nsecond\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\nlast\n"
    )
    assert parse_srt(text) == [Cue(0, 1, "first second"), Cue(2, 3, "last")]


def test_empty_input() -> None:
    assert parse_srt("") == []
    assert parse_srt("\n\n") == []


def test_cue_without_index() -> None:
    assert parse_srt("00:00:00,000 --> 00:00:01,000\nhey\n") == [Cue(0, 1, "hey")]


@pytest.mark.parametrize(
    "text",
    [
        "1\nnot a timing\ntext\n",
        "1\n00:00:02,000 --> 00:00:01,000\nbackwards\n",
        "1\n00:00:00,000 -> 00:00:01,000\nbad arrow\n",
        "1\n00:61:00,000 --> 00:62:00,000\nbad minutes\n",
        "junk\nmore junk\n00:00:00,000 --> 00:00:01,000\nx\n",
        "1\n00:00:00 --> 00:00:01\nno millis\n",
    ],
)
def test_malformed_srt_raises(text: str) -> None:
    with pytest.raises(SubtitleParseError):
        parse_srt(text)


def test_vtt_header_required() -> None:
    with pytest.raises(SubtitleParseError):
        parse_vtt("00:00:00.000 --> 00:00:01.000\nx\n")


def test_vtt_short_timestamps_settings_and_notes() -> None:
    text = (
        "WEBVTT - title\n\nNOTE a comment\nsecond line\n\n"
        "intro\n00:01.000 --> 00:02.500 align:start position:0%\nHello\n\n"
        "STYLE\n::cue { color: red }\n"
    )
    assert parse_vtt(text) == [Cue(1.0, 2.5, "Hello")]
