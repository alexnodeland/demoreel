"""Scene-transition library — concatenation strategies + pure geometry helpers.

The compositor stitches per-scene clips into one timeline. The *type* of transition
between adjacent clips changes both how they are concatenated and whether they overlap
in time. Two families exist:

- non-overlapping (``cut``, ``dip``): clips play back-to-back, total duration is the
  sum of segment durations; captions need no time correction.
- overlapping (``crossfade``, ``wipe``, ``push``, ``zoom_blur``): each later clip starts
  ``duration`` seconds before the previous one ends (moviepy ``padding=-d``), so the
  timeline is shorter and downstream caption offsets must subtract ``duration`` per
  boundary. ``overlap_offset`` encodes that single source of truth.

``concat_segments`` is the only moviepy-touching entry point and is wrapped so a broken
effect can never fail a render — it degrades to a plain compose-concat. Everything else
(``wipe_mask``, ``push_offsets``, ``zoom_blur_ramp``) is pure numpy/Python math, unit
tested directly without rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

# --------------------------------------------------------------------------- registries

#: Transition types whose later clip overlaps the earlier one by ``duration`` seconds.
OVERLAPPING: frozenset[str] = frozenset({"crossfade", "wipe", "push", "zoom_blur"})

#: Every transition type this module knows how to concatenate.
SUPPORTED: frozenset[str] = frozenset({"cut", "dip"}) | OVERLAPPING


def overlap_offset(tcfg) -> float:
    """Seconds of timeline overlap a single boundary of this transition introduces.

    Overlapping transitions (``padding=-d``) shorten the timeline by ``duration`` at each
    seam, so caption/voiceover offsets must subtract that. Non-overlapping ones contribute
    nothing. ``tcfg`` is duck-typed: only ``.type`` and ``.duration`` are read.
    """
    return tcfg.duration if tcfg.type in OVERLAPPING else 0.0


# --------------------------------------------------------------------------- pure helpers


def _smoothstep(x: float) -> float:
    """Hermite smoothstep on a value already clamped to [0, 1]."""
    return x * x * (3.0 - 2.0 * x)


def _progress(t: float, d: float) -> float:
    """Eased progress in [0, 1]. ``t`` is clamped to ``[0, d]``; ``d <= 0`` -> 1.0 (end)."""
    if d <= 0:
        return 1.0
    return _smoothstep(min(max(t / d, 0.0), 1.0))


def wipe_mask(t: float, d: float, w: int, h: int, direction: str = "left") -> np.ndarray:
    """Hard-edged sweep mask: float32 ``(h, w)`` in [0, 1] revealing the incoming clip.

    At ``t <= 0`` the mask is ~all zeros (incoming hidden); at ``t >= d`` (or ``d <= 0``)
    all ones (incoming fully shown). In between, a single hard edge sweeps across the
    frame. ``direction`` is the side the reveal *originates from*: "left" sweeps the edge
    rightward, "right" leftward, "up" downward, "down" upward.
    """
    w = max(int(w), 1)
    h = max(int(h), 1)
    p = _progress(t, d)
    mask = np.zeros((h, w), dtype=np.float32)
    if direction in ("left", "right"):
        cut = round(p * w)
        if direction == "left":
            mask[:, :cut] = 1.0
        else:
            mask[:, w - cut :] = 1.0
    else:
        cut = round(p * h)
        if direction == "up":
            mask[:cut, :] = 1.0
        else:
            mask[h - cut :, :] = 1.0
    return mask


def push_offsets(t: float, d: float, w: int, h: int, axis: str = "x") -> tuple[int, int]:
    """Pixel offsets ``(incoming, outgoing)`` along ``axis`` for a push transition.

    The incoming clip slides in from the far edge toward 0 while the outgoing slides out
    the opposite way. At ``t <= 0`` incoming is fully off-screen (``+dimension``) and
    outgoing is centered (0). At ``t >= d`` (or ``d <= 0``) incoming is centered (0) and
    outgoing is fully gone (``-dimension``). ``axis`` is "x" (use width) or "y" (height).
    """
    dim = max(int(w), 1) if axis == "x" else max(int(h), 1)
    p = _progress(t, d)
    incoming = round((1.0 - p) * dim)
    outgoing = round(-p * dim)
    return incoming, outgoing


def zoom_blur_ramp(t: float, d: float) -> tuple[float, float, float]:
    """Whip-zoom ramp ``(incoming_scale, incoming_alpha, outgoing_alpha)``.

    Incoming eases its scale from 1.08 down to 1.0 while fading in; outgoing fades out.
    At ``t <= 0``: ``(1.08, 0.0, 1.0)``. At ``t >= d`` (or ``d <= 0``): ``(1.0, 1.0, 0.0)``.
    The two alphas always sum to 1.0 (a clean crossfade).
    """
    p = _progress(t, d)
    incoming_scale = 1.08 - 0.08 * p
    incoming_alpha = p
    outgoing_alpha = 1.0 - p
    return incoming_scale, incoming_alpha, outgoing_alpha


# --------------------------------------------------------------- concatenation dispatch


def concat_segments(clips: Sequence, tcfg):
    """Concatenate per-scene clips applying the ``tcfg.type`` transition between them.

    Replaces the former ``compose._concat``. Returns a single moviepy ``VideoClip``.
    Single-clip input short-circuits to ``clips[0]``. The whole dispatch is wrapped so a
    failed effect degrades to a plain compose-concat rather than breaking a render.
    """
    from moviepy import concatenate_videoclips

    clips = list(clips)
    if len(clips) == 1:
        return clips[0]
    if tcfg.type == "cut":
        return concatenate_videoclips(clips, method="compose")

    d = tcfg.duration
    try:
        if tcfg.type == "dip":
            return _concat_dip(clips, d, concatenate_videoclips)
        if tcfg.type == "wipe":
            return _concat_wipe(clips, d, concatenate_videoclips)
        if tcfg.type == "push":
            return _concat_push(clips, d)
        if tcfg.type == "zoom_blur":
            return _concat_zoom_blur(clips, d, concatenate_videoclips)
        # crossfade (default / fallback for any overlapping type)
        return _concat_crossfade(clips, d, concatenate_videoclips)
    except Exception:  # noqa: BLE001 - never fail a render on a transition
        return concatenate_videoclips(clips, method="compose")


def _concat_dip(clips, d, concatenate_videoclips):
    from moviepy.video.fx import FadeIn, FadeOut

    out = []
    for i, c in enumerate(clips):
        fx = []
        if i > 0:
            fx.append(FadeIn(d / 2))
        if i < len(clips) - 1:
            fx.append(FadeOut(d / 2))
        out.append(c.with_effects(fx) if fx else c)
    return concatenate_videoclips(out, method="compose")


def _concat_crossfade(clips, d, concatenate_videoclips):
    from moviepy.video.fx import CrossFadeIn

    out = [clips[0]]
    for c in clips[1:]:
        out.append(c.with_effects([CrossFadeIn(d)]))
    return concatenate_videoclips(out, method="compose", padding=-d)


def _concat_wipe(clips, d, concatenate_videoclips):
    """Overlapping wipe: each later clip is revealed by an animated hard-edge mask."""
    from moviepy import VideoClip

    out = [clips[0]]
    for c in clips[1:]:
        w, h = c.size

        def make_frame(t, w=w, h=h):
            return wipe_mask(t, d, w, h, direction="left")

        mask = VideoClip(make_frame, is_mask=True, duration=d)
        out.append(c.with_mask(mask))
    return concatenate_videoclips(out, method="compose", padding=-d)


def _concat_push(clips, d):
    """Overlapping push: each adjacent pair slides together — the outgoing clip exits to the
    left while the incoming clip enters from the right, both visible during the overlap.

    Built as an explicit CompositeVideoClip with per-clip start times and a position callable,
    because concatenate_videoclips(method="compose") does NOT honor per-clip with_position
    during an overlap (it stacks the incoming clip full-frame, which reads as a hard cut).
    moviepy evaluates a clip's position at its LOCAL time (0..duration), same as a mask clip.
    """
    from moviepy import CompositeVideoClip

    starts: list[float] = []
    acc = 0.0
    for c in clips:
        starts.append(acc)
        acc += c.duration - d
    total = starts[-1] + clips[-1].duration
    n = len(clips)

    placed = []
    for i, c in enumerate(clips):
        w, h = c.size
        dur = c.duration
        enters = i > 0
        leaves = i < n - 1

        def pos(t, dur=dur, w=w, h=h, enters=enters, leaves=leaves):
            if enters and t < d:  # first d seconds: slide in from the right (+w → 0)
                return (push_offsets(t, d, w, h, axis="x")[0], 0)
            if leaves and t > dur - d:  # last d seconds: slide out to the left (0 → -w)
                return (push_offsets(t - (dur - d), d, w, h, axis="x")[1], 0)
            return (0, 0)

        placed.append(c.with_start(starts[i]).with_position(pos))
    return CompositeVideoClip(placed, size=clips[0].size).with_duration(total)


def _concat_zoom_blur(clips, d, concatenate_videoclips):
    """Overlapping whip-zoom: a crossfade with a fast scale ramp on the incoming clip."""
    from moviepy.video.fx import CrossFadeIn, Resize

    out = [clips[0]]
    for c in clips[1:]:

        def scale(t):
            return zoom_blur_ramp(t, d)[0]

        out.append(c.with_effects([Resize(scale), CrossFadeIn(d)]))
    return concatenate_videoclips(out, method="compose", padding=-d)
