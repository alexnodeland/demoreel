"""Unit tests for demoreel.swatch — logo-derived brand colors.

The pure core operates on synthetic PIL images (solid blocks, half/half splits, a
transparent region) built in tmp_path and on plain hex lists — no real logo, no network.
We pin: valid '#rrggbb' output, population ordering, the vividness gate in pick_accent
(skip white/black/grey, fall back to the neutral accent), the dark-background invariant of
palette_from_logo, FileNotFoundError on a missing path, and each pure helper directly.
"""

from __future__ import annotations

import pytest
from PIL import Image

from demoreel.swatch import (
    FALLBACK_ACCENT,
    _darken,
    _hex,
    _hex_to_rgb,
    _luma,
    _saturation,
    dominant_colors,
    palette_from_logo,
    pick_accent,
)

INDIGO = (108, 92, 231)  # #6c5ce7
INDIGO_HEX = "#6c5ce7"
HEX_RE = r"^#[0-9a-f]{6}$"


# --------------------------------------------------------------------------- #
# image factories
# --------------------------------------------------------------------------- #


def _solid(tmp_path, color, size=(64, 64), name="solid.png"):
    path = tmp_path / name
    Image.new("RGB", size, color).save(path)
    return path


def _half_half(tmp_path, left, right, size=(64, 64), name="half.png"):
    img = Image.new("RGB", size, left)
    img.paste(Image.new("RGB", (size[0] // 2, size[1]), right), (size[0] // 2, 0))
    img.save(path := tmp_path / name)
    return path


def _with_transparent_region(tmp_path, color, size=(64, 64), name="alpha.png"):
    # Left half is opaque `color`, right half is fully transparent.
    img = Image.new("RGBA", size, (*color, 255))
    img.paste(Image.new("RGBA", (size[0] // 2, size[1]), (0, 0, 0, 0)), (size[0] // 2, 0))
    img.save(path := tmp_path / name)
    return path


# --------------------------------------------------------------------------- #
# dominant_colors
# --------------------------------------------------------------------------- #


def test_dominant_colors_returns_valid_hex(tmp_path):
    colors = dominant_colors(_solid(tmp_path, INDIGO))
    assert colors  # non-empty
    for c in colors:
        assert isinstance(c, str)
        import re

        assert re.match(HEX_RE, c), c


def test_dominant_colors_solid_block_is_that_color(tmp_path):
    colors = dominant_colors(_solid(tmp_path, INDIGO))
    # A solid block quantizes to a single (near-exact) stop at the front.
    assert _close(_hex_to_rgb(colors[0]), INDIGO, tol=4)


def test_dominant_colors_known_color_near_front(tmp_path):
    # 75% indigo / 25% white → indigo must dominate and sit at the front.
    img = Image.new("RGB", (80, 64), INDIGO)
    img.paste(Image.new("RGB", (20, 64), (255, 255, 255)), (60, 0))
    img.save(p := tmp_path / "mostly_indigo.png")
    colors = dominant_colors(p)
    # The most populous color is the indigo, within a couple of front positions.
    front = [c for c in colors[:2]]
    assert any(_close(_hex_to_rgb(c), INDIGO, tol=12) for c in front)


def test_dominant_colors_respects_k(tmp_path):
    # An image with several distinct bands should not exceed k palette stops.
    img = Image.new("RGB", (100, 20))
    bands = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30), (30, 200, 200)]
    for i, c in enumerate(bands):
        img.paste(Image.new("RGB", (20, 20), c), (i * 20, 0))
    img.save(p := tmp_path / "bands.png")
    colors = dominant_colors(p, k=3)
    assert len(colors) <= 3


def test_dominant_colors_ignores_transparent_region(tmp_path):
    # Half opaque indigo, half fully transparent → indigo wins; the transparent canvas
    # (which composites to white) must not push white to the front.
    p = _with_transparent_region(tmp_path, INDIGO)
    colors = dominant_colors(p)
    assert _close(_hex_to_rgb(colors[0]), INDIGO, tol=12)
    # White should not be the dominant color despite covering half the canvas.
    assert not _close(_hex_to_rgb(colors[0]), (255, 255, 255), tol=12)


def test_dominant_colors_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        dominant_colors(tmp_path / "does-not-exist.png")


def test_dominant_colors_k_one_returns_single(tmp_path):
    colors = dominant_colors(_half_half(tmp_path, INDIGO, (10, 200, 120)), k=1)
    assert len(colors) == 1


# --------------------------------------------------------------------------- #
# pick_accent
# --------------------------------------------------------------------------- #


def test_pick_accent_returns_vivid_color():
    colors = ["#ffffff", "#000000", "#6c5ce7", "#10b981"]
    # Population-ordered: white and black are skipped; first vivid survivor wins.
    assert pick_accent(colors) == "#6c5ce7"


def test_pick_accent_skips_white_black_grey():
    colors = ["#fefefe", "#020202", "#808080", "#e11d48"]
    # near-white, near-black, mid grey skipped → the vivid red.
    assert pick_accent(colors) == "#e11d48"


def test_pick_accent_prefers_first_vivid_not_most_saturated():
    # Two vivid colors; the FIRST (population-ordered) wins even if the second is purer.
    colors = ["#6c5ce7", "#ff0000"]
    assert pick_accent(colors) == "#6c5ce7"


def test_pick_accent_all_grey_falls_back():
    colors = ["#ffffff", "#000000", "#7f7f7f", "#b0b0b0"]
    assert pick_accent(colors) == FALLBACK_ACCENT


def test_pick_accent_empty_falls_back():
    assert pick_accent([]) == FALLBACK_ACCENT


def test_pick_accent_no_vivid_uses_most_saturated_fallback():
    # All fail the vividness gate (too dark), but they carry hue, so the most-saturated
    # survivor is returned rather than the neutral fallback.
    colors = ["#0a0500", "#050a00"]  # very dark but tinted (luma < 25)
    out = pick_accent(colors)
    assert out in colors


def test_pick_accent_pure_grey_only_falls_back_to_neutral():
    # Zero-saturation greys give no most-saturated candidate → neutral fallback.
    assert pick_accent(["#404040", "#606060"]) == FALLBACK_ACCENT


# --------------------------------------------------------------------------- #
# palette_from_logo
# --------------------------------------------------------------------------- #


def test_palette_from_logo_shape_and_dark_background(tmp_path):
    out = palette_from_logo(_solid(tmp_path, INDIGO))
    assert set(out.keys()) == {"accent", "background", "colors"}
    import re

    assert re.match(HEX_RE, out["accent"])
    assert isinstance(out["background"], list) and len(out["background"]) == 2
    for stop in out["background"]:
        assert re.match(HEX_RE, stop)
        assert _luma(_hex_to_rgb(stop)) < 90  # readable Studio backdrop stays dark
    assert isinstance(out["colors"], list) and out["colors"]


def test_palette_from_logo_accent_matches_pick_accent(tmp_path):
    p = _solid(tmp_path, INDIGO)
    out = palette_from_logo(p)
    assert out["accent"] == pick_accent(dominant_colors(p))


def test_palette_from_logo_background_descends(tmp_path):
    # The gradient's second stop is darker than (or equal to) the first.
    out = palette_from_logo(_solid(tmp_path, INDIGO))
    top, bottom = out["background"]
    assert _luma(_hex_to_rgb(bottom)) <= _luma(_hex_to_rgb(top))


def test_palette_from_logo_white_logo_falls_back_but_stays_dark(tmp_path):
    out = palette_from_logo(_solid(tmp_path, (255, 255, 255)))
    assert out["accent"] == FALLBACK_ACCENT
    for stop in out["background"]:
        assert _luma(_hex_to_rgb(stop)) < 90


def test_palette_from_logo_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        palette_from_logo(tmp_path / "nope.png")


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #


def test_hex_roundtrip():
    assert _hex((108, 92, 231)) == "#6c5ce7"
    assert _hex_to_rgb("#6c5ce7") == (108, 92, 231)
    # Round-trips through both directions.
    assert _hex(_hex_to_rgb("#10b981")) == "#10b981"


def test_hex_clamps_out_of_range():
    assert _hex((-5, 300, 128)) == "#00ff80"


def test_hex_rounds_floats():
    # The gradient path feeds floats in; _hex must round, not truncate.
    assert _hex((1.6, 1.4, 254.5)) == _hex((2, 1, 254))


def test_hex_to_rgb_short_form():
    assert _hex_to_rgb("#fff") == (255, 255, 255)
    assert _hex_to_rgb("f00") == (255, 0, 0)  # leading '#' optional


def test_luma_extremes():
    assert _luma((0, 0, 0)) == 0.0
    assert _luma((255, 255, 255)) == pytest.approx(255.0)
    # Green is perceptually brightest of the primaries.
    assert _luma((0, 255, 0)) > _luma((255, 0, 0)) > _luma((0, 0, 255))


def test_saturation_grey_is_zero_pure_is_one():
    assert _saturation((128, 128, 128)) == 0.0
    assert _saturation((255, 0, 0)) == pytest.approx(1.0)
    assert _saturation((0, 0, 0)) == 0.0  # black has no saturation


def test_darken_factors():
    assert _darken("#646464", 0.5) == "#323232"
    assert _darken("#ffffff", 0.0) == "#000000"  # factor 0 → black
    assert _darken("#abcdef", 1.0) == "#abcdef"  # factor 1 → unchanged


def test_darken_clamps_factor():
    # Out-of-range factors clamp to [0, 1].
    assert _darken("#646464", -1.0) == "#000000"
    assert _darken("#646464", 2.0) == "#646464"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=False))
