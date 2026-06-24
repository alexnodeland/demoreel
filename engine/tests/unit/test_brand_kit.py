"""Unit tests for demoreel.brand_kit — kit validation, overlay projection, deep-merge.

brand_kit.py is pure (YAML load + dict math, no moviepy/browser). These tests pin:
- BrandKit validation (good kit, bad `background` length, missing/garbage file → errors)
- kit_overlay (omits None keys + empty sections; accent maps to all three leaves)
- merge_under (raw wins at every depth, recursion, overlay-only keys filled, no mutation,
  empty-input edge cases)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from demoreel.brand_kit import (
    BrandKit,
    kit_overlay,
    load_brand_kit,
    merge_under,
)

# --------------------------------------------------------------------------- #
# BrandKit validation
# --------------------------------------------------------------------------- #


def test_brandkit_full_valid():
    kit = BrandKit(
        accent="#FF6B00",
        background=["#101018", "#05050A"],
        logo="logo.png",
        font="Inter",
        name="Acme",
        title="Product Demo",
        watermark=True,
        watermark_position="bottom-left",
        watermark_opacity=0.4,
    )
    assert kit.accent == "#FF6B00"
    assert kit.background == ["#101018", "#05050A"]


def test_brandkit_empty_is_valid():
    kit = BrandKit()
    assert kit.accent is None
    assert kit.background is None


def test_brandkit_bad_background_length_one():
    with pytest.raises(ValidationError, match="from, to"):
        BrandKit(background=["#101018"])


def test_brandkit_bad_background_length_three():
    with pytest.raises(ValidationError, match="from, to"):
        BrandKit(background=["#101018", "#05050A", "#000000"])


def test_brandkit_background_empty_list_rejected():
    with pytest.raises(ValidationError, match="from, to"):
        BrandKit(background=[])


def test_brandkit_extra_key_forbidden():
    with pytest.raises(ValidationError):
        BrandKit(unknown="x")


# --------------------------------------------------------------------------- #
# load_brand_kit
# --------------------------------------------------------------------------- #


def test_load_brand_kit_good(tmp_path):
    p = tmp_path / "acme.brand.yaml"
    p.write_text(
        "accent: '#FF6B00'\n"
        "background: ['#101018', '#05050A']\n"
        "logo: logo.png\n"
        "name: Acme\n"
        "title: Demo\n"
        "watermark: true\n"
    )
    kit = load_brand_kit(p)
    assert kit.accent == "#FF6B00"
    assert kit.background == ["#101018", "#05050A"]
    assert kit.name == "Acme"


def test_load_brand_kit_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="brand kit not found"):
        load_brand_kit(tmp_path / "nope.yaml")


def test_load_brand_kit_empty_file_is_empty_kit(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    kit = load_brand_kit(p)
    assert kit == BrandKit()


def test_load_brand_kit_non_mapping(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="expected a YAML mapping"):
        load_brand_kit(p)


def test_load_brand_kit_bad_content(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("background: ['#fff']\n")
    with pytest.raises(ValueError, match="invalid brand kit"):
        load_brand_kit(p)


def test_load_brand_kit_accepts_str_path(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("accent: '#fff'\n")
    kit = load_brand_kit(str(p))
    assert kit.accent == "#fff"


# --------------------------------------------------------------------------- #
# kit_overlay
# --------------------------------------------------------------------------- #


def test_kit_overlay_empty_kit_is_empty():
    assert kit_overlay(BrandKit()) == {}


def test_kit_overlay_accent_maps_to_three_places():
    overlay = kit_overlay(BrandKit(accent="#FF6B00"))
    assert overlay["brand"]["color"] == "#FF6B00"
    assert overlay["captions"]["accent"] == "#FF6B00"
    assert overlay["cursor"]["color"] == "#FF6B00"


def test_kit_overlay_omits_none_subkeys():
    # Only accent set → brand has just `color`, no logo/watermark/name keys.
    overlay = kit_overlay(BrandKit(accent="#FF6B00"))
    assert overlay["brand"] == {"color": "#FF6B00"}
    assert set(overlay["brand"]) == {"color"}


def test_kit_overlay_drops_empty_sections():
    # Only `logo` set → no captions section, no cursor section, no frame section.
    overlay = kit_overlay(BrandKit(logo="logo.png"))
    assert overlay == {"brand": {"logo": "logo.png"}}


def test_kit_overlay_font_only_emits_captions_no_accent():
    overlay = kit_overlay(BrandKit(font="Inter"))
    assert overlay == {"captions": {"font": "Inter"}}


def test_kit_overlay_background_maps_to_frame_gradient():
    overlay = kit_overlay(BrandKit(background=["#101018", "#05050A"]))
    assert overlay == {"frame": {"background": {"colors": ["#101018", "#05050A"], "angle": 135}}}


def test_kit_overlay_watermark_false_is_emitted():
    # watermark=False is a real value, not None — it must appear.
    overlay = kit_overlay(BrandKit(watermark=False))
    assert overlay == {"brand": {"watermark": False}}


def test_kit_overlay_watermark_opacity_zero_is_emitted():
    overlay = kit_overlay(BrandKit(watermark_opacity=0.0))
    assert overlay == {"brand": {"watermark_opacity": 0.0}}


def test_kit_overlay_full_kit_all_sections():
    kit = BrandKit(
        accent="#FF6B00",
        background=["#101018", "#05050A"],
        logo="logo.png",
        font="Inter",
        name="Acme",
        title="Product Demo",
        watermark=True,
        watermark_position="bottom-left",
        watermark_opacity=0.4,
    )
    overlay = kit_overlay(kit)
    assert overlay == {
        "brand": {
            "logo": "logo.png",
            "color": "#FF6B00",
            "watermark": True,
            "watermark_position": "bottom-left",
            "watermark_opacity": 0.4,
            "name": "Acme",
            "title": "Product Demo",
        },
        "captions": {"font": "Inter", "accent": "#FF6B00"},
        "cursor": {"color": "#FF6B00"},
        "frame": {"background": {"colors": ["#101018", "#05050A"], "angle": 135}},
    }


# --------------------------------------------------------------------------- #
# merge_under — raw_spec wins on conflicts, overlay fills gaps
# --------------------------------------------------------------------------- #


def test_merge_under_raw_wins_at_top_level():
    raw = {"a": 1}
    overlay = {"a": 99, "b": 2}
    assert merge_under(raw, overlay) == {"a": 1, "b": 2}


def test_merge_under_fills_overlay_only_keys():
    raw = {}
    overlay = {"brand": {"color": "#FF6B00"}}
    assert merge_under(raw, overlay) == {"brand": {"color": "#FF6B00"}}


def test_merge_under_nested_recursion_raw_wins_at_leaf():
    raw = {"brand": {"color": "#000000"}}
    overlay = {"brand": {"color": "#FF6B00", "logo": "kit.png"}}
    # raw wins on `color`; overlay's `logo` survives.
    assert merge_under(raw, overlay) == {"brand": {"color": "#000000", "logo": "kit.png"}}


def test_merge_under_three_levels_deep():
    raw = {"frame": {"background": {"angle": 90}}}
    overlay = {"frame": {"background": {"angle": 135, "colors": ["#000", "#111"]}}}
    out = merge_under(raw, overlay)
    assert out == {"frame": {"background": {"angle": 90, "colors": ["#000", "#111"]}}}


def test_merge_under_raw_scalar_replaces_overlay_dict():
    raw = {"frame": {"background": "#0B0B12"}}
    overlay = {"frame": {"background": {"colors": ["#000", "#111"], "angle": 135}}}
    out = merge_under(raw, overlay)
    assert out["frame"]["background"] == "#0B0B12"


def test_merge_under_raw_list_replaces_overlay_list():
    raw = {"colors": ["#fff"]}
    overlay = {"colors": ["#000", "#111"]}
    assert merge_under(raw, overlay) == {"colors": ["#fff"]}


def test_merge_under_raw_dict_replaces_overlay_scalar():
    # When raw has a dict where overlay had a scalar, raw's dict wins outright.
    raw = {"x": {"deep": 1}}
    overlay = {"x": 5}
    assert merge_under(raw, overlay) == {"x": {"deep": 1}}


def test_merge_under_empty_overlay_returns_raw_copy():
    raw = {"a": {"b": 1}}
    out = merge_under(raw, {})
    assert out == {"a": {"b": 1}}
    assert out is not raw
    assert out["a"] is not raw["a"]


def test_merge_under_empty_raw_returns_overlay_copy():
    overlay = {"brand": {"color": "#FF6B00"}}
    out = merge_under({}, overlay)
    assert out == {"brand": {"color": "#FF6B00"}}
    assert out is not overlay
    assert out["brand"] is not overlay["brand"]


def test_merge_under_both_empty():
    assert merge_under({}, {}) == {}


def test_merge_under_does_not_mutate_inputs():
    raw = {"brand": {"color": "#000000"}}
    overlay = {"brand": {"color": "#FF6B00", "logo": "kit.png"}}
    raw_before = {"brand": {"color": "#000000"}}
    overlay_before = {"brand": {"color": "#FF6B00", "logo": "kit.png"}}
    merge_under(raw, overlay)
    assert raw == raw_before
    assert overlay == overlay_before


def test_merge_under_realistic_spec_over_kit_overlay():
    # End-to-end: a kit overlay merged under a real spec dict. Spec's accent override and
    # title win; kit's logo + gradient + font fill the gaps.
    overlay = kit_overlay(
        BrandKit(
            accent="#FF6B00",
            background=["#101018", "#05050A"],
            logo="acme-logo.png",
            font="Inter",
            name="Acme",
            title="Kit Title",
        )
    )
    raw = {
        "title": "My Demo",
        "brand": {"color": "#00B894", "title": "Spec Title"},
        "scenes": [{"goto": "https://example.com"}],
    }
    out = merge_under(raw, overlay)
    # Spec wins:
    assert out["brand"]["color"] == "#00B894"
    assert out["brand"]["title"] == "Spec Title"
    # Kit fills:
    assert out["brand"]["logo"] == "acme-logo.png"
    assert out["brand"]["name"] == "Acme"
    assert out["captions"]["font"] == "Inter"
    assert out["captions"]["accent"] == "#FF6B00"  # accent not overridden in captions
    assert out["cursor"]["color"] == "#FF6B00"
    assert out["frame"]["background"]["colors"] == ["#101018", "#05050A"]
    # Spec-only keys untouched:
    assert out["title"] == "My Demo"
    assert out["scenes"] == [{"goto": "https://example.com"}]
