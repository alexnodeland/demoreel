"""Unit tests for demoreel.keyframes — easing functions and the CameraTrack.

Covers the three easing primitives (smoothstep, easeInOutCubic, easeOutBack/spring),
the `_easer` dispatcher, and the CameraTrack add/sample/idle-drift/remap behavior.
All deterministic, no network, no heavy deps.
"""

from __future__ import annotations

import math

import pytest

from demoreel.keyframes import (
    CameraTrack,
    Keyframe,
    _easer,
    ease_in_out_cubic,
    ease_out_back,
    remap,
    smoothstep,
)

# A sampled grid across the closed unit interval, endpoints included.
GRID = [i / 50.0 for i in range(51)]


# --------------------------------------------------------------------------- easers


@pytest.mark.parametrize("fn", [smoothstep, ease_in_out_cubic])
def test_easer_endpoints(fn):
    assert fn(0.0) == pytest.approx(0.0)
    assert fn(1.0) == pytest.approx(1.0)


def test_ease_out_back_endpoints():
    # ease_out_back takes an overshoot param; endpoints are clamped regardless.
    assert ease_out_back(0.0, 1.7) == pytest.approx(0.0)
    assert ease_out_back(1.0, 1.7) == pytest.approx(1.0)


@pytest.mark.parametrize("fn", [smoothstep, ease_in_out_cubic])
def test_easer_monotonic_nondecreasing(fn):
    prev = fn(GRID[0])
    for u in GRID[1:]:
        cur = fn(u)
        assert cur >= prev - 1e-12, f"{fn.__name__} decreased at u={u}: {cur} < {prev}"
        prev = cur


def test_ease_out_back_monotonic_with_zero_overshoot():
    # With s=0 ease_out_back collapses to a plain cubic and is monotonic non-decreasing.
    prev = ease_out_back(GRID[0], 0.0)
    for u in GRID[1:]:
        cur = ease_out_back(u, 0.0)
        assert cur >= prev - 1e-12, f"ease_out_back decreased at u={u}"
        prev = cur


def test_smoothstep_stays_within_unit_interval():
    for u in GRID:
        v = smoothstep(u)
        assert 0.0 <= v <= 1.0, f"smoothstep({u}) = {v} escaped [0,1]"


def test_smoothstep_clamps_outside_unit_interval():
    assert smoothstep(-5.0) == 0.0
    assert smoothstep(2.0) == 1.0


def test_ease_in_out_cubic_clamps_outside_unit_interval():
    assert ease_in_out_cubic(-1.0) == 0.0
    assert ease_in_out_cubic(3.0) == 1.0


def test_spring_overshoots_above_one_mid_range():
    # _easer('spring', overshoot>0) builds ease_out_back with a positive s, which must
    # rise above 1.0 somewhere in the open interval before settling back to 1.0.
    spring = _easer("spring", 0.1)
    interior = [spring(u) for u in GRID if 0.0 < u < 1.0]
    assert max(interior) > 1.0, "spring easing never overshot 1.0"


def test_spring_no_overshoot_when_overshoot_zero():
    # overshoot 0 -> s=0 -> plain cubic, no values exceed 1.0.
    spring = _easer("spring", 0.0)
    assert all(spring(u) <= 1.0 + 1e-9 for u in GRID)


# --------------------------------------------------------------------------- _easer dispatch


def test_easer_returns_cubic_for_cubic_mode():
    assert _easer("cubic", 0.0) is ease_in_out_cubic


def test_easer_returns_smoothstep_for_smoothstep_mode():
    assert _easer("smoothstep", 0.0) is smoothstep


def test_easer_returns_smoothstep_for_unknown_mode():
    # Anything not 'cubic'/'spring' falls through to smoothstep.
    assert _easer("nonsense", 0.5) is smoothstep


