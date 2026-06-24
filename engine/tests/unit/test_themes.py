"""Unit tests for demoreel.themes — deep-merge semantics and preset application.

themes.py is pure (no I/O, no network): `_deep_merge` recursively merges two dicts and
`apply_preset` deep-merges a named preset *under* the user's raw spec dict. These tests
pin the exact merge behavior and the deepcopy guarantee that protects the PRESETS global.
"""

from __future__ import annotations

import copy

import pytest

from demoreel.themes import (
    DEFAULT_PRESET,
    PRESETS,
    _deep_merge,
    apply_preset,
)

# --------------------------------------------------------------------------- #
# _deep_merge
# --------------------------------------------------------------------------- #


def test_deep_merge_override_wins_at_top_level():
    base = {"a": 1, "b": 2}
    override = {"a": 99}
    out = _deep_merge(base, override)
    assert out == {"a": 99, "b": 2}


def test_deep_merge_adds_new_top_level_keys():
    base = {"a": 1}
    override = {"b": 2}
    assert _deep_merge(base, override) == {"a": 1, "b": 2}


def test_deep_merge_nested_dicts_merge_recursively():
    # Override one nested key, the sibling nested key must survive.
    base = {"frame": {"style": "studio", "chrome": "browser"}}
    override = {"frame": {"chrome": "none"}}
    out = _deep_merge(base, override)
    assert out == {"frame": {"style": "studio", "chrome": "none"}}


def test_deep_merge_nested_three_levels_deep():
    base = {"frame": {"background": {"angle": 135, "colors": ["#000"]}}}
    override = {"frame": {"background": {"angle": 90}}}
    out = _deep_merge(base, override)
    assert out == {"frame": {"background": {"angle": 90, "colors": ["#000"]}}}


def test_deep_merge_non_dict_override_replaces_dict_base_wholesale():
    # When the override value for a key is NOT a dict, it replaces the base dict outright
    # (no recursive merge). This is how `minimal`'s string background overrides a dict.
    base = {"frame": {"background": {"colors": ["#1B1B2E"], "angle": 135}}}
    override = {"frame": {"background": "#0B0B12"}}
    out = _deep_merge(base, override)
    assert out["frame"]["background"] == "#0B0B12"


def test_deep_merge_dict_override_over_non_dict_base_replaces():
    # Symmetric case: base value is a scalar, override is a dict → override wins wholesale
    # (the `isinstance(out[k], dict)` guard is False so no recursion).
    base = {"frame": "flat"}
    override = {"frame": {"style": "studio"}}
    out = _deep_merge(base, override)
    assert out == {"frame": {"style": "studio"}}


def test_deep_merge_does_not_mutate_base():
    base = {"frame": {"style": "studio", "chrome": "browser"}, "top": 1}
    base_snapshot = copy.deepcopy(base)
    override = {"frame": {"chrome": "none"}, "top": 2}
    _deep_merge(base, override)
    # The base passed in is untouched at every level.
    assert base == base_snapshot


def test_deep_merge_does_not_mutate_override():
    base = {"frame": {"style": "studio"}}
    override = {"frame": {"chrome": "none"}}
    override_snapshot = copy.deepcopy(override)
    _deep_merge(base, override)
    assert override == override_snapshot


def test_deep_merge_empty_override_returns_shallow_copy_of_base():
    base = {"a": {"b": 1}}
    out = _deep_merge(base, {})
    assert out == base
    # Top-level container is a fresh dict (dict(base)) — a new top-level key never leaks.
    out["z"] = 9
    assert "z" not in base
    # CURRENT BEHAVIOR: it's only a *shallow* copy (out = dict(base)). With an empty
    # override the recursion never fires, so nested dicts are shared by reference. We pin
    # this so a future change to deepcopy-the-base would intentionally flip this test.
    assert out["a"] is base["a"]


# --------------------------------------------------------------------------- #
# apply_preset
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("preset_name", ["studio", "dark", "light", "minimal"])
def test_apply_preset_known_preset_brings_in_defaults(preset_name):
    raw = {"preset": preset_name, "url": "https://example.com"}
    out = apply_preset(raw)
    # User keys preserved.
    assert out["preset"] == preset_name
    assert out["url"] == "https://example.com"
    # Preset defaults are carried in (every preset defines a frame).
    assert "frame" in out
    assert out["frame"] == PRESETS[preset_name]["frame"]


