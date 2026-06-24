"""Unit tests for the pure helpers in demoreel.compose.

Both _group_words and _scaled are dependency-free (the heavy moviepy imports in
compose.py live inside functions), so we can import them directly without a
browser or a render pipeline.
"""

from __future__ import annotations

import pytest

from demoreel.compose import _group_words, _scaled


def _words(*tokens):
    """Build the (word, start, end) tuples _group_words consumes.

    The timings are irrelevant to grouping (only w[0], the word string, is read),
    so we hand out monotonically increasing placeholder times.
    """
    return [(tok, float(i), float(i) + 0.5) for i, tok in enumerate(tokens)]


def _flatten(lines):
    return [w for line in lines for w in line]


# ----------------------------------------------------------------- _group_words


def test_group_words_empty_input_returns_no_lines():
    assert _group_words([], 40) == []


def test_group_words_no_word_dropped_flatten_equals_input():
    words = _words("the", "quick", "brown", "fox", "jumped", "over", "the", "lazy", "dog")
    lines = _group_words(words, 12)
    # Every input word appears exactly once, in order, across the output lines.
    assert _flatten(lines) == words


def test_group_words_one_short_line_stays_one_line():
    words = _words("hello", "world")
    # "hello world" is well under the cap, so it must not wrap.
    lines = _group_words(words, 80)
    assert len(lines) == 1
    assert lines[0] == words


def test_group_words_small_max_chars_produces_multiple_lines():
    words = _words("alpha", "beta", "gamma", "delta", "epsilon")
    lines = _group_words(words, 8)
    assert len(lines) > 1
    # Still loses nothing.
    assert _flatten(lines) == words


def test_group_words_respects_max_chars_with_trailing_space_accounting():
    # count starts at 0; first word appends unconditionally (cur is empty),
    # bumping count to len(word)+1. The wrap fires when count + len(next) > max.
    # "aaa"(=3 -> count 4) then "bbb": 4 + 3 = 7 <= 8, stays. Then "ccc":
    # 4 + 3 + 1 = 8 -> count 8, then + len("ccc")=3 -> 11 > 8, wraps.
    words = _words("aaa", "bbb", "ccc")
    lines = _group_words(words, 8)
    assert [[w[0] for w in line] for line in lines] == [["aaa", "bbb"], ["ccc"]]


def test_group_words_overlong_single_word_kept_alone_not_dropped():
    # A word longer than max_chars cannot be dropped: the first word of any line
    # is appended unconditionally (the wrap guard requires a non-empty cur).
    long_word = "supercalifragilistic"  # 20 chars, well over the cap
    words = _words("hi", long_word, "bye")
    lines = _group_words(words, 5)
    assert _flatten(lines) == words
    # The over-long word lands on its own line, sandwiched by the short ones.
    flattened_lines = [[w[0] for w in line] for line in lines]
    assert [long_word] in flattened_lines
    # The over-long line is allowed to exceed max_chars (single-word exception).
    overlong_line = next(line for line in lines if line[0][0] == long_word)
    assert len(overlong_line) == 1


def test_group_words_each_line_within_cap_except_lone_overlong_words():
    words = _words("one", "two", "three", "four", "five", "six", "seven")
    max_chars = 10
    lines = _group_words(words, max_chars)
    for line in lines:
        joined = " ".join(w[0] for w in line)
        if len(line) == 1:
            # Lone words are exempt — may exceed the cap.
            continue
        assert len(joined) <= max_chars


def test_group_words_single_word_input():
    words = _words("solo")
    lines = _group_words(words, 40)
    assert lines == [words]


def test_group_words_order_preserved():
    words = _words("a", "b", "c", "d", "e", "f")
    lines = _group_words(words, 3)
    flat = [w[0] for w in _flatten(lines)]
    assert flat == ["a", "b", "c", "d", "e", "f"]


# ---------------------------------------------------------------------- _scaled


def test_scaled_identity_at_1080():
    assert _scaled(40, 1080) == 40


def test_scaled_doubles_at_2160():
    assert _scaled(40, 2160) == 80


def test_scaled_floors_at_14():
    # 10 * 540 / 1080 = 5 -> rounds to 5 -> clamped up to the 14 floor.
    assert _scaled(10, 540) == 14


def test_scaled_clamp_when_result_just_below_floor():
    # 26 * 540 / 1080 = 13.0 -> below the 14 floor -> clamped up to 14.
    assert _scaled(26, 540) == 14


def test_scaled_at_floor_boundary_returns_14():
    # 28 * 540 / 1080 = 14.0 -> exactly the floor, no clamping needed.
    assert _scaled(28, 540) == 14


def test_scaled_just_above_floor():
    # 30 * 540 / 1080 = 15.0
    assert _scaled(30, 540) == 15


def test_scaled_half_scaling_at_540():
    # General half-resolution scaling above the floor.
    assert _scaled(80, 540) == 40


def test_scaled_returns_int():
    result = _scaled(40, 2160)
    assert isinstance(result, int)


@pytest.mark.parametrize(
    ("size", "out_h", "expected"),
    [
        (40, 1080, 40),
        (40, 2160, 80),
        (10, 540, 14),  # clamped
        (28, 540, 14),  # exactly floor
        (30, 540, 15),
        (60, 1080, 60),
        (100, 1080, 100),
    ],
)
def test_scaled_parametrized(size, out_h, expected):
    assert _scaled(size, out_h) == expected