def test_easer_spring_is_callable_not_a_named_function():
    spring = _easer("spring", 0.06)
    assert callable(spring)
    assert spring is not smoothstep
    assert spring is not ease_in_out_cubic


# --------------------------------------------------------------------------- add() guard


def test_add_bumps_equal_time_by_eps():
    track = CameraTrack(1000, 800)
    track.add(1.0, 2.0, 100.0, 100.0)
    track.add(1.0, 3.0, 200.0, 200.0)  # same t -> must be bumped
    kfs = track.keyframes
    assert len(kfs) == 2
    assert kfs[1].t == pytest.approx(1.0 + CameraTrack._EPS)
    assert kfs[1].t > kfs[0].t


def test_add_bumps_earlier_time_to_strictly_increasing():
    track = CameraTrack(1000, 800)
    track.add(5.0, 1.0, 0.0, 0.0)
    track.add(2.0, 1.0, 0.0, 0.0)  # earlier than last -> bumped past last
    kfs = track.keyframes
    assert kfs[1].t == pytest.approx(5.0 + CameraTrack._EPS)
    assert kfs[1].t > kfs[0].t


def test_add_keeps_strictly_increasing_time_unchanged():
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 0.0, 0.0)
    track.add(1.5, 1.0, 0.0, 0.0)
    assert track.keyframes[1].t == pytest.approx(1.5)


def test_add_coerces_center_to_float():
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 10, 20)  # ints
    kf = track.keyframes[0]
    assert isinstance(kf.cx, float)
    assert isinstance(kf.cy, float)


def test_keyframes_property_returns_a_copy():
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 0.0, 0.0)
    snapshot = track.keyframes
    snapshot.append(Keyframe(99.0, 9.0, 9.0, 9.0))
    # mutating the returned list must not affect the track's internal state
    assert len(track.keyframes) == 1


def test_last_returns_none_when_empty_and_keyframe_when_populated():
    track = CameraTrack(1000, 800)
    assert track.last() is None
    track.add(0.0, 1.0, 1.0, 2.0)
    last = track.last()
    assert isinstance(last, Keyframe)
    assert last.t == pytest.approx(0.0)


# --------------------------------------------------------------------------- sample()


def test_sample_empty_track_returns_default_center():
    track = CameraTrack(1000, 800)
    z, cx, cy = track.sample(0.0)
    assert z == pytest.approx(1.0)
    assert cx == pytest.approx(500.0)  # width / 2
    assert cy == pytest.approx(400.0)  # height / 2


def test_sample_empty_track_default_independent_of_t():
    track = CameraTrack(640, 480)
    for t in (-10.0, 0.0, 5.0, 1e6):
        z, cx, cy = track.sample(t)
        assert (z, cx, cy) == pytest.approx((1.0, 320.0, 240.0))


def test_sample_clamps_to_first_before_start():
    track = CameraTrack(1000, 800)
    track.add(1.0, 2.0, 100.0, 200.0)
    track.add(3.0, 4.0, 300.0, 400.0)
    z, cx, cy = track.sample(0.0)  # t <= first
    assert (z, cx, cy) == pytest.approx((2.0, 100.0, 200.0))


def test_sample_clamps_to_last_after_end():
    track = CameraTrack(1000, 800)
    track.add(1.0, 2.0, 100.0, 200.0)
    track.add(3.0, 4.0, 300.0, 400.0)
    z, cx, cy = track.sample(10.0)  # t >= last
    assert (z, cx, cy) == pytest.approx((4.0, 300.0, 400.0))


def test_sample_at_exact_first_and_last_keyframe_times():
    track = CameraTrack(1000, 800)
    track.add(1.0, 2.0, 100.0, 200.0)
    track.add(3.0, 4.0, 300.0, 400.0)
    assert track.sample(1.0) == pytest.approx((2.0, 100.0, 200.0))
    assert track.sample(3.0) == pytest.approx((4.0, 300.0, 400.0))


