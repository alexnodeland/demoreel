"""Brand kits — a reusable `brand.yaml` bundle merged *under* a spec as defaults.

A brand kit captures the look-and-feel a team reuses across many demos: an accent color,
a gradient backdrop palette, a logo + watermark settings, a caption font, and the
lower-third name/title. A spec references one with a top-level `brand_kit: path.yaml`
directive; the kit's values become defaults that the spec's own explicit fields always
override.

This module is pure: it loads + validates a kit (`load_brand_kit`), projects it into a
partial raw-spec dict (`kit_overlay`), and deep-merges that overlay *under* the spec's raw
dict so the spec wins on every conflicting leaf (`merge_under`). The orchestrator wires
these into `load_spec` at the raw-dict level (before preset application and validation).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

# The angle paired with a kit's gradient palette in the frame background overlay. Matches
# the 135° default used by the presets in themes.py and the GradientBg model in spec.py.
_KIT_BACKGROUND_ANGLE = 135


class BrandKit(BaseModel):
    """A reusable brand bundle. Every field is optional; only the set fields overlay.

    The accent color is a single value that maps to three spec leaves (brand.color,
    captions.accent, cursor.color); `background` is a `[from, to]` hex gradient pair.
    """

    model_config = ConfigDict(extra="forbid")

    accent: str | None = None
    background: list[str] | None = None  # [from, to] hex pair
    logo: str | None = None
    font: str | None = None
    name: str | None = None
    title: str | None = None
    watermark: bool | None = None
    watermark_position: str | None = None
    watermark_opacity: float | None = None

    @model_validator(mode="after")
    def _check_background(self) -> BrandKit:
        # mode="after" runs on defaults too, so guard the None case explicitly.
        if self.background is not None and len(self.background) != 2:
            raise ValueError(
                f"brand kit `background` must be a [from, to] pair of 2 hex colors, "
                f"got {len(self.background)}"
            )
        return self


def load_brand_kit(path: str | Path) -> BrandKit:
    """Read a `brand.yaml` kit, validate it, and return a `BrandKit`.

    Raises FileNotFoundError if the path is missing and ValueError if the content is not a
    YAML mapping or fails kit validation.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"brand kit not found: {path}")
    raw = yaml.safe_load(p.read_text())
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level for a brand kit")
    try:
        return BrandKit.model_validate(raw)
    except ValueError as exc:
        raise ValueError(f"{path}: invalid brand kit: {exc}") from exc


def kit_overlay(kit: BrandKit) -> dict[str, Any]:
    """Project a `BrandKit` into a partial raw-spec dict.

    Only keys the kit actually sets are emitted; any sub-key whose value is None is omitted,
    and a section is dropped entirely if it ends up empty. The accent color maps to three
    leaves: brand.color, captions.accent, and cursor.color.
    """
    overlay: dict[str, Any] = {}

    brand: dict[str, Any] = {}
    if kit.logo is not None:
        brand["logo"] = kit.logo
    if kit.accent is not None:
        brand["color"] = kit.accent
    if kit.watermark is not None:
        brand["watermark"] = kit.watermark
    if kit.watermark_position is not None:
        brand["watermark_position"] = kit.watermark_position
    if kit.watermark_opacity is not None:
        brand["watermark_opacity"] = kit.watermark_opacity
    if kit.name is not None:
        brand["name"] = kit.name
    if kit.title is not None:
        brand["title"] = kit.title
    if brand:
        overlay["brand"] = brand

    captions: dict[str, Any] = {}
    if kit.font is not None:
        captions["font"] = kit.font
    if kit.accent is not None:
        captions["accent"] = kit.accent
    if captions:
        overlay["captions"] = captions

    if kit.accent is not None:
        overlay["cursor"] = {"color": kit.accent}

    if kit.background is not None:
        overlay["frame"] = {
            "background": {"colors": kit.background, "angle": _KIT_BACKGROUND_ANGLE}
        }

    return overlay


def merge_under(raw_spec: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge `overlay` *under* `raw_spec` so `raw_spec` wins on every conflicting leaf.

    Nested dicts are merged recursively; a list/scalar in `raw_spec` replaces the overlay's
    value wholesale (no element-wise merge). Keys present only in the overlay are filled in.
    Returns a NEW dict — neither input is mutated.
    """
    out: dict[str, Any] = copy.deepcopy(overlay)
    for k, v in raw_spec.items():
        existing = out.get(k)
        if isinstance(existing, dict) and isinstance(v, dict):
            out[k] = merge_under(v, existing)
        else:
            out[k] = copy.deepcopy(v)
    return out
