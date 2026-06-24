"""Unit tests for demoreel.transitions — registries, overlap offset, and pure geometry.

None of these touch moviepy: concat_segments is the only moviepy entry point and is not
exercised here. We test the membership frozensets, overlap_offset over a tiny duck-typed
fake config, and the three pure helpers (wipe_mask, push_offsets, zoom_blur_ramp)
exhaustively at boundaries (t=0, t=d, t past d, d<=0), for direction/sign, monotonicity,
and clamping.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import pytest

from demoreel import transitions
from demoreel.transitions import (
    OVERLAPPING,
    SUPPORTED,
    overlap_offset,
    push_offsets,
    wipe_mask,
    zoom_blur_ramp,
)

ALL_TYPES = ["cut", "dip", "crossfade", "wipe", "push", "zoom_blur"]


@dataclass
class _FakeTcfg:
    """Duck-typed stand-in for spec.TransitionConfig — only .type/.duration are read."""

    type: str
    duration: float = 0.5


# --------------------------------------------------------------------------- registries


def test_supported_is_exactly_six_types():
    assert frozenset(ALL_TYPES) == SUPPORTED
    assert len(SUPPORTED) == 6


def test_overlapping_is_the_four_overlap_types():
    assert frozenset({"crossfade", "wipe", "push", "zoom_blur"}) == OVERLAPPING


def test_overlapping_is_subset_of_supported():
    assert OVERLAPPING <= SUPPORTED


@pytest.mark.parametrize("t", ["cut", "dip"])
def test_non_overlapping_types_excluded_from_overlapping(t):
    assert t not in OVERLAPPING
    assert t in SUPPORTED


# ------------------------------------------------------------------------ overlap_offset


@pytest.mark.parametrize("t", ["crossfade", "wipe", "push", "zoom_blur"])
def test_overlap_offset_returns_duration_for_overlapping(t):
    assert overlap_offset(_FakeTcfg(t, duration=0.4)) == 0.4


@pytest.mark.parametrize("t", ["cut", "dip"])
def test_overlap_offset_zero_for_non_overlapping(t):
    assert overlap_offset(_FakeTcfg(t, duration=0.4)) == 0.0


def test_overlap_offset_unknown_type_is_zero():
    assert overlap_offset(_FakeTcfg("nonsense", duration=9.0)) == 0.0


def test_overlap_offset_reads_actual_duration():
    assert overlap_offset(_FakeTcfg("crossfade", duration=1.25)) == 1.25


# --------------------------------------------------------------------------- wipe_mask


def test_wipe_mask_shape_and_dtype():
    m = wipe_mask(0.25, 0.5, 32, 16)
    assert m.shape == (16, 32)
    assert m.dtype == np.float32


def test_wipe_mask_t0_all_hidden():
    m = wipe_mask(0.0, 0.5, 20, 10)
    assert float(m.sum()) == 0.0


def test_wipe_mask_td_all_shown():
    m = wipe_mask(0.5, 0.5, 20, 10)
    assert np.all(m == 1.0)


def test_wipe_mask_past_d_clamped_to_full():
    m = wipe_mask(99.0, 0.5, 20, 10)
    assert np.all(m == 1.0)


def test_wipe_mask_negative_t_clamped_to_empty():
    m = wipe_mask(-5.0, 0.5, 20, 10)
    assert float(m.sum()) == 0.0


def test_wipe_mask_zero_duration_is_end_state():
    m = wipe_mask(0.0, 0.0, 20, 10)
    assert np.all(m == 1.0)


def test_wipe_mask_negative_duration_is_end_state():
    m = wipe_mask(0.1, -1.0, 20, 10)
    assert np.all(m == 1.0)


def test_wipe_mask_left_fills_from_left():
    m = wipe_mask(0.25, 0.5, 20, 10, direction="left")
    # smoothstep(0.5) = 0.5 -> half the columns from the left lit.
    assert float(m[:, 0].sum()) > 0.0
    assert float(m[:, -1].sum()) == 0.0


def test_wipe_mask_right_fills_from_right():
    m = wipe_mask(0.25, 0.5, 20, 10, direction="right")
    assert float(m[:, -1].sum()) > 0.0
    assert float(m[:, 0].sum()) == 0.0


def test_wipe_mask_up_fills_from_top():
    m = wipe_mask(0.25, 0.5, 20, 10, direction="up")
    assert float(m[0, :].sum()) > 0.0
    assert float(m[-1, :].sum()) == 0.0


def test_wipe_mask_down_fills_from_bottom():
    m = wipe_mask(0.25, 0.5, 20, 10, direction="down")
    assert float(m[-1, :].sum()) > 0.0
    assert float(m[0, :].sum()) == 0.0


def test_wipe_mask_edge_advances_monotonically():
    lit = [float(wipe_mask(t, 1.0, 40, 8, direction="left").sum()) for t in np.linspace(0, 1, 11)]
    for a, b in pairwise(lit):
        assert b >= a
    assert lit[0] == 0.0
    assert lit[-1] == 40 * 8


def test_wipe_mask_clamps_tiny_dimensions():
    m = wipe_mask(0.5, 0.5, 0, 0)
    assert m.shape == (1, 1)


# ------------------------------------------------------------------------- push_offsets


def test_push_offsets_t0_incoming_off_outgoing_centered():
    inc, out = push_offsets(0.0, 0.5, 100, 50, axis="x")
    assert inc == 100
    assert out == 0


def test_push_offsets_td_incoming_centered_outgoing_gone():
    inc, out = push_offsets(0.5, 0.5, 100, 50, axis="x")
    assert inc == 0
    assert out == -100


def test_push_offsets_past_d_clamped():
    inc, out = push_offsets(10.0, 0.5, 100, 50, axis="x")
    assert (inc, out) == (0, -100)


def test_push_offsets_negative_t_clamped_to_start():
    inc, out = push_offsets(-3.0, 0.5, 100, 50, axis="x")
    assert (inc, out) == (100, 0)


def test_push_offsets_zero_duration_is_end_state():
    inc, out = push_offsets(0.0, 0.0, 100, 50, axis="x")
    assert (inc, out) == (0, -100)


def test_push_offsets_y_axis_uses_height():
    inc, out = push_offsets(0.0, 0.5, 100, 50, axis="y")
    assert inc == 50
    assert out == 0


def test_push_offsets_incoming_decreases_outgoing_decreases():
    incs, outs = [], []
    for t in np.linspace(0, 0.5, 11):
        i, o = push_offsets(t, 0.5, 100, 50, axis="x")
        incs.append(i)
        outs.append(o)
    for a, b in pairwise(incs):
        assert b <= a  # incoming slides from +w toward 0
    for a, b in pairwise(outs):
        assert b <= a  # outgoing slides from 0 toward -w
    assert all(i >= 0 for i in incs)
    assert all(o <= 0 for o in outs)


def test_push_offsets_clamps_tiny_dimensions():
    inc, out = push_offsets(0.0, 0.5, 0, 0, axis="x")
    assert inc == 1
    assert out == 0


# ------------------------------------------------------------------------ zoom_blur_ramp


def test_zoom_blur_ramp_t0_endpoints():
    scale, ina, outa = zoom_blur_ramp(0.0, 0.5)
    assert scale == pytest.approx(1.08)
    assert ina == pytest.approx(0.0)
    assert outa == pytest.approx(1.0)


def test_zoom_blur_ramp_td_endpoints():
    scale, ina, outa = zoom_blur_ramp(0.5, 0.5)
    assert scale == pytest.approx(1.0)
    assert ina == pytest.approx(1.0)
    assert outa == pytest.approx(0.0)


def test_zoom_blur_ramp_past_d_clamped():
    scale, ina, outa = zoom_blur_ramp(99.0, 0.5)
    assert (scale, ina, outa) == pytest.approx((1.0, 1.0, 0.0))


def test_zoom_blur_ramp_negative_t_clamped():
    scale, ina, outa = zoom_blur_ramp(-2.0, 0.5)
    assert (scale, ina, outa) == pytest.approx((1.08, 0.0, 1.0))


def test_zoom_blur_ramp_zero_duration_is_end_state():
    assert zoom_blur_ramp(0.0, 0.0) == pytest.approx((1.0, 1.0, 0.0))


def test_zoom_blur_ramp_negative_duration_is_end_state():
    assert zoom_blur_ramp(0.1, -1.0) == pytest.approx((1.0, 1.0, 0.0))


@pytest.mark.parametrize("t", [0.0, 0.1, 0.25, 0.4, 0.5])
def test_zoom_blur_ramp_alphas_sum_to_one(t):
    _, ina, outa = zoom_blur_ramp(t, 0.5)
    assert ina + outa == pytest.approx(1.0)


@pytest.mark.parametrize("t", [0.0, 0.1, 0.25, 0.4, 0.5])
def test_zoom_blur_ramp_scale_within_bounds(t):
    scale, _, _ = zoom_blur_ramp(t, 0.5)
    assert 1.0 <= scale <= 1.08


def test_zoom_blur_ramp_scale_decreases_alpha_increases():
    scales, alphas = [], []
    for t in np.linspace(0, 0.5, 11):
        s, ina, _ = zoom_blur_ramp(t, 0.5)
        scales.append(s)
        alphas.append(ina)
    for a, b in pairwise(scales):
        assert b <= a
    for a, b in pairwise(alphas):
        assert b >= a


# --------------------------------------------------------------------------- smoothstep


def test_smoothstep_endpoints_and_midpoint():
    assert transitions._smoothstep(0.0) == 0.0
    assert transitions._smoothstep(1.0) == 1.0
    assert transitions._smoothstep(0.5) == pytest.approx(0.5)


def test_progress_clamps_and_handles_zero_duration():
    assert transitions._progress(-1.0, 0.5) == 0.0
    assert transitions._progress(99.0, 0.5) == 1.0
    assert transitions._progress(0.5, 0.0) == 1.0
