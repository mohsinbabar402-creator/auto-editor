import pytest
from analysis.transcript import (
    NormalizedTranscript,
    WordToken,
    EmptyTranscriptError,
    InvalidWordIndexError
)


def test_empty_transcript_raises():
    with pytest.raises(EmptyTranscriptError):
        NormalizedTranscript([])


def test_all_whitespace_tokens_raises():
    with pytest.raises(EmptyTranscriptError):
        NormalizedTranscript([{"word": "   ", "start": 0.0, "end": 0.5}])


def test_monotonic_sorting_and_reindexing():
    # Out of order input
    raw = [
        {"word": "world", "start": 1.5, "end": 2.0},
        {"word": "hello", "start": 0.2, "end": 0.8},
        {"word": "there", "start": 0.9, "end": 1.4},
    ]
    t = NormalizedTranscript(raw)
    assert len(t) == 3
    assert t.get_word(0).word == "hello"
    assert t.get_word(0).index == 0
    assert t.get_word(1).word == "there"
    assert t.get_word(2).word == "world"


def test_inverted_timestamps_repair():
    # end < start
    raw = [{"word": "glitch", "start": 2.0, "end": 1.0}]
    t = NormalizedTranscript(raw)
    w = t.get_word(0)
    assert w.start == 2.0
    assert w.end >= w.start # Auto repaired


def test_invalid_word_index_raises():
    raw = [{"word": "first", "start": 0.0, "end": 0.5}]
    t = NormalizedTranscript(raw)
    with pytest.raises(InvalidWordIndexError):
        t.get_word(1)
    with pytest.raises(InvalidWordIndexError):
        t.get_word(-1)


def test_effect_window_resolution():
    raw = [
        {"word": "launch", "start": 1.0, "end": 1.4},
        {"word": "revenue", "start": 1.5, "end": 2.0},
    ]
    t = NormalizedTranscript(raw)
    # pre_offset=50ms, duration=800ms
    start_sec, end_sec = t.resolve_effect_window(
        word_index=1,
        duration_ms=800,
        pre_offset_ms=50,
        video_duration=10.0
    )
    assert start_sec == 1.45 # 1.5 - 0.05
    assert end_sec == 2.25   # 1.45 + 0.80


def test_effect_window_clamping():
    raw = [{"word": "last", "start": 9.5, "end": 9.8}]
    t = NormalizedTranscript(raw)
    # video duration is 10.0s, effect tries to go to 10.5s
    start_sec, end_sec = t.resolve_effect_window(
        word_index=0,
        duration_ms=1000,
        pre_offset_ms=0,
        video_duration=10.0
    )
    assert start_sec == 9.5
    assert end_sec == 10.0 # Clamped to video duration
