"""Unit tests for demoreel/spec.py.

Covers the declarative spec model: Quality normalization, Scene action/focus/zoom
invariants, DemoSpec cross-field validation, VoiceConfig engine validation against the
tts registry, and load_spec + preset merge. No network, no browser, no ffmpeg.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from demoreel.spec import (
    Callout,
    CameraConfig,
    DemoSpec,
    Quality,
    Scene,
    TypeAction,
    VoiceConfig,
    load_spec,
)

# --------------------------------------------------------------------------- Quality


def test_quality_default_resolution_size():
    q = Quality()
    assert q.size == (1920, 1080)


def test_quality_named_presets():
    assert Quality(resolution="480p").size == (854, 480)
    assert Quality(resolution="720p").size == (1280, 720)
    assert Quality(resolution="1440p").size == (2560, 1440)
    assert Quality(resolution="4k").size == (3840, 2160)


def test_quality_resolution_case_insensitive():
    assert Quality(resolution="1080P").size == (1920, 1080)
    assert Quality(resolution="4K").size == (3840, 2160)


def test_quality_tuple_passthrough_even():
    q = Quality(resolution=(1920, 1080))
    assert q.size == (1920, 1080)


def test_quality_odd_dims_round_down_to_even():
    q = Quality(resolution=(1281, 721))
    assert q.size == (1280, 720)


def test_quality_one_odd_dim_rounds_down():
    assert Quality(resolution=(1920, 1081)).size == (1920, 1080)
    assert Quality(resolution=(1921, 1080)).size == (1920, 1080)


def test_quality_unknown_string_raises():
    with pytest.raises(ValidationError):
        Quality(resolution="potato")


def test_quality_zero_dim_raises():
    with pytest.raises(ValidationError):
        Quality(resolution=(0, 1080))
    with pytest.raises(ValidationError):
        Quality(resolution=(1920, 0))


def test_quality_negative_dim_raises():
    with pytest.raises(ValidationError):
        Quality(resolution=(-100, 1080))
    with pytest.raises(ValidationError):
        Quality(resolution=(1920, -100))


def test_quality_size_always_concrete_even_tuple():
    # Across preset, even-tuple, and odd-tuple inputs, .size is always a concrete even (w, h).
    for inp in ("1080p", (1920, 1080), (1281, 721), "480p"):
        w, h = Quality(resolution=inp).size
        assert isinstance(w, int) and isinstance(h, int)
        assert w % 2 == 0 and h % 2 == 0
        assert w > 0 and h > 0


# --------------------------------------------------------------------------- Scene actions


def test_scene_two_actions_raises():
    with pytest.raises(ValidationError):
        Scene(click="#a", goto="/b")


def test_scene_two_actions_raises_other_pair():
    with pytest.raises(ValidationError):
        Scene(hover="#a", wait=1.0)


def test_scene_one_action_ok():
    s = Scene(click="#a")
    assert s.primary_action() == ("click", "#a")


def test_scene_no_action_ok():
    s = Scene(narrate="hello")
    assert s.primary_action() is None


# --------------------------------------------------------------------- Scene.focus_selector


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        # focus wins over everything
        ({"focus": "#focus", "click": "#click", "highlight": "#hl"}, "#focus"),
        # callout.at beats arrow/highlight/spotlight/click/hover/type
        (
            {
                "callout": Callout(text="hi", at="#callout"),
                "arrow": {"to": "#arrow"},
                "highlight": "#hl",
            },
            "#callout",
        ),
        # arrow.to beats highlight/spotlight/click/hover/type
        ({"arrow": {"to": "#arrow"}, "highlight": "#hl", "spotlight": "#sp"}, "#arrow"),
        # highlight beats spotlight/click/hover/type
        ({"highlight": "#hl", "spotlight": "#sp", "click": "#c"}, "#hl"),
        # spotlight beats click/hover/type
        ({"spotlight": "#sp", "click": "#c"}, "#sp"),
        # an action field alone yields its own selector (each tested individually since
        # click/hover/type are mutually exclusive actions and can't co-occur on one scene)
        ({"click": "#c"}, "#c"),
        ({"hover": "#h"}, "#h"),
        # type.selector last
        ({"type": TypeAction(selector="#t", text="x")}, "#t"),
    ],
)
def test_focus_selector_precedence(kwargs, expected):
    assert Scene(**kwargs).focus_selector() == expected


def test_focus_selector_annotation_beats_action():
    # Annotations (highlight) combine with a single action (click); highlight wins.
    assert Scene(highlight="#hl", click="#c").focus_selector() == "#hl"
    # spotlight also outranks the click action.
    assert Scene(spotlight="#sp", click="#c").focus_selector() == "#sp"


def test_focus_selector_none_when_no_focus_point():
    # narrate-only scene, and a string callout (centered banner — no `at`) → no focus point.
    assert Scene(narrate="hi").focus_selector() is None
    assert Scene(callout="centered banner").focus_selector() is None


def test_focus_selector_callout_without_at_is_not_a_focus_point():
    # A Callout with no `at` is a centered banner and should NOT contribute a focus selector.
    assert Scene(callout=Callout(text="hi")).focus_selector() is None


def test_focus_selector_type_string_form_not_a_focus_point():
    # `type` as a bare string has no selector → not a focus point.
    assert Scene(type="just text").focus_selector() is None


def test_has_focus_point():
    assert Scene(click="#c").has_focus_point() is True
    assert Scene(narrate="hi").has_focus_point() is False


# --------------------------------------------------------------------- Scene.effective_zoom


def test_effective_zoom_no_zoom_returns_none():
    cam = CameraConfig()
    s = Scene(click="#c", no_zoom=True, zoom=2.0)  # no_zoom overrides even explicit zoom
    assert s.effective_zoom(cam) is None


def test_effective_zoom_explicit_zoom_wins():
    cam = CameraConfig(zoom=1.6)
    s = Scene(click="#c", zoom=2.5)
    assert s.effective_zoom(cam) == pytest.approx(2.5)


def test_effective_zoom_explicit_zoom_without_focus():
    # explicit zoom applies even when there's no focus point.
    cam = CameraConfig()
    s = Scene(narrate="hi", zoom=1.3)
    assert s.effective_zoom(cam) == pytest.approx(1.3)


def test_effective_zoom_auto_zoom_with_focus_uses_cam_zoom():
    cam = CameraConfig(auto_zoom=True, zoom=1.6)
    s = Scene(click="#c")
    assert s.effective_zoom(cam) == pytest.approx(1.6)


def test_effective_zoom_no_focus_point_returns_none():
    cam = CameraConfig(auto_zoom=True, zoom=1.6)
    s = Scene(narrate="hi")
    assert s.effective_zoom(cam) is None


def test_effective_zoom_auto_zoom_disabled_returns_none():
    cam = CameraConfig(auto_zoom=False, zoom=1.6)
    s = Scene(click="#c")
    assert s.effective_zoom(cam) is None


# ---------------------------------------------------- DemoSpec._check_first_navigation


def test_first_scene_no_goto_no_url_raises():
    with pytest.raises(ValidationError):
        DemoSpec(scenes=[Scene(narrate="hi")])


def test_first_scene_goto_passes():
    spec = DemoSpec(scenes=[Scene(goto="https://example.com")])
    assert spec.scenes[0].goto == "https://example.com"


def test_top_level_url_passes():
    spec = DemoSpec(url="https://example.com", scenes=[Scene(narrate="hi")])
    assert spec.url == "https://example.com"


def test_first_scene_goto_and_top_level_url_both_present_passes():
    spec = DemoSpec(url="https://example.com", scenes=[Scene(goto="/page")])
    assert spec.scenes[0].goto == "/page"


def test_demospec_requires_at_least_one_scene():
    with pytest.raises(ValidationError):
        DemoSpec(url="https://example.com", scenes=[])


# -------------------------------------------------------- DemoSpec.aspect_mismatch


def test_aspect_mismatch_matched_is_near_zero(make_spec):
    spec = make_spec(viewport=(1600, 900), quality={"resolution": "1080p"})
    assert spec.aspect_mismatch() == pytest.approx(0.0, abs=1e-9)


def test_aspect_mismatch_mismatched_exceeds_threshold(make_spec):
    spec = make_spec(viewport=(1600, 1000), quality={"resolution": "1080p"})
    assert spec.aspect_mismatch() > 0.02


def test_aspect_mismatch_value(make_spec):
    # 1600x1000 → 1.6, output 16:9 → 1.777...; gap relative to output aspect.
    spec = make_spec(viewport=(1600, 1000), quality={"resolution": "1080p"})
    vw_vh = 1600 / 1000
    ow_oh = 1920 / 1080
    expected = abs(vw_vh - ow_oh) / ow_oh
    assert spec.aspect_mismatch() == pytest.approx(expected)


def test_output_size_delegates_to_quality(make_spec):
    spec = make_spec(quality={"resolution": (1281, 721)})
    assert spec.output_size() == (1280, 720)


# --------------------------------------------------------------------------- VoiceConfig


def test_voice_config_default_engine_valid():
    v = VoiceConfig()
    assert v.engine == "piper"
    assert v.fallback == []


def test_voice_config_unknown_engine_raises():
    with pytest.raises(ValidationError):
        VoiceConfig(engine="not-a-real-engine")


def test_voice_config_unknown_fallback_entry_raises():
    with pytest.raises(ValidationError):
        VoiceConfig(engine="piper", fallback=["say", "bogus"])


def test_voice_config_valid_engine_and_fallback_passes():
    v = VoiceConfig(engine="openai", fallback=["piper", "say"])
    assert v.engine == "openai"
    assert v.fallback == ["piper", "say"]


def test_voice_config_all_registry_engines_accepted():
    from demoreel.tts import provider_names

    for eng in provider_names():
        v = VoiceConfig(engine=eng)
        assert v.engine == eng


def test_voice_config_new_fields_accept_values():
    v = VoiceConfig(
        engine="openai",
        base_url="https://localhost:1234/v1",
        tts_model="gpt-4o-mini-tts",
        model="alloy",
        fallback=["say"],
        rate=1.25,
        volume=0.9,
    )
    assert v.base_url == "https://localhost:1234/v1"
    assert v.tts_model == "gpt-4o-mini-tts"
    assert v.model == "alloy"
    assert v.fallback == ["say"]
    assert v.rate == pytest.approx(1.25)
    assert v.volume == pytest.approx(0.9)


# --------------------------------------------------------------------------- load_spec


def test_load_spec_valid_dict_loads(write_spec):
    path = write_spec(
        {
            "title": "My Demo",
            "url": "https://example.com",
            "scenes": [{"goto": "/", "narrate": "welcome"}],
        }
    )
    spec = load_spec(path)
    assert isinstance(spec, DemoSpec)
    assert spec.title == "My Demo"
    assert spec.url == "https://example.com"
    assert len(spec.scenes) == 1
    assert spec.scenes[0].narrate == "welcome"


def test_load_spec_preset_merge_sets_frame_background(write_spec):
    # No frame given → studio preset supplies the indigo gradient background.
    path = write_spec({"url": "https://example.com", "scenes": [{"goto": "/"}]})
    spec = load_spec(path)
    assert spec.preset == "studio"
    bg = spec.frame.background
    assert bg is not None
    # studio preset uses a GradientBg with the indigo-tinted colors.
    assert bg.colors == ["#1B1B2E", "#0B0B12"]
    assert bg.angle == pytest.approx(135.0)


def test_load_spec_named_preset_merge(write_spec):
    path = write_spec({"preset": "light", "url": "https://example.com", "scenes": [{"goto": "/"}]})
    spec = load_spec(path)
    assert spec.preset == "light"
    assert spec.frame.background.colors == ["#EEF1F6", "#D9DEE8"]
    assert spec.frame.shadow_opacity == pytest.approx(0.28)
    assert spec.cursor.color == "#4338CA"


def test_load_spec_user_fields_win_over_preset(write_spec):
    # User-supplied frame.background overrides the preset's.
    path = write_spec(
        {
            "url": "https://example.com",
            "frame": {"background": "#000000"},
            "scenes": [{"goto": "/"}],
        }
    )
    spec = load_spec(path)
    assert spec.frame.background == "#000000"


def test_load_spec_non_mapping_raises(write_spec, tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        load_spec(path)


def test_load_spec_invalid_spec_raises(write_spec):
    # First scene has no goto and no top-level url → validation error.
    path = write_spec({"scenes": [{"narrate": "hi"}]})
    with pytest.raises(ValidationError):
        load_spec(path)
