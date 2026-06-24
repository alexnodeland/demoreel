"""End-to-end smoke renders through the real pipeline (Playwright + ffmpeg/moviepy).

These are the only tests that drive a real Chromium and push frames through moviepy, so they
are marked ``browser`` + ``slow`` and excluded from the default ``pytest`` run. They render a
narration-free spec (no ``narrate`` keys) so no TTS engine / model download is needed, against
the static ``tests/fixtures/page.html`` over a ``file://`` URL (no live app, no network).

Each scene's ``goto`` carries the FULL ``file://`` URL: ``_resolve_url`` returns ``file:`` URLs
as-is, whereas a bare ``"/"`` would be appended to the top-level ``url`` and break.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from demoreel.render import render
from demoreel.spec import load_spec

pytestmark = [pytest.mark.browser, pytest.mark.slow]


def _base_spec(page_url: str, *, quality: str = "720p") -> dict:
    """A tiny, narration-free, headless spec: goto + click, then a highlight scene.

    A scene allows at most one primary action (``_at_most_one_action``), so the goto and the
    click live in separate scenes; the third scene is annotation-only (highlight, no action).
    """
    return {
        "title": "Smoke",
        "fps": 12,
        "headless": True,
        "quality": {"resolution": quality},
        "scenes": [
            {"name": "open", "goto": page_url, "hold": 0.3},
            {"name": "start", "click": "#start", "hold": 0.3},
            {"name": "install", "highlight": "#installation", "hold": 0.3},
        ],
    }


def _open_mp4(path: Path) -> tuple[int, int, int]:
    """Return (frame_count, width, height) from an mp4 via cv2 — counting decoded frames."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        assert cap.isOpened(), f"cv2 could not open {path}"
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        count = 0
        while True:
            ok, _frame = cap.read()
            if not ok:
                break
            count += 1
        return count, width, height
    finally:
        cap.release()


def test_basic_mp4_render(page_url, write_spec, tmp_path):
    """render() returns an existing, non-empty mp4 whose frames are the expected (OH, OW)."""
    spec_path = write_spec(_base_spec(page_url), name="smoke.yaml")
    out = tmp_path / "out.mp4"

    result = render(spec_path, output=out)

    assert isinstance(result, Path)
    assert result == out
    assert result.exists()
    assert result.stat().st_size > 0

    # Output frame size is exactly spec.output_size() (== quality.size); 720p -> (1280, 720).
    spec = load_spec(spec_path)
    ow, oh = spec.output_size()
    assert (ow, oh) == (1280, 720)

    count, width, height = _open_mp4(result)
    assert count > 0
    assert (width, height) == (ow, oh)

    # No narration -> no .srt is required; if any transcript/srt artifact exists it must be sane.
    srt = out.with_suffix(".srt")
    if srt.exists():
        assert srt.stat().st_size >= 0


def test_gif_extra_output(page_url, write_spec, tmp_path):
    """render(gif=True) also writes a non-empty animated GIF that PIL can open."""
    from PIL import Image

    spec_path = write_spec(_base_spec(page_url), name="smoke_gif.yaml")
    out = tmp_path / "out.mp4"

    render(spec_path, output=out, gif=True, gif_fps=8, gif_width=320)

    gif = out.with_suffix(".gif")
    assert gif.exists()
    assert gif.stat().st_size > 0

    with Image.open(gif) as im:
        assert im.format == "GIF"
        assert getattr(im, "is_animated", False)
        assert im.n_frames > 1


def test_player_extra_output(page_url, write_spec, tmp_path):
    """render(player=True) writes a self-contained player.html referencing the mp4."""
    spec_path = write_spec(_base_spec(page_url), name="smoke_player.yaml")
    out = tmp_path / "out.mp4"

    render(spec_path, output=out, player=True)

    player = out.with_suffix(".player.html")
    assert player.exists()
    html = player.read_text(encoding="utf-8")
    assert "<video" in html
    assert out.name in html  # the mp4 is referenced by relative filename


def test_device_frame_vertical_render(page_url, write_spec, tmp_path):
    """A phone-framed vertical spec renders without error at the vertical output size."""
    spec_dict = _base_spec(page_url, quality="vertical")
    spec_dict["viewport"] = [390, 844]
    spec_dict["frame"] = {"device": "phone"}
    spec_path = write_spec(spec_dict, name="smoke_phone.yaml")
    out = tmp_path / "out.mp4"

    result = render(spec_path, output=out)

    assert result.exists()
    assert result.stat().st_size > 0

    # `vertical` resolves to (1080, 1920): OW=1080, OH=1920 — the mp4 carries that size.
    spec = load_spec(spec_path)
    ow, oh = spec.output_size()
    assert (ow, oh) == (1080, 1920)

    count, width, height = _open_mp4(result)
    assert count > 0
    assert (width, height) == (ow, oh)
