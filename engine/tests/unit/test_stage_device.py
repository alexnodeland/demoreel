"""Unit tests for demoreel.stage device-frame geometry + the opaque window panel.

Two things are exercised here, both with numpy/PIL only (no browser, no ffmpeg):

1. The phone/tablet device shells: ``StageCompositor`` swaps the macOS browser chrome for a
   bezel + notch/home foreground layer. We assert the bezel/radius geometry, the foreground
   alpha split (``_fg_a``), and that the page content rect fits inside the device body.

2. The opaque window panel — the "hero fix". ``_window_layer`` paints a solid panel behind the
   page so an app with a transparent/glassy background can't let the dark backdrop bleed through.
   We prove the panel is opaque by checking ``stage_base`` (the static layer, before any page is
   composited) at the window centre differs from the backdrop corner, and that a dark opaque page
   composites cleanly through ``frame``.

The compositor is hand-built from a synthetic CaptureResult + one-keyframe CameraTrack, so no
Playwright is needed. ``frame`` lazily imports cv2 (always available in the unit env).
"""

from __future__ import annotations

import numpy as np

from demoreel.capture import CaptureResult
from demoreel.keyframes import CameraTrack
from demoreel.spec import DemoSpec
from demoreel.stage import StageCompositor


def _build(vw: int, vh: int, res: str, dev: str) -> StageCompositor:
    """Construct a StageCompositor with the given viewport, output resolution, and device.

    page_w/page_h are taken from the viewport (as the live pipeline does), so the page aspect
    matches the requested device/resolution pairing.
    """
    spec = DemoSpec.model_validate(
        {
            "url": "https://x",
            "scenes": [{"goto": "/"}],
            "viewport": [vw, vh],
            "quality": {"resolution": res},
            "frame": {"device": dev},
        }
    )
    cam = CameraTrack(vw, vh)
    cam.add(0.0, 1.0, vw / 2, vh / 2)
    cap = CaptureResult(
        video_path="raw.webm",
        page_w=vw,
        page_h=vh,
        video_w=vw,
        video_h=vh,
        duration=1.0,
        scenes=[],
        camera=cam,
    )
    return StageCompositor(spec, cap)


def _flat_page(vh: int, vw: int, value):
    """A get_frame callable returning a solid HxWx3 uint8 RGB page at the capture size."""

    def _get(_t: float) -> np.ndarray:
        return np.full((vh, vw, 3), value, np.uint8)

    return _get


# --------------------------------------------------------------------------- phone


def test_phone_geometry_and_foreground():
    sc = _build(390, 844, "vertical", "phone")

    # device path → bezel furniture and a foreground notch/home layer.
    assert sc.device == "phone"
    assert sc.bezel > 0
    assert sc._fg_a is not None
    assert sc._fg_rgb is not None
    # the foreground alpha split is normalized to [0, 1] and matches the output frame shape.
    assert sc._fg_a.shape == (sc.OH, sc.OW, 1)
    assert float(sc._fg_a.min()) >= 0.0
    assert float(sc._fg_a.max()) <= 1.0
    # the notch/home indicator actually marks some pixels opaque.
    assert float(sc._fg_a.max()) > 0.0

    # content sits inside the bezel: at least one bezel-width in from the body's left edge.
    assert sc.content_x >= sc.win_x + sc.bezel
    assert sc.content_y >= sc.win_y + sc.bezel
    # and the whole content rect fits within the device body box.
    assert sc.content_x + sc.cw <= sc.win_x + sc.win_w
    assert sc.content_y + sc.ch <= sc.win_y + sc.win_h

    # radii: a rounded body, with the screen corners tucked one bezel inside (and non-negative).
    assert sc.body_radius > sc.screen_radius >= 0
    assert sc.screen_radius == max(0, sc.body_radius - sc.bezel)


def test_phone_frame_output_shape():
    sc = _build(390, 844, "vertical", "phone")
    out = sc.frame(_flat_page(844, 390, 200), 0.0)
    assert out.shape == (sc.OH, sc.OW, 3)
    assert out.dtype == np.uint8


def test_phone_no_browser_chrome_bar():
    # a device draws its own status furniture; the browser chrome bar is suppressed.
    sc = _build(390, 844, "vertical", "phone")
    assert sc.chrome_h == 0
    # window box is exactly the content plus a bezel on every side (no chrome height added).
    assert sc.win_w == sc.cw + 2 * sc.bezel
    assert sc.win_h == sc.ch + 2 * sc.bezel


# --------------------------------------------------------------------------- tablet


