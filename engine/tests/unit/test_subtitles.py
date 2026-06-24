"""Unit tests for demoreel.subtitles.

Covers cue splitting (time-ordering, contiguity, the exact-end invariant, and the
short-span / negative-width guard), sentence chunking + width wrapping, timestamp
formatting (srt vs vtt separators, negative clamp), and the .srt/.vtt/transcript
writers (including the degenerate end<=start cue that writers must repair).

All pure-Python: no PIL fonts, no moviepy, no network.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from demoreel.subtitles import (
    Cue,
    _chunk_sentences,
    _ts,
    _wrap_to_width,
    split_into_cues,
    write_srt,
    write_transcript,
    write_vtt,
)


# --------------------------------------------------------------------------- #
# split_into_cues
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", ["", "   ", "\n\t  \n", None])
def test_split_into_cues_empty_text_returns_empty(text):
    assert split_into_cues(text, 0.0, 10.0) == []


def test_split_into_cues_returns_cue_objects():
    cues = split_into_cues("Hello world.", 0.0, 5.0)
    assert cues
    assert all(isinstance(c, Cue) for c in cues)


def test_split_into_cues_time_ordered_and_contiguous():
    text = (
        "First sentence here. Second sentence follows. Third one too. "
        "Fourth wraps things up nicely. Fifth and final remark."
    )
    start, end = 2.0, 20.0
    cues = split_into_cues(text, start, end, max_chars=30)
    assert len(cues) >= 2

    # First cue starts at the scene start.
    assert cues[0].start == pytest.approx(start)

    for cue in cues:
        # No cue is inverted or zero/negative width is allowed only when clamped,
        # but for an ample span every cue has positive width and is in range.
        assert cue.end >= cue.start
        assert start <= cue.start <= end
        assert start <= cue.end <= end

    # Contiguous: each cue starts exactly where the previous one ended.
    for prev, nxt in pairwise(cues):
        assert nxt.start == pytest.approx(prev.end)


def test_split_into_cues_last_cue_ends_exactly_on_boundary():
    text = "One. Two. Three. Four. Five. Six. Seven. Eight."
    end = 13.0
    cues = split_into_cues(text, 1.0, end, max_chars=20)
    assert cues[-1].end == end  # exact, not approx — set directly to `end`


def test_split_into_cues_single_cue_lands_on_boundary():
    cues = split_into_cues("Short.", 3.0, 9.0)
    assert len(cues) == 1
    assert cues[0].start == pytest.approx(3.0)
    assert cues[0].end == 9.0


def test_split_into_cues_very_short_span_never_inverts_or_negative_width():
    """The regression guard: a tiny span with multiline text must never yield a
    cue whose start > end or whose width is negative."""
    text = (
        "This is a fairly long narration that will chunk into several pieces "
        "across an almost-zero duration scene that lasts a twentieth of a second."
    )
    start, end = 0.0, 0.05
    cues = split_into_cues(text, start, end, max_chars=20)
    assert len(cues) >= 2  # genuinely multiple chunks, exercising the drift path
    for cue in cues:
        assert cue.end >= cue.start, f"inverted cue: {cue}"
        assert (cue.end - cue.start) >= 0, f"negative width: {cue}"
        assert cue.start <= end
        assert cue.end <= end
    assert cues[-1].end == end


def test_split_into_cues_normalizes_internal_whitespace():
    cues = split_into_cues("  Hello\n\n  there\tfriend.  ", 0.0, 4.0)
    assert len(cues) == 1
    assert cues[0].text == "Hello there friend."


def test_split_into_cues_zero_length_span_stays_non_inverted():
    cues = split_into_cues("Alpha beta gamma delta epsilon zeta.", 5.0, 5.0, max_chars=10)
    for cue in cues:
        assert cue.end >= cue.start
    assert cues[-1].end == 5.0


# --------------------------------------------------------------------------- #
# _chunk_sentences
# --------------------------------------------------------------------------- #
def test_chunk_sentences_splits_on_boundaries():
    chunks = _chunk_sentences("First sentence. Second sentence! Third sentence?", 90)
    assert chunks == ["First sentence.", "Second sentence!", "Third sentence?"]


def test_chunk_sentences_wraps_long_sentence_under_max_chars():
    long = "word " * 40  # 200 chars, no sentence punctuation
    long = long.strip()
    max_chars = 30
    chunks = _chunk_sentences(long, max_chars)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= max_chars


def test_chunk_sentences_drops_empty_pieces():
    chunks = _chunk_sentences("Hi.", 90)
    assert chunks == ["Hi."]
    assert "" not in chunks


def test_chunk_sentences_short_sentence_kept_whole():
    chunks = _chunk_sentences("A tidy little sentence.", 90)
    assert chunks == ["A tidy little sentence."]


# --------------------------------------------------------------------------- #
# _wrap_to_width
# --------------------------------------------------------------------------- #
class _FakeFont:
    """Deterministic monospace-ish font: width == 10px per character."""

    def getbbox(self, text):
        return (0, 0, 10 * len(text), 12)


def test_wrap_to_width_non_empty_input_never_returns_empty():
    font = _FakeFont()
    # max_w smaller than even one char forces the `or not cur` fallback path.
    lines = _wrap_to_width("supercalifragilistic", font, max_w=1)
    assert lines  # never empty
    assert all(isinstance(ln, str) for ln in lines)


def test_wrap_to_width_wraps_multiple_words():
    font = _FakeFont()
    # Each word is 4 chars => 40px; allow ~2 words per line (90px).
    lines = _wrap_to_width("abcd abcd abcd abcd", font, max_w=90)
    assert len(lines) >= 2
    # Reconstructing keeps every word.
    assert " ".join(lines).split() == ["abcd", "abcd", "abcd", "abcd"]


def test_wrap_to_width_single_word_too_wide_kept_on_one_line():
    font = _FakeFont()
    lines = _wrap_to_width("toolongword", font, max_w=5)
    assert lines == ["toolongword"]


def test_wrap_to_width_falls_back_to_raw_text_when_no_words():
    # text.split() on whitespace-only yields no words -> `lines or [text]`.
    font = _FakeFont()
    lines = _wrap_to_width("   ", font, max_w=100)
    assert lines == ["   "]


# --------------------------------------------------------------------------- #
# _ts
# --------------------------------------------------------------------------- #
def test_ts_srt_separator():
    assert _ts(3661.5, ",") == "01:01:01,500"


def test_ts_vtt_separator():
    assert _ts(3661.5, ".") == "01:01:01.500"


def test_ts_default_separator_is_comma():
    assert _ts(3661.5) == "01:01:01,500"


def test_ts_zero():
    assert _ts(0.0) == "00:00:00,000"


@pytest.mark.parametrize("neg", [-1.0, -3661.5, -0.001])
def test_ts_negative_clamps_to_zero(neg):
    assert _ts(neg) == "00:00:00,000"
    assert _ts(neg, ".") == "00:00:00.000"


def test_ts_rounds_milliseconds():
    # 1.2345s -> 1234.5ms -> round() banker's rounding to 1234ms (round-half-to-even)
    assert _ts(1.2345) == "00:00:01,234"
    # 1.0005s -> 1000.5ms -> 1000ms (half-to-even on .5 lands on even 1000)
    assert _ts(1.0006) == "00:00:01,001"


# --------------------------------------------------------------------------- #
# write_srt
# --------------------------------------------------------------------------- #
def test_write_srt_block_structure(tmp_path):
    cues = [Cue(0.0, 1.5, "First line"), Cue(1.5, 3.0, "Second line")]
    out = tmp_path / "out.srt"
    write_srt(cues, out)
    content = out.read_text(encoding="utf-8")

    # No WEBVTT header for SRT.
    assert not content.startswith("WEBVTT")

    blocks = [b for b in content.split("\n\n") if b.strip()]
    assert len(blocks) == 2

    first = blocks[0].splitlines()
    assert first[0] == "1"  # index
    assert first[1] == "00:00:00,000 --> 00:00:01,500"  # timestamp with comma sep
    assert first[2] == "First line"  # text

    second = blocks[1].splitlines()
    assert second[0] == "2"
    assert second[1] == "00:00:01,500 --> 00:00:03,000"
    assert second[2] == "Second line"

    # Each block ends with a blank line separating it from the next.
    assert content.endswith("\n")


def test_write_srt_uses_comma_separator(tmp_path):
    out = tmp_path / "c.srt"
    write_srt([Cue(0.0, 2.0, "x")], out)
    text = out.read_text(encoding="utf-8")
    assert "," in text
    assert "-->" in text


def test_write_srt_empty_cues(tmp_path):
    out = tmp_path / "empty.srt"
    write_srt([], out)
    assert out.read_text(encoding="utf-8") == ""


# --------------------------------------------------------------------------- #
# write_vtt
# --------------------------------------------------------------------------- #
def test_write_vtt_starts_with_webvtt(tmp_path):
    out = tmp_path / "out.vtt"
    write_vtt([Cue(0.0, 1.0, "hello")], out)
    content = out.read_text(encoding="utf-8")
    assert content.startswith("WEBVTT")


def test_write_vtt_uses_dot_separator(tmp_path):
    out = tmp_path / "dot.vtt"
    write_vtt([Cue(0.0, 1.25, "tick")], out)
    content = out.read_text(encoding="utf-8")
    assert "00:00:00.000 --> 00:00:01.250" in content


def test_write_vtt_empty_cues_still_has_header(tmp_path):
    out = tmp_path / "emptyvtt.vtt"
    write_vtt([], out)
    content = out.read_text(encoding="utf-8")
    assert content.startswith("WEBVTT")


# --------------------------------------------------------------------------- #
# degenerate cue repair (end <= start)
# --------------------------------------------------------------------------- #
def _parse_ts(ts: str, sep: str) -> float:
    hms, ms = ts.split(sep)
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


@pytest.mark.parametrize("writer,sep", [(write_srt, ","), (write_vtt, ".")])
def test_writer_repairs_degenerate_cue_to_positive_range(tmp_path, writer, sep):
    # end == start (degenerate) and end < start (inverted) must both come out end > start.
    cues = [Cue(2.0, 2.0, "zero width"), Cue(5.0, 4.0, "inverted")]
    out = tmp_path / "degenerate"
    writer(cues, out)
    content = out.read_text(encoding="utf-8")

    ranges = [line for line in content.splitlines() if "-->" in line]
    assert len(ranges) == 2
    for rng in ranges:
        left, right = (p.strip() for p in rng.split("-->"))
        start_s = _parse_ts(left, sep)
        end_s = _parse_ts(right, sep)
        assert end_s > start_s, f"invalid range emitted: {rng}"


# --------------------------------------------------------------------------- #
# write_transcript
# --------------------------------------------------------------------------- #
def test_write_transcript_titled_markdown(tmp_path):
    out = tmp_path / "transcript.md"
    write_transcript("  The body of the narration.  ", "My Demo", out)
    content = out.read_text(encoding="utf-8")

    lines = content.splitlines()
    assert lines[0] == "# My Demo — transcript"
    # Body is stripped of surrounding whitespace.
    assert "The body of the narration." in content
    assert not content.startswith("\n")
    # Title line followed by a blank line then the body.
    assert lines[1] == ""
    assert content.endswith("\n")


def test_write_transcript_strips_body(tmp_path):
    out = tmp_path / "t2.md"
    write_transcript("\n\n  spaced out  \n\n", "T", out)
    content = out.read_text(encoding="utf-8")
    assert content == "# T — transcript\n\nspaced out\n"
