"""Unit tests for the pure (no-browser) helpers in demoreel.capture.

Covers _resolve_url (URL joining), _clamp (range clamping), and _resolve_zoom
(camera zoom resolution incl. element-aware framing). None of these touch
Playwright, so the whole module imports and runs with only the always-on deps.
"""

from __future__ import annotations

import pytest

from demoreel.capture import _clamp, _resolve_url, _resolve_zoom
from demoreel.spec import CameraConfig, Scene

# --------------------------------------------------------------------------- _resolve_url


class TestResolveUrl:
    @pytest.mark.parametrize(
        "val",
        [
            "http://example.com/foo",
            "https://example.com/foo",
            "https://example.com",
            "file:///tmp/page.html",
            "about:blank",
        ],
    )
    def test_absolute_returned_as_is(self, val: str) -> None:
        # absolute http(s)/file/about URLs are passed through unchanged, base or not
        assert _resolve_url("https://base.test", val) == val
        assert _resolve_url(None, val) == val

    def test_relative_with_base_joins_single_slash(self) -> None:
        assert _resolve_url("https://example.com", "dashboard") == ("https://example.com/dashboard")

    def test_relative_with_base_no_double_slash(self) -> None:
        # base has a trailing slash AND val has a leading slash → exactly one slash
        assert _resolve_url("https://example.com/", "/dashboard") == (
            "https://example.com/dashboard"
        )

    def test_relative_with_base_trailing_slash_only(self) -> None:
        assert _resolve_url("https://example.com/", "dashboard") == (
            "https://example.com/dashboard"
        )

    def test_relative_with_base_leading_slash_only(self) -> None:
        assert _resolve_url("https://example.com", "/dashboard") == (
            "https://example.com/dashboard"
        )

    def test_relative_preserves_path_segments(self) -> None:
        assert _resolve_url("https://example.com/app", "/foo/bar") == (
            "https://example.com/app/foo/bar"
        )

    def test_relative_no_base_returned_as_is(self) -> None:
        assert _resolve_url(None, "dashboard") == "dashboard"
        assert _resolve_url("", "dashboard") == "dashboard"  # falsy base → as-is

    def test_empty_relative_with_base(self) -> None:
        # "" lstrip of "/" is "", base rstrip "/" + "/" + "" → trailing slash
        assert _resolve_url("https://example.com", "") == "https://example.com/"


# ------------------------------------------------------------------------------- _clamp


class TestClamp:
    def test_below_lo(self) -> None:
        assert _clamp(-5.0, 0.0, 10.0) == 0.0

    def test_above_hi(self) -> None:
        assert _clamp(99.0, 0.0, 10.0) == 10.0

    def test_within_range(self) -> None:
        assert _clamp(4.0, 0.0, 10.0) == 4.0

    def test_at_lo_boundary(self) -> None:
        assert _clamp(0.0, 0.0, 10.0) == 0.0

    def test_at_hi_boundary(self) -> None:
        assert _clamp(10.0, 0.0, 10.0) == 10.0

    def test_float_within(self) -> None:
        assert _clamp(1.488, 1.25, 2.6) == pytest.approx(1.488)


# ------------------------------------------------------------------------- _resolve_zoom


def _rect(cx: float, cy: float, w: float, h: float) -> dict:
    return {"cx": cx, "cy": cy, "w": w, "h": h}


# page dimensions used across the zoom tests
W, H = 1280, 720


class TestResolveZoom:
    def test_base_none_returns_none(self) -> None:
        # no_zoom scene → effective_zoom is None → result is None regardless of rect
        scene = Scene(focus="#x", no_zoom=True)
        cam = CameraConfig()
        assert _resolve_zoom(scene, cam, _rect(100, 100, 50, 50), W, H) is None

    def test_rect_none_returns_base(self) -> None:
        # focus point present + auto_zoom → effective_zoom is cam.zoom; rect None → return base
        scene = Scene(focus="#x")
        cam = CameraConfig(zoom=1.6)
        assert _resolve_zoom(scene, cam, None, W, H) == pytest.approx(1.6)

    def test_element_framing_small_rect_zooms_harder_than_large(self) -> None:
        scene = Scene(focus="#x")  # scene.zoom is None → element framing active
        cam = CameraConfig(framing="element")
        small = _resolve_zoom(scene, cam, _rect(100, 100, 40, 30), W, H)
        large = _resolve_zoom(scene, cam, _rect(100, 100, 900, 600), W, H)
        assert small > large

    def test_element_framing_clamped_to_max(self) -> None:
        # a tiny target wants a huge zoom → clamped to the 2.6 ceiling
        scene = Scene(focus="#x")
        cam = CameraConfig(framing="element")
        z = _resolve_zoom(scene, cam, _rect(100, 100, 10, 10), W, H)
        assert z == pytest.approx(2.6)

    def test_element_framing_clamped_to_min(self) -> None:
        # a giant target wants < 1.0 zoom → clamped up to the 1.25 floor
        scene = Scene(focus="#x")
        cam = CameraConfig(framing="element")
        z = _resolve_zoom(scene, cam, _rect(100, 100, 1200, 700), W, H)
        assert z == pytest.approx(1.25)

    def test_element_framing_within_range_uses_computed_value(self) -> None:
        # rect 400x300: z_w = 0.55*1280/400 = 1.76, z_h = 0.62*720/300 = 1.488
        # min(z_w, z_h) = 1.488, inside [1.25, 2.6] so returned uncapped.
        scene = Scene(focus="#x")
        cam = CameraConfig(framing="element")
        z = _resolve_zoom(scene, cam, _rect(100, 100, 400, 300), W, H)
        assert z == pytest.approx(1.488)

    def test_element_framing_takes_min_of_width_and_height(self) -> None:
        # very wide but short rect: width-driven zoom is small, height-driven is large;
        # the helper takes the smaller (width) so the whole element stays in frame.
        scene = Scene(focus="#x")
        cam = CameraConfig(framing="element")
        # rect 1000x120: z_w = 0.55*1280/1000 = 0.704, z_h = 0.62*720/120 = 3.72
        # min = 0.704 → clamped up to 1.25 (width constraint dominates)
        z = _resolve_zoom(scene, cam, _rect(100, 100, 1000, 120), W, H)
        assert z == pytest.approx(1.25)

    def test_explicit_scene_zoom_bypasses_element_framing(self) -> None:
        # scene.zoom set → effective_zoom returns it AND element-framing branch is skipped
        # (the `scene.zoom is None` guard fails), so the explicit value is returned as-is.
        scene = Scene(focus="#x", zoom=2.0)
        cam = CameraConfig(framing="element")
        z = _resolve_zoom(scene, cam, _rect(100, 100, 10, 10), W, H)
        assert z == pytest.approx(2.0)

    def test_point_framing_returns_base_unchanged(self) -> None:
        # framing == "point": ignore element size, return the configured base zoom
        scene = Scene(focus="#x")
        cam = CameraConfig(framing="point", zoom=1.6)
        z = _resolve_zoom(scene, cam, _rect(100, 100, 10, 10), W, H)
        assert z == pytest.approx(1.6)

    def test_zero_dim_rect_does_not_divide_by_zero(self) -> None:
        # max(rect_dim, 1.0) guards against zero-size rects; result still clamps to ceiling
        scene = Scene(focus="#x")
        cam = CameraConfig(framing="element")
        z = _resolve_zoom(scene, cam, _rect(100, 100, 0, 0), W, H)
        assert z == pytest.approx(2.6)
