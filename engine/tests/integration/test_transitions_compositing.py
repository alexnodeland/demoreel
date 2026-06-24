"""Compositing-level regression tests for demoreel.transitions.concat_segments.

The pure helpers (wipe_mask / push_offsets / zoom_blur_ramp) are unit-tested without moviepy,
but those passed even while `push` was silently degraded to a full-frame cover (the position
offset was dropped by concatenate_videoclips). These tests drive the ACTUAL moviepy compositing
with solid-color clips and assert each transition's mid-overlap frame, so a broken effect can't
slip through green again.

moviepy + ffmpeg only (no Playwright, no network) → marked `slow`, excluded from the default run.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = [pytest.mark.slow]

W, H = 200, 120
DUR = 1.6  # each segment; with d=0.6 two segments overlap on t∈[1.0, 1.6]
D = 0.6


class _TC:
    """Duck-typed TransitionConfig (concat_segments only reads .type/.duration)."""

    def __init__(self, type_: str, duration: float = D) -> None:
        self.type = type_
        self.duration = duration


def _segments():
    from moviepy import ColorClip

    red = ColorClip((W, H), color=(220, 40, 40)).with_duration(DUR)
    blue = ColorClip((W, H), color=(40, 40, 220)).with_duration(DUR)
    return [red, blue]


def _dominant(frame, x0, x1):
    """'red' or 'blue' for the column band [x0, x1) of an RGB frame."""
    band = frame[:, x0:x1].astype(int)
    return "red" if band[..., 0].mean() > band[..., 2].mean() else "blue"


def _final(type_):
    from demoreel.transitions import concat_segments

    return concat_segments(_segments(), _TC(type_))


def test_total_duration_overlaps_by_d_for_overlapping_types():
    # two 1.6s clips, one 0.6s overlap → 2.6s for crossfade/wipe/push/zoom_blur
    for t in ("crossfade", "wipe", "push", "zoom_blur"):
        assert _final(t).duration == pytest.approx(DUR + DUR - D, abs=0.05), t


def test_cut_has_no_overlap_and_full_runtime():
    final = _final("cut")
    assert final.duration == pytest.approx(DUR + DUR, abs=0.05)
    # at t just before the first clip ends, it's still fully red (no early blend)
    assert _dominant(final.get_frame(1.5), 0, W) == "red"


def test_push_slides_red_out_left_and_blue_in_right():
    final = _final("push")
    # start of overlap: blue still off-screen right → all red
    assert _dominant(final.get_frame(1.00), 0, W) == "red"
    # midpoint: a genuine spatial split — left half red (exiting), right half blue (entering)
    mid = final.get_frame(1.30)
    assert _dominant(mid, 0, 60) == "red", "left half should still show the outgoing clip"
    assert _dominant(mid, 140, W) == "blue", "right half should show the incoming clip"
    # end of overlap: push complete → all blue
    assert _dominant(final.get_frame(1.58), 0, W) == "blue"


def test_wipe_reveals_incoming_as_a_hard_spatial_split():
    final = _final("wipe")
    mid = final.get_frame(1.30)
    left = _dominant(mid, 0, 60)
    right = _dominant(mid, 140, W)
    # a wipe is a masked reveal: at the midpoint the two halves differ (one revealed, one not)
    assert left != right, f"wipe midpoint should be split, got left={left} right={right}"


def test_crossfade_is_a_uniform_opacity_blend_not_a_spatial_split():
    final = _final("crossfade")
    mid = final.get_frame(1.30).astype(int)
    # both channels present everywhere (purple-ish); neither pure red nor pure blue
    r, b = mid[..., 0].mean(), mid[..., 2].mean()
    assert 80 < r < 180 and 80 < b < 180, f"expected a blend, got R={r:.0f} B={b:.0f}"
    # spatially uniform: left and right bands blend equally (within tolerance)
    left_r = mid[:, :60][..., 0].mean()
    right_r = mid[:, 140:][..., 0].mean()
    assert abs(left_r - right_r) < 30, "crossfade should be spatially uniform"


def test_overlap_offset_matches_overlapping_set():
    from demoreel.transitions import OVERLAPPING, overlap_offset

    for t in ("crossfade", "wipe", "push", "zoom_blur"):
        assert t in OVERLAPPING
        assert overlap_offset(_TC(t)) == pytest.approx(D)
    for t in ("cut", "dip"):
        assert overlap_offset(_TC(t)) == 0.0


def test_single_segment_short_circuits():
    from demoreel.transitions import concat_segments

    clips = _segments()[:1]
    assert concat_segments(clips, _TC("push")) is clips[0]


def test_unknown_type_falls_back_to_overlapping_default():
    # an unrecognized type must not raise — it degrades to the crossfade/compose path
    final = _final("nonexistent_transition")
    assert final.duration > 0
    arr = final.get_frame(1.30)
    assert isinstance(arr, np.ndarray)
