"""Unit tests for demoreel.stage — pure colour/url helpers, background builders, and the
StageCompositor geometry (numpy/PIL/cv2 only; no browser, no ffmpeg).

The compositor's __init__ does all the framing math and then calls ``remap`` over the
capture's page-space camera track, so we feed it a hand-built CaptureResult + CameraTrack
(no Playwright needed) and assert the derived window/content geometry and coordinate map.
"""

from __future__ import annotations

import numpy as np
import pytest

from demoreel.capture import CaptureResult
from demoreel.keyframes import CameraTrack
from demoreel.spec import GradientBg
from demoreel.stage import (
    StageCompositor,
    _build_background,
    _clean_url,
    _gradient,
    _hex,
    _is_light,
)

# --------------------------------------------------------------------------- _hex


def test_hex_short_form_white():
    assert _hex("#fff") == (255, 255, 255)


def test_hex_full_form():
    assert _hex("#6C5CE7") == (108, 92, 231)


def test_hex_without_leading_hash():
    # _hex lstrips '#', so a bare hex works identically.
    assert _hex("6C5CE7") == (108, 92, 231)
    assert _hex("fff") == (255, 255, 255)


def test_hex_black_and_lowercase():
    assert _hex("#000000") == (0, 0, 0)
    assert _hex("#ffffff") == (255, 255, 255)


# --------------------------------------------------------------------------- _is_light


def test_is_light_light_gradient_true():
    bg = GradientBg(colors=["#FFFFFF", "#EEEEEE"])
    assert _is_light(bg) is True


def test_is_light_dark_gradient_false():
    bg = GradientBg(colors=["#0B0B12", "#10101A"])
    assert _is_light(bg) is False


def test_is_light_averages_stops_borderline_dark():
    # white luminance == 255, black == 0 → mean 127.5, which is NOT > 140.
    # This pins the "average all stops" behaviour (a first-stop-only impl would say True).
    bg = GradientBg(colors=["#FFFFFF", "#000000"])
    assert _is_light(bg) is False


def test_is_light_solid_hex_string_light():
    assert _is_light("#FFFFFF") is True


def test_is_light_solid_hex_string_dark():
    assert _is_light("#000000") is False


def test_is_light_non_hex_string_false():
    # A non-hex string (e.g. an image path) is treated as an image backdrop → dark chrome.
    assert _is_light("/some/backdrop.png") is False
    assert _is_light("backdrop.png") is False


def test_is_light_none_false():
    assert _is_light(None) is False


def test_is_light_mean_threshold_just_above():
    # A pair whose mean luminance clears 140 → light. Two identical mid-grey stops at
    # luminance == 150 (gray 150,150,150 → 0.299*150+0.587*150+0.114*150 == 150).
    bg = GradientBg(colors=["#969696", "#969696"])  # 0x96 == 150
    assert _is_light(bg) is True


# --------------------------------------------------------------------------- _clean_url


def test_clean_url_strips_scheme():
    assert _clean_url("https://example.com") == "example.com"
    assert _clean_url("http://example.com") == "example.com"


def test_clean_url_strips_query():
    assert _clean_url("https://example.com/x?foo=bar&baz=1") == "example.com/x"


def test_clean_url_long_users_path_localhost():
    url = "file:///Users/alex/projects/demo/engine/tests/fixtures/page.html"
    assert _clean_url(url) == "localhost"


def test_clean_url_private_path_localhost():
    url = "file:///private/tmp/build/page.html"
    assert _clean_url(url) == "localhost"


def test_clean_url_many_segments_localhost():
    # More than 4 slashes (post-scheme) collapses to localhost even without /Users//private.
    assert _clean_url("https://host/a/b/c/d/e/f") == "localhost"


def test_clean_url_simple_host_path_kept():
    assert _clean_url("example.com/x") == "example.com/x"


def test_clean_url_trailing_slash_trimmed():
    assert _clean_url("https://example.com/") == "example.com"


def test_clean_url_bare_root_becomes_localhost():
    # 'https://example.com' minus scheme is 'example.com'; but a path that rstrips to empty
    # falls back to 'localhost'. 'http://localhost/' → 'localhost' (root slash trimmed).
    assert _clean_url("http://localhost/") == "localhost"


# --------------------------------------------------------------------------- backgrounds


def test_build_background_solid_hex_shape_and_fill():
    h, w = 40, 60
    arr = _build_background("#6C5CE7", w, h)
    assert arr.shape == (h, w, 3)
    assert arr.dtype == np.uint8
    # Solid fill: every pixel is the same colour.
    assert np.array_equal(arr[0, 0], np.array([108, 92, 231], dtype=np.uint8))
    assert (arr == arr[0, 0]).all()


def test_build_background_none_is_default_dark():
    h, w = 12, 20
    arr = _build_background(None, w, h)
    assert arr.shape == (h, w, 3)
    assert arr.dtype == np.uint8
    assert np.array_equal(arr[0, 0], np.array([11, 11, 18], dtype=np.uint8))
    assert (arr == arr[0, 0]).all()