def test_apply_preset_user_key_overrides_preset_nested():
    # User frame.background must win over the studio preset's frame.background,
    # while the preset's sibling frame keys (style, chrome) survive.
    raw = {
        "preset": "studio",
        "frame": {"background": {"colors": ["#FF0000", "#00FF00"], "angle": 45}},
    }
    out = apply_preset(raw)
    assert out["frame"]["background"] == {"colors": ["#FF0000", "#00FF00"], "angle": 45}
    # Preset siblings preserved.
    assert out["frame"]["style"] == "studio"
    assert out["frame"]["chrome"] == "browser"


def test_apply_preset_user_scalar_overrides_preset_dict():
    # User supplies a scalar background; it replaces the preset's dict background wholesale.
    raw = {"preset": "studio", "frame": {"background": "#123456"}}
    out = apply_preset(raw)
    assert out["frame"]["background"] == "#123456"
    # Other preset frame fields remain.
    assert out["frame"]["style"] == "studio"


def test_apply_preset_returns_both_preset_and_user_overrides():
    raw = {
        "preset": "dark",
        "url": "https://example.com",
        "cursor": {"color": "#ABCDEF"},  # overrides dark's cursor color
    }
    out = apply_preset(raw)
    # User override wins on cursor.
    assert out["cursor"]["color"] == "#ABCDEF"
    # Preset-only key (captions accent from dark) is present and untouched.
    assert out["captions"]["accent"] == PRESETS["dark"]["captions"]["accent"]
    # User-only key present.
    assert out["url"] == "https://example.com"


def test_apply_preset_unknown_name_falls_back_to_studio():
    raw = {"preset": "does-not-exist"}
    out = apply_preset(raw)
    # The fallback base is the studio preset, so studio's frame defaults come through.
    assert out["frame"] == PRESETS[DEFAULT_PRESET]["frame"]
    assert out["cursor"]["color"] == PRESETS["studio"]["cursor"]["color"]


def test_apply_preset_missing_preset_key_defaults_to_studio():
    # No "preset" key at all → DEFAULT_PRESET (studio).
    raw = {"url": "https://example.com"}
    out = apply_preset(raw)
    assert out["frame"] == PRESETS["studio"]["frame"]


def test_apply_preset_does_not_mutate_presets_global():
    # Take a deep snapshot of the entire PRESETS table, run a merge that would (without the
    # deepcopy in apply_preset) mutate nested preset dicts, then assert the global is intact.
    snapshot = copy.deepcopy(PRESETS)
    raw = {
        "preset": "studio",
        "frame": {"background": {"colors": ["#DEAD00"], "angle": 1}, "chrome": "none"},
        "cursor": {"color": "#000000"},
    }
    out = apply_preset(raw)
    # The merge actually applied the overrides (sanity: we really did exercise the path).
    assert out["frame"]["chrome"] == "none"
    assert out["frame"]["background"] == {"colors": ["#DEAD00"], "angle": 1}
    # The module global is byte-for-byte unchanged.
    assert snapshot == PRESETS
    # And specifically the studio preset's nested dicts were not aliased into the output.
    assert PRESETS["studio"]["frame"]["chrome"] == "browser"
    assert PRESETS["studio"]["frame"]["background"]["colors"] == ["#1B1B2E", "#0B0B12"]


def test_apply_preset_output_is_not_aliased_to_preset():
    # Mutating the returned dict's nested preset-derived structures must not reach back
    # into PRESETS (guards the deepcopy boundary at the nested level).
    raw = {"preset": "light"}
    out = apply_preset(raw)
    out["frame"]["style"] = "MUTATED"
    out["captions"]["accent"] = "MUTATED"
    assert PRESETS["light"]["frame"]["style"] == "studio"
    assert PRESETS["light"]["captions"]["accent"] == "#4338CA"


def test_apply_preset_minimal_string_background_via_user_keeps_preset():
    # minimal already ships a string background; a user override of another key should not
    # disturb it. Confirms preset string scalars pass through merge intact.
    raw = {"preset": "minimal", "captions": {"accent": "#FFFFFF"}}
    out = apply_preset(raw)
    assert out["frame"]["background"] == "#0B0B12"
    assert out["frame"]["chrome"] == "none"
    assert out["captions"]["accent"] == "#FFFFFF"
    # Preset's brand watermark flag survives.
    assert out["brand"]["watermark"] is False