def test_sample_interior_interpolates_between_keyframes():
    # smoothstep easing: at the midpoint u=0.5, smoothstep(0.5)=0.5 so the interpolated
    # value lands exactly halfway between the two keyframes.
    track = CameraTrack(1000, 800, easing="smoothstep")
    track.add(0.0, 1.0, 0.0, 0.0)
    track.add(2.0, 3.0, 200.0, 400.0)
    z, cx, cy = track.sample(1.0)  # midpoint in time
    assert z == pytest.approx(2.0)  # 1 + (3-1)*0.5
    assert cx == pytest.approx(100.0)  # 0 + (200-0)*0.5
    assert cy == pytest.approx(200.0)  # 0 + (400-0)*0.5


def test_sample_interior_lies_between_endpoints():
    track = CameraTrack(1000, 800, easing="smoothstep")
    track.add(0.0, 1.0, 10.0, 20.0)
    track.add(4.0, 5.0, 110.0, 220.0)
    z, cx, cy = track.sample(1.0)  # u=0.25
    assert 1.0 < z < 5.0
    assert 10.0 < cx < 110.0
    assert 20.0 < cy < 220.0


def test_sample_interior_zero_span_uses_u_zero():
    # Two keyframes one _EPS apart (from the add() bump) make a tiny span; sampling at the
    # first time uses the lower keyframe's value (u=0 path is exercised internally).
    track = CameraTrack(1000, 800)
    track.add(1.0, 2.0, 100.0, 100.0)
    track.add(1.0, 9.0, 900.0, 900.0)  # bumped to 1.0 + _EPS
    # sample strictly between gives a value near the first keyframe (very short span)
    z, _, _ = track.sample(1.0 + CameraTrack._EPS / 2.0)
    assert 2.0 <= z <= 9.0


# --------------------------------------------------------------------------- idle_drift


def test_idle_drift_defaults_off():
    track = CameraTrack(1000, 800)
    assert track.idle_drift is False


def test_no_idle_drift_does_not_shift_center_after_last_keyframe():
    # Bare track: idle_drift defaults False, so even at high zoom the held center is exactly
    # the last keyframe's center for any t past the end.
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 100.0, 100.0)
    track.add(2.0, 3.0, 500.0, 400.0)  # zoom 3 > 1.05
    for t in (2.0, 5.0, 50.0):
        z, cx, cy = track.sample(t)
        assert z == pytest.approx(3.0)
        assert cx == pytest.approx(500.0)
        assert cy == pytest.approx(400.0)


def test_idle_drift_shifts_center_when_zoomed_in():
    drift = CameraTrack(1000, 800, idle_drift=True)
    drift.add(0.0, 1.0, 100.0, 100.0)
    drift.add(2.0, 3.0, 500.0, 400.0)  # zoom 3 > 1.05

    base = CameraTrack(1000, 800, idle_drift=False)
    base.add(0.0, 1.0, 100.0, 100.0)
    base.add(2.0, 3.0, 500.0, 400.0)

    # Find some t past the last keyframe where the drifted center differs from the static
    # center. The sinusoidal offset is nonzero for almost all t, so a sampled grid finds it.
    found = False
    for k in range(1, 40):
        t = 2.0 + k * 0.25
        _, dcx, dcy = drift.sample(t)
        _, bcx, bcy = base.sample(t)
        if abs(dcx - bcx) > 1e-6 or abs(dcy - bcy) > 1e-6:
            found = True
            break
    assert found, "idle_drift never shifted the center despite zoom > 1.05"


def test_idle_drift_inactive_below_zoom_threshold():
    # idle_drift on but zoom <= 1.05 -> no offset applied; center stays exact.
    track = CameraTrack(1000, 800, idle_drift=True)
    track.add(0.0, 1.0, 100.0, 100.0)
    track.add(2.0, 1.0, 300.0, 200.0)  # zoom stays 1.0, never exceeds 1.05
    z, cx, cy = track.sample(10.0)
    assert z == pytest.approx(1.0)
    assert cx == pytest.approx(300.0)
    assert cy == pytest.approx(200.0)