def test_build_background_gradient_shape_and_endpoints():
    h, w = 30, 80
    bg = GradientBg(colors=["#000000", "#FFFFFF"], angle=0.0)
    arr = _build_background(bg, w, h)
    assert arr.shape == (h, w, 3)
    assert arr.dtype == np.uint8
    # angle 0 → horizontal gradient: left edge near black, right edge near white.
    assert int(arr[0, 0].mean()) < 5
    assert int(arr[0, -1].mean()) > 250


def test_gradient_shape_dtype():
    h, w = 50, 70
    arr = _gradient(["#101020", "#202040"], 135.0, w, h)
    assert arr.shape == (h, w, 3)
    assert arr.dtype == np.uint8


def test_gradient_equal_colors_uniform():
    h, w = 16, 16
    arr = _gradient(["#123456", "#123456"], 90.0, w, h)
    assert arr.shape == (h, w, 3)
    # Both stops identical → uniform field of that colour.
    assert np.array_equal(arr[0, 0], np.array(_hex("#123456"), dtype=np.uint8))
    assert (arr == arr[0, 0]).all()


# --------------------------------------------------------------------------- compositor


def _make_capture(page_w=1600, page_h=900) -> CaptureResult:
    """A minimal CaptureResult with a one-keyframe page-space camera track."""
    cam = CameraTrack(page_w, page_h)
    cam.add(0.0, 1.0, page_w / 2, page_h / 2)
    return CaptureResult(
        video_path="raw.webm",
        page_w=page_w,
        page_h=page_h,
        video_w=page_w,
        video_h=page_h,
        duration=1.0,
        scenes=[],
        camera=cam,
        page_url="file:///Users/alex/x/page.html",
    )


def test_compositor_output_size(make_spec):
    spec = make_spec(quality={"resolution": [640, 360]})
    cap = _make_capture()
    comp = StageCompositor(spec, cap)
    assert (comp.OW, comp.OH) == (640, 360)


def test_compositor_window_centered(make_spec):
    spec = make_spec(quality={"resolution": [640, 360]})
    cap = _make_capture()
    comp = StageCompositor(spec, cap)
    assert comp.win_x >= 0
    assert comp.win_y >= 0
    win_w = comp.cw
    win_h = comp.ch + comp.chrome_h
    # Centered to within a pixel on both axes (integer // can leave a 1px asymmetry).
    assert abs(comp.win_x - (comp.OW - comp.win_x - win_w)) <= 1
    assert abs(comp.win_y - (comp.OH - comp.win_y - win_h)) <= 1


def test_compositor_page_to_stage_corners(make_spec):
    spec = make_spec(quality={"resolution": [640, 360]})
    cap = _make_capture()
    comp = StageCompositor(spec, cap)

    # (0,0) maps to the content rect's top-left corner.
    x0, y0 = comp.page_to_stage(0, 0)
    assert x0 == pytest.approx(comp.content_x)
    assert y0 == pytest.approx(comp.content_y)

    # (page_w, page_h) maps to the content rect's far (bottom-right) corner.
    x1, y1 = comp.page_to_stage(cap.page_w, cap.page_h)
    assert x1 == pytest.approx(comp.content_x + comp.cw)
    assert y1 == pytest.approx(comp.content_y + comp.ch)

    # The mapped points sit inside the output frame and inside the content rect bounds.
    assert 0 <= x0 < x1 <= comp.OW
    assert 0 <= y0 < y1 <= comp.OH


def test_compositor_scale_factors_positive(make_spec):
    spec = make_spec(quality={"resolution": [640, 360]})
    cap = _make_capture()
    comp = StageCompositor(spec, cap)
    assert comp.sx > 0
    assert comp.sy > 0
    # sx, sy are content-pixels-per-page-pixel; with a smaller output they are < 1.
    assert comp.sx == pytest.approx(comp.cw / cap.page_w)
    assert comp.sy == pytest.approx(comp.ch / cap.page_h)


def test_compositor_content_inside_window(make_spec):
    spec = make_spec(quality={"resolution": [640, 360]})
    cap = _make_capture()
    comp = StageCompositor(spec, cap)
    # Content starts at the window's x and is pushed below the chrome bar.
    assert comp.content_x == comp.win_x
    assert comp.content_y == comp.win_y + comp.chrome_h
    # Content rect fits within the output frame.
    assert comp.content_x + comp.cw <= comp.OW
    assert comp.content_y + comp.ch <= comp.OH


def test_compositor_remaps_camera_into_stage_space(make_spec):
    spec = make_spec(quality={"resolution": [640, 360]})
    cap = _make_capture()
    comp = StageCompositor(spec, cap)
    # The page-space centre keyframe should be remapped through page_to_stage.
    kf = comp.camera.keyframes[0]
    exp_x, exp_y = comp.page_to_stage(cap.page_w / 2, cap.page_h / 2)
    assert kf.cx == pytest.approx(exp_x)
    assert kf.cy == pytest.approx(exp_y)
    assert kf.zoom == pytest.approx(1.0)