def test_tablet_geometry_and_foreground():
    sc = _build(820, 1180, "portrait", "tablet")

    assert sc.device == "tablet"
    assert sc.bezel > 0
    assert sc._fg_a is not None
    assert sc._fg_rgb is not None
    assert sc.content_x >= sc.win_x + sc.bezel
    assert sc.content_x + sc.cw <= sc.win_x + sc.win_w
    assert sc.body_radius > sc.screen_radius >= 0
    assert sc.screen_radius == max(0, sc.body_radius - sc.bezel)


def test_tablet_body_radius_relatively_smaller_than_phone():
    # _radii uses 0.085 * min(win) for a phone vs 0.045 for a tablet — a tablet's corners are
    # relatively rounder-but-shallower. Compare as a fraction of the body's short side so the
    # difference is the corner *style*, not just absolute pixel counts at different sizes.
    phone = _build(390, 844, "vertical", "phone")
    tablet = _build(820, 1180, "portrait", "tablet")
    phone_frac = phone.body_radius / min(phone.win_w, phone.win_h)
    tablet_frac = tablet.body_radius / min(tablet.win_w, tablet.win_h)
    assert tablet_frac < phone_frac


def test_tablet_frame_output_shape():
    sc = _build(820, 1180, "portrait", "tablet")
    out = sc.frame(_flat_page(1180, 820, 128), 0.0)
    assert out.shape == (sc.OH, sc.OW, 3)
    assert out.dtype == np.uint8


# --------------------------------------------------------------------------- browser (none)


def test_browser_path_unchanged():
    sc = _build(1600, 900, "1080p", "none")

    # the unchanged browser path: no bezel, no device foreground layer.
    assert sc.device == "none"
    assert sc.bezel == 0
    assert sc._fg_a is None
    assert sc._fg_rgb is None
    # browser chrome bar is present (default frame.chrome == "browser", studio style).
    assert sc.chrome_h > 0
    # with no bezel the content origin equals the window origin (offset only by the chrome bar).
    assert sc.content_x == sc.win_x
    assert sc.content_y == sc.win_y + sc.chrome_h


def test_browser_frame_output_shape():
    sc = _build(1600, 900, "1080p", "none")
    out = sc.frame(_flat_page(900, 1600, 180), 0.0)
    assert out.shape == (sc.OH, sc.OW, 3)
    assert out.dtype == np.uint8


# --------------------------------------------------------------------------- _radii


def test_radii_none_screen_equals_body():
    # for the browser path _radii returns (fc.radius, fc.radius) — screen == body, no bezel inset.
    sc = _build(1600, 900, "1080p", "none")
    assert sc.body_radius == sc.screen_radius
    assert sc.body_radius == sc.spec.frame.radius


# --------------------------------------------------------------------------- opaque panel


def test_window_panel_is_opaque_not_backdrop():
    # The hero fix: _window_layer paints a solid body so the dark backdrop can't bleed through a
    # transparent app. Prove it on the STATIC layer (stage_base), before any page is composited:
    # the window centre must NOT read as the backdrop corner colour.
    sc = _build(1600, 900, "1080p", "none")

    backdrop_corner = sc.stage_base[5, 5]
    win_center = sc.stage_base[sc.content_y + sc.ch // 2, sc.content_x + sc.cw // 2]
    assert not np.array_equal(win_center, backdrop_corner)


def test_dark_page_composites_through_to_center():
    # Feed a DARK opaque page; the composited output's content centre should read as that page
    # colour (the mask is fully opaque away from the rounded corners), proving the page — not the
    # panel — fills the interior once a frame is drawn.
    sc = _build(1600, 900, "1080p", "none")
    page_col = (13, 13, 20)
    out = sc.frame(_flat_page(900, 1600, page_col), 0.0)

    cy = sc.content_y + sc.ch // 2
    cx = sc.content_x + sc.cw // 2
    center = out[cy, cx].astype(int)
    # resize of a flat field is exact; allow a hair for uint8/float round-trip in the blend.
    assert np.all(np.abs(center - np.array(page_col, dtype=int)) <= 1)


def test_panel_distinct_from_backdrop_under_default_dark_backdrop():
    # The default (no background) backdrop is the dark (11, 11, 18); the dark panel is (16, 16, 22).
    # They are close but deliberately distinct, so the opaque panel is visible against the
    # backdrop even in the all-dark case.
    sc = _build(1600, 900, "1080p", "none")
    backdrop_corner = sc.stage_base[5, 5].astype(int)
    win_center = sc.stage_base[sc.content_y + sc.ch // 2, sc.content_x + sc.cw // 2].astype(int)
    # not the default-dark backdrop colour...
    assert not np.array_equal(backdrop_corner, np.array([16, 16, 22]))
    # ...and the panel centre is strictly brighter than that backdrop (16,16,22 > 11,11,18).
    assert int(win_center.sum()) > int(backdrop_corner.sum())