def test_idle_drift_offset_matches_formula():
    # Verify the drift offset equals the documented sinusoidal expression.
    w, h = 1000, 800
    amount = 0.006
    track = CameraTrack(w, h, idle_drift=True, drift_amount=amount)
    track.add(0.0, 2.0, 500.0, 400.0)  # single keyframe, zoom 2 > 1.05
    t = 3.0
    z, cx, cy = track.sample(t)
    amp = amount * w
    assert z == pytest.approx(2.0)
    assert cx == pytest.approx(500.0 + amp * math.sin(t * 0.55))
    assert cy == pytest.approx(400.0 + amp * 0.7 * math.cos(t * 0.42))


# --------------------------------------------------------------------------- remap()


def _offset(dx, dy):
    return lambda cx, cy: (cx + dx, cy + dy)


def test_remap_preserves_keyframe_count_t_and_zoom():
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 10.0, 20.0)
    track.add(1.0, 2.0, 30.0, 40.0)
    track.add(2.0, 3.0, 50.0, 60.0)

    out = remap(track, _offset(100.0, 0.0), 1920, 1080)
    src, dst = track.keyframes, out.keyframes
    assert len(dst) == len(src) == 3
    for a, b in zip(src, dst, strict=True):
        assert b.t == pytest.approx(a.t)
        assert b.zoom == pytest.approx(a.zoom)


def test_remap_maps_centers_through_fn():
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 10.0, 20.0)
    track.add(1.0, 2.0, 30.0, 40.0)

    out = remap(track, _offset(100.0, 5.0), 1920, 1080)
    for a, b in zip(track.keyframes, out.keyframes, strict=True):
        assert b.cx == pytest.approx(a.cx + 100.0)
        assert b.cy == pytest.approx(a.cy + 5.0)


def test_remap_returns_new_track_with_target_dimensions():
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 10.0, 20.0)
    out = remap(track, lambda cx, cy: (cx, cy), 1920, 1080)
    assert out is not track
    assert isinstance(out, CameraTrack)
    assert out.width == 1920
    assert out.height == 1080


def test_remap_does_not_mutate_source_track():
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 10.0, 20.0)
    remap(track, _offset(100.0, 100.0), 1920, 1080)
    # source keyframe centers are untouched
    assert track.keyframes[0].cx == pytest.approx(10.0)
    assert track.keyframes[0].cy == pytest.approx(20.0)


def test_remap_preserves_strictly_increasing_times_after_bump():
    # Source has a bumped duplicate time; remap re-adds through add(), preserving order.
    track = CameraTrack(1000, 800)
    track.add(1.0, 1.0, 0.0, 0.0)
    track.add(1.0, 2.0, 0.0, 0.0)  # bumped to 1.0 + _EPS
    out = remap(track, lambda cx, cy: (cx, cy), 1920, 1080)
    times = [k.t for k in out.keyframes]
    assert times[1] > times[0]


def test_remap_forwards_easing_kwargs():
    # remap passes **kw into the new CameraTrack; spring easing should overshoot on the
    # remapped track between two distinct keyframes.
    track = CameraTrack(1000, 800)
    track.add(0.0, 1.0, 0.0, 0.0)
    track.add(2.0, 2.0, 1000.0, 0.0)
    out = remap(
        track,
        lambda cx, cy: (cx, cy),
        1920,
        1080,
        easing="spring",
        overshoot=0.1,
    )
    # sample across the interior; with spring overshoot the interpolated cx exceeds the
    # larger endpoint somewhere (overshoot past target).
    overshot = any(out.sample(2.0 * u / 50.0)[1] > 1000.0 + 1e-6 for u in range(1, 50))
    assert overshot, "remap did not forward spring easing kwargs"
