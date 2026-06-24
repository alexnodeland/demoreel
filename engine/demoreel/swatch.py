"""Derive brand colors from a logo image so a demo can be themed straight from a logo.

Open a logo, quantize it to an adaptive palette, and pick the most brand-vivid accent
(skipping the near-white / near-black / grey that dominate most logos). `palette_from_logo`
composes that into a drop-in theme dict — an accent plus a dark gradient pair tinted from it
— so the whole Studio backdrop reads as one piece. The accent/background math is pure (it
operates on hex strings) and is what the unit suite exercises without touching a real image.
"""

from __future__ import annotations

import colorsys
from pathlib import Path

from PIL import Image

# Studio backdrops must stay dark for legibility; this is the neutral indigo fallback used
# when a logo yields no usable accent (matches the `studio` preset accent in themes.py).
FALLBACK_ACCENT = "#6C5CE7"

# Vividness gates for pick_accent — luma is 0..255, saturation is 0..1.
_WHITE_LUMA = 235.0
_BLACK_LUMA = 25.0
_MIN_SAT = 0.25


def dominant_colors(image_path: str | Path, k: int = 6) -> list[str]:
    """Top-k dominant colors of an image as population-ordered '#rrggbb' hex strings.

    Flattens RGBA over white, downscales for speed, and quantizes to an adaptive palette.
    Fully-transparent pixels are ignored so a logo's empty canvas never wins.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    img = Image.open(path)
    return _dominant_colors_from_image(img, k)


def _dominant_colors_from_image(img: Image.Image, k: int = 6) -> list[str]:
    """Pure-ish core of dominant_colors operating on an already-opened PIL image."""
    k = max(1, k)
    img = _downscale(img, 128)
    alpha = _alpha_mask(img)
    rgb = _flatten_to_rgb(img)

    # ADAPTIVE palette = median-cut; the resulting palette image's color counts give us a
    # population order for free.
    pal = rgb.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
    palette = pal.getpalette() or []
    counts = _palette_counts(pal, alpha)

    out: list[str] = []
    seen: set[str] = set()
    for _count, idx in counts:
        base = idx * 3
        rgb_triple = (palette[base], palette[base + 1], palette[base + 2])
        hex_str = _hex(rgb_triple)
        if hex_str not in seen:  # MEDIANCUT can repeat a stop on flat images
            seen.add(hex_str)
            out.append(hex_str)
    return out


def pick_accent(colors: list[str]) -> str:
    """Choose the most brand-vivid accent from a population-ordered hex list.

    Skips near-white, near-black, and low-saturation greys; prefers the first survivor (the
    input is population-ordered). Falls back to the most saturated color overall, then to the
    neutral FALLBACK_ACCENT when nothing qualifies.
    """
    rgbs = [_hex_to_rgb(c) for c in colors]

    for rgb in rgbs:
        if _is_vivid(rgb):
            return _hex(rgb)

    # Nothing passed the gate — take the most saturated color we have, if any.
    if rgbs:
        best = max(rgbs, key=_saturation)
        if _saturation(best) > 0.0:
            return _hex(best)

    return FALLBACK_ACCENT


def palette_from_logo(image_path: str | Path) -> dict:
    """Drop-in theme dict derived from a logo: accent, dark gradient background, raw colors.

    Shape: {"accent": "#rrggbb", "background": ["#rrggbb", "#rrggbb"], "colors": [...]}.
    The background is a deep desaturated tint of the accent fading to near-black, so it stays
    a readable Studio backdrop regardless of how bright the source logo is.
    """
    colors = dominant_colors(image_path)
    accent = pick_accent(colors)
    return {
        "accent": accent,
        "background": _dark_gradient(accent),
        "colors": colors,
    }


# --------------------------------------------------------------------------- helpers


def _alpha_mask(img: Image.Image) -> Image.Image | None:
    """The image's alpha band as an 'L' image, or None for an opaque image."""
    if img.mode in ("RGBA", "LA"):
        return img.getchannel("A")
    if img.mode == "P" and "transparency" in img.info:
        return img.convert("RGBA").getchannel("A")
    return None


def _palette_counts(pal: Image.Image, alpha: Image.Image | None) -> list[tuple[int, int]]:
    """Population per palette index as (count, index), most-common first.

    When an alpha mask is given, fully-transparent pixels are excluded so a logo's empty
    canvas can't win the palette. Falls back to PIL's own counts for opaque images.
    """
    counts: dict[int, int] = {}
    if alpha is None:
        # For a 'P' image getcolors yields (count, palette_index); index is always an int.
        for count, idx in pal.getcolors() or []:
            if isinstance(idx, int):
                counts[idx] = counts.get(idx, 0) + count
    else:
        for idx, a in zip(pal.getdata(), alpha.getdata(), strict=False):
            if a == 0:  # fully transparent — ignore
                continue
            counts[idx] = counts.get(idx, 0) + 1
    return sorted(((c, i) for i, c in counts.items()), key=lambda c: c[0], reverse=True)


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Composite any image onto white so alpha doesn't bleed dark fringes into the palette.

    Fully-transparent pixels are dropped (set to white and excluded by sampling on the
    visible area) — we approximate that by alpha-compositing over white, which keeps the
    transparent canvas from contributing a spurious dark/black color.
    """
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(white, rgba).convert("RGB")
    return img.convert("RGB")


def _downscale(img: Image.Image, max_side: int) -> Image.Image:
    """Shrink so the longest side is <= max_side; quantizing a thumbnail is plenty accurate."""
    longest = max(img.size)
    if longest <= max_side:
        return img
    scale = max_side / longest
    size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    return img.resize(size, Image.Resampling.BILINEAR)


def _hex(rgb: tuple[float, float, float]) -> str:
    """An (r, g, b) triple → '#rrggbb', rounded and clamped to 0..255.

    Accepts floats so the gradient/darken math can feed scaled channel values directly.
    """
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    """'#rgb' or '#rrggbb' → (r, g, b)."""
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _luma(rgb: tuple[int, int, int]) -> float:
    """Perceptual luminance (Rec. 601), 0..255."""
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _saturation(rgb: tuple[int, int, int]) -> float:
    """HSV saturation, 0..1 (greys → 0, pure hues → 1)."""
    r, g, b = (c / 255.0 for c in rgb)
    return colorsys.rgb_to_hsv(r, g, b)[1]


def _darken(hex_str: str, factor: float) -> str:
    """Scale a hex color toward black by `factor` (0 → black, 1 → unchanged)."""
    factor = max(0.0, min(1.0, factor))
    r, g, b = _hex_to_rgb(hex_str)
    return _hex((r * factor, g * factor, b * factor))


def _is_vivid(rgb: tuple[int, int, int]) -> bool:
    """A color is accent-worthy if it isn't near-white, near-black, or a low-sat grey."""
    lum = _luma(rgb)
    if lum > _WHITE_LUMA or lum < _BLACK_LUMA:
        return False
    return _saturation(rgb) >= _MIN_SAT


def _dark_gradient(accent: str) -> list[str]:
    """A deep desaturated tint of the accent → near-black, both safely dark for a backdrop."""
    r, g, b = _hex_to_rgb(accent)
    h, _s, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    # Keep the accent's hue but force it deep and muted so the window reads on top of it.
    tr, tg, tb = colorsys.hsv_to_rgb(h, 0.35, 0.16)
    top = _hex((tr * 255, tg * 255, tb * 255))
    return [top, _darken(top, 0.35)]
