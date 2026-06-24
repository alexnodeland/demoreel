"""Unit tests for the pure (no-ffmpeg/cv2) core of demoreel.export.

Exercises frames_to_gif / frames_to_webp on small synthetic in-memory RGB frame
lists, plus the frame-sampling/resize math helpers. The mp4_* wrappers are NOT
called here — they need cv2 + a real video — so the whole module runs in the
default suite with only the always-on deps (numpy, Pillow).
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from demoreel.export import (
    _sample_step,
    _target_size,
    frames_to_gif,
    frames_to_webp,
)


def _frames(n: int, w: int = 16, h: int = 16) -> list[np.ndarray]:
    """n distinct HxWx3 uint8 RGB frames (each a different solid-ish color)."""
    out: list[np.ndarray] = []
    for i in range(n):
        f = np.zeros((h, w, 3), dtype=np.uint8)
        f[:, :, 0] = (i * 40) % 256  # vary so frames are not identical
        f[:, :, 1] = (i * 17) % 256
        f[: h // 2, :, 2] = 255  # a fixed colored band → real palette content
        out.append(f)
    return out


# ----------------------------------------------------------------------- frames_to_gif


class TestFramesToGif:
    def test_writes_animated_gif(self, tmp_path) -> None:
        frames = _frames(4)
        out = frames_to_gif(frames, tmp_path / "out.gif")
        assert out == tmp_path / "out.gif"
        assert out.exists()
        with Image.open(out) as im:
            assert im.format == "GIF"
            assert im.is_animated
            assert im.n_frames == len(frames)
            assert im.size == (16, 16)

    def test_returns_path_for_str_arg(self, tmp_path) -> None:
        # accepts a str out_path and still returns a Path
        out = frames_to_gif(_frames(2), str(tmp_path / "s.gif"))
        from pathlib import Path

        assert isinstance(out, Path)
        assert out.exists()

    def test_empty_frames_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="empty"):
            frames_to_gif([], tmp_path / "x.gif")

    def test_single_frame(self, tmp_path) -> None:
        out = frames_to_gif(_frames(1), tmp_path / "one.gif")
        with Image.open(out) as im:
            assert im.n_frames == 1

    def test_loop_default_is_infinite(self, tmp_path) -> None:
        # loop=0 → infinite loop; Pillow surfaces it as info['loop'] == 0
        out = frames_to_gif(_frames(3), tmp_path / "loop0.gif")
        with Image.open(out) as im:
            assert im.info.get("loop") == 0

    def test_loop_finite_count(self, tmp_path) -> None:
        out = frames_to_gif(_frames(3), tmp_path / "loop2.gif", loop=2)
        with Image.open(out) as im:
            assert im.info.get("loop") == 2

    def test_duration_reflects_fps(self, tmp_path) -> None:
        # fps=10 → duration round(1000/10) == 100ms per frame
        out = frames_to_gif(_frames(3), tmp_path / "d.gif", fps=10)
        with Image.open(out) as im:
            assert im.info.get("duration") == 100

    def test_duration_rounds(self, tmp_path) -> None:
        # fps=15 → round(1000/15) == 67ms (GIF stores centiseconds, so expect 60 or 70)
        out = frames_to_gif(_frames(2), tmp_path / "r.gif", fps=15)
        with Image.open(out) as im:
            assert im.info.get("duration") in (60, 70)

    def test_size_matches_input_frames(self, tmp_path) -> None:
        out = frames_to_gif(_frames(3, w=32, h=24), tmp_path / "sz.gif")
        with Image.open(out) as im:
            assert im.size == (32, 24)


# ---------------------------------------------------------------------- frames_to_webp


class TestFramesToWebp:
    def test_writes_animated_webp(self, tmp_path) -> None:
        frames = _frames(4)
        out = frames_to_webp(frames, tmp_path / "out.webp")
        assert out == tmp_path / "out.webp"
        assert out.exists()
        with Image.open(out) as im:
            assert im.format == "WEBP"
            assert im.is_animated
            assert im.n_frames == len(frames)
            assert im.size == (16, 16)

    def test_empty_frames_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="empty"):
            frames_to_webp([], tmp_path / "x.webp")

    def test_single_frame(self, tmp_path) -> None:
        # a 1-frame WebP is a still image; Pillow reports n_frames == 1
        out = frames_to_webp(_frames(1), tmp_path / "one.webp")
        with Image.open(out) as im:
            assert im.n_frames == 1

    def test_loop_finite_count(self, tmp_path) -> None:
        out = frames_to_webp(_frames(3), tmp_path / "loop3.webp", loop=3)
        with Image.open(out) as im:
            assert im.info.get("loop") == 3

    def test_fps_does_not_change_frame_count(self, tmp_path) -> None:
        # (Pillow's WebP reader doesn't surface per-frame duration in info, so we assert
        # the observable invariant: fps controls playback speed, not the frame count.)
        slow = frames_to_webp(_frames(5), tmp_path / "slow.webp", fps=5)
        fast = frames_to_webp(_frames(5), tmp_path / "fast.webp", fps=30)
        for p in (slow, fast):
            with Image.open(p) as im:
                assert im.n_frames == 5

    def test_size_matches_input_frames(self, tmp_path) -> None:
        out = frames_to_webp(_frames(3, w=20, h=40), tmp_path / "sz.webp")
        with Image.open(out) as im:
            assert im.size == (20, 40)

    def test_quality_param_accepted(self, tmp_path) -> None:
        # low and high quality both produce a valid animated file
        lo = frames_to_webp(_frames(3), tmp_path / "lo.webp", quality=10)
        hi = frames_to_webp(_frames(3), tmp_path / "hi.webp", quality=95)
        for p in (lo, hi):
            with Image.open(p) as im:
                assert im.n_frames == 3


# ------------------------------------------------------------------------- _sample_step


class TestSampleStep:
    def test_downsample_halves(self) -> None:
        assert _sample_step(30.0, 15) == 2

    def test_downsample_rounds(self) -> None:
        # 25 → 15 wants 1.67, rounds to 2
        assert _sample_step(25.0, 15) == 2

    def test_source_below_target_keeps_every_frame(self) -> None:
        # never upsample: source slower than target → step 1
        assert _sample_step(10.0, 15) == 1

    def test_source_equals_target(self) -> None:
        assert _sample_step(15.0, 15) == 1

    def test_zero_src_fps_defaults_to_one(self) -> None:
        assert _sample_step(0.0, 15) == 1

    def test_zero_target_fps_defaults_to_one(self) -> None:
        assert _sample_step(30.0, 0) == 1

    def test_high_ratio(self) -> None:
        assert _sample_step(60.0, 15) == 4


# ------------------------------------------------------------------------- _target_size


class TestTargetSize:
    def test_preserves_aspect(self) -> None:
        # 1920x1080 → width 720 → height 720*1080/1920 = 405 → even → 404
        assert _target_size(1920, 1080, 720) == (720, 404)

    def test_height_is_even(self) -> None:
        _, h = _target_size(1000, 1001, 720)
        assert h % 2 == 0

    def test_square_input(self) -> None:
        assert _target_size(500, 500, 200) == (200, 200)

    def test_portrait_input(self) -> None:
        # 600x900 → width 300 → height 450 (already even)
        assert _target_size(600, 900, 300) == (300, 450)

    def test_width_floored_to_two(self) -> None:
        w, h = _target_size(100, 100, 0)
        assert w == 2
        assert h >= 2

    def test_zero_source_dims_fall_back_to_square(self) -> None:
        # degenerate source → square width x width (guards the divide)
        assert _target_size(0, 0, 480) == (480, 480)

    def test_height_never_below_two(self) -> None:
        # extreme wide-short source → height would round to 0, floored to 2
        _w, h = _target_size(10000, 1, 720)
        assert h >= 2
