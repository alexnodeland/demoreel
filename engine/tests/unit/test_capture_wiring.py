"""Unit tests for the Python wiring around browser capture (no real browser).

These exercise the pure helpers in ``demoreel.capture`` that build the document-start init
scripts, the prelude CSS, the redaction re-arming, URL resolution, and the clamp — plus a
few sanity invariants on the injected ``OVERLAY_JS`` string. A ``FakePage`` records every
``page.evaluate`` call so we can assert exactly what would be sent to a live page.
"""

from __future__ import annotations

from demoreel.capture import (
    _apply_redaction,
    _base_bg,
    _clamp,
    _init_scripts,
    _prelude_css,
    _resolve_url,
)
from demoreel.overlay_js import OVERLAY_JS

DARK_BG = "#101016"
LIGHT_BG = "#fcfcfe"


class FakePage:
    """Records evaluate() calls instead of touching a real Playwright page."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def evaluate(self, script: str, arg: object = None) -> None:
        self.calls.append((script, arg))


# --------------------------------------------------------------------------- _base_bg


def test_base_bg_dark_for_default_studio_spec(make_spec):
    # The default (studio) spec leaves frame.background unset, which _is_light treats as
    # dark, so the pre-paint panel color is the dark window color.
    assert _base_bg(make_spec()) == DARK_BG


def test_base_bg_light_for_light_frame_background(make_spec):
    # A light frame background flips the pre-paint color to the light window panel so a
    # light stage never flashes a dark panel before the app paints.
    spec = make_spec(frame={"background": "#EEF1F6"})
    assert _base_bg(spec) == LIGHT_BG


def test_base_bg_light_for_light_gradient(make_spec):
    spec = make_spec(frame={"background": {"colors": ["#EEF1F6", "#D9DEE8"], "angle": 135}})
    assert _base_bg(spec) == LIGHT_BG


def test_base_bg_returns_one_of_the_two_panel_colors(make_spec):
    assert _base_bg(make_spec()) in {DARK_BG, LIGHT_BG}


# ------------------------------------------------------------------------ _init_scripts


def test_init_scripts_first_sets_documentelement_background_to_base_bg(make_spec):
    spec = make_spec()
    scripts = _init_scripts(spec)
    first = scripts[0]
    assert "documentElement" in first
    assert _base_bg(spec) in first
    assert DARK_BG in first


def test_init_scripts_first_carries_light_base_bg(make_spec):
    spec = make_spec(frame={"background": "#EEF1F6"})
    scripts = _init_scripts(spec)
    assert _base_bg(spec) in scripts[0]
    assert LIGHT_BG in scripts[0]


def test_init_scripts_includes_overlay_js(make_spec):
    scripts = _init_scripts(make_spec())
    assert OVERLAY_JS in scripts


def test_init_scripts_minimal_is_bg_then_overlay(make_spec):
    # With no prelude css and no inject_js, exactly two scripts: the bg-paint and OVERLAY_JS.
    scripts = _init_scripts(make_spec())
    assert len(scripts) == 2
    assert scripts[1] == OVERLAY_JS


def test_init_scripts_appends_inject_js_when_set(make_spec):
    spec = make_spec(prelude={"inject_js": "window.__custom = 1;"})
    scripts = _init_scripts(spec)
    assert "window.__custom = 1;" in scripts[-1]


def test_init_scripts_adds_style_script_for_hide_and_mask(make_spec):
    spec = make_spec(prelude={"hide": [".cookie"], "mask": [".live"]})
    scripts = _init_scripts(spec)
    style_scripts = [s for s in scripts if "createElement('style')" in s]
    assert len(style_scripts) == 1
    style = style_scripts[0]
    assert "display:none!important" in style
    assert "filter:blur(12px)!important" in style


def test_init_scripts_no_style_script_without_prelude_css(make_spec):
    scripts = _init_scripts(make_spec())
    assert not any("createElement('style')" in s for s in scripts)


def test_init_scripts_order_bg_overlay_style_inject(make_spec):
    # When all are present, order is: bg-paint, OVERLAY_JS, style, inject_js.
    spec = make_spec(prelude={"hide": [".x"], "inject_js": "window.__z = 2;"})
    scripts = _init_scripts(spec)
    assert "documentElement" in scripts[0]
    assert scripts[1] == OVERLAY_JS
    assert "createElement('style')" in scripts[2]
    assert "window.__z = 2;" in scripts[3]


# ---------------------------------------------------------------------- _apply_redaction


def test_apply_redaction_records_single_call_with_selectors_and_mode(make_spec):
    spec = make_spec(prelude={"redact": [".x"], "redact_mode": "block"})
    fake = FakePage()
    _apply_redaction(fake, spec)
    assert len(fake.calls) == 1
    script, arg = fake.calls[0]
    assert arg == [[".x"], "block"]
    assert "__demoreel.redact" in script


def test_apply_redaction_default_mode_is_scramble(make_spec):
    spec = make_spec(prelude={"redact": [".a", ".b"]})
    fake = FakePage()
    _apply_redaction(fake, spec)
    assert len(fake.calls) == 1
    _, arg = fake.calls[0]
    assert arg == [[".a", ".b"], "scramble"]


def test_apply_redaction_no_calls_when_redact_empty(make_spec):
    fake = FakePage()
    _apply_redaction(fake, make_spec())
    assert fake.calls == []


def test_apply_redaction_no_calls_for_explicit_empty_list(make_spec):
    spec = make_spec(prelude={"redact": [], "redact_mode": "label"})
    fake = FakePage()
    _apply_redaction(fake, spec)
    assert fake.calls == []


# -------------------------------------------------------------------------- _prelude_css


def test_prelude_css_hide_becomes_display_none(make_spec):
    css = _prelude_css(make_spec(prelude={"hide": [".banner"]}))
    assert ".banner{display:none!important}" in css


def test_prelude_css_mask_becomes_blur(make_spec):
    css = _prelude_css(make_spec(prelude={"mask": [".secret"]}))
    assert ".secret{filter:blur(12px)!important}" in css


def test_prelude_css_does_not_leak_redact_selectors(make_spec):
    # redact is a runtime text-scrub, not CSS — its selectors must never appear in the
    # injected stylesheet (which would hide/blur them by accident).
    css = _prelude_css(
        make_spec(
            prelude={
                "hide": [".h"],
                "mask": [".m"],
                "redact": [".secret-redact"],
                "redact_mode": "block",
            }
        )
    )
    assert ".secret-redact" not in css
    assert ".h{display:none!important}" in css
    assert ".m{filter:blur(12px)!important}" in css


def test_prelude_css_freeze_anim_kills_animations(make_spec):
    css = _prelude_css(make_spec(prelude={"freeze_anim": True}))
    assert "animation:none!important" in css


def test_prelude_css_inject_css_appended(make_spec):
    css = _prelude_css(make_spec(prelude={"inject_css": "body{margin:0}"}))
    assert "body{margin:0}" in css


def test_prelude_css_empty_when_nothing_set(make_spec):
    assert _prelude_css(make_spec()) == ""


# --------------------------------------------------------------------------- _resolve_url


def test_resolve_url_passes_through_https():
    assert _resolve_url("https://h", "https://other.com/page") == "https://other.com/page"


def test_resolve_url_passes_through_file():
    assert _resolve_url("https://h", "file:///tmp/x.html") == "file:///tmp/x.html"


def test_resolve_url_passes_through_http_and_about():
    assert _resolve_url("https://h", "http://x") == "http://x"
    assert _resolve_url("https://h", "about:blank") == "about:blank"


def test_resolve_url_joins_relative_against_base():
    assert _resolve_url("https://h", "/x") == "https://h/x"


def test_resolve_url_strips_trailing_slash_and_leading_slash():
    assert _resolve_url("https://h/", "/x") == "https://h/x"
    assert _resolve_url("https://h", "x") == "https://h/x"


def test_resolve_url_no_base_returns_val_unchanged():
    assert _resolve_url(None, "/x") == "/x"
    assert _resolve_url("", "/x") == "/x"


# ----------------------------------------------------------------------------- OVERLAY_JS


def test_overlay_js_contains_redaction_machinery():
    assert "redact" in OVERLAY_JS
    assert "scramble" in OVERLAY_JS
    assert "MutationObserver" in OVERLAY_JS


def test_overlay_js_defines_redact_function_and_window_api():
    # The redact entrypoint Python calls (window.__demoreel.redact) is a top-level function
    # in the toolkit, and the __demoreel API object is published on window.
    assert "function redact(" in OVERLAY_JS
    assert "window.__demoreel" in OVERLAY_JS
    api_idx = OVERLAY_JS.index("function redact(")
    assert "redact" in OVERLAY_JS[api_idx : api_idx + 40]


def test_overlay_js_is_an_iife_string():
    body = OVERLAY_JS.strip()
    assert body.startswith("(()")
    assert body.endswith(")();")


# -------------------------------------------------------------------------------- _clamp


def test_clamp_within_bounds_returns_value():
    assert _clamp(5.0, 1.0, 10.0) == 5.0


def test_clamp_below_lo_returns_lo():
    assert _clamp(-3.0, 1.0, 10.0) == 1.0


def test_clamp_above_hi_returns_hi():
    assert _clamp(99.0, 1.0, 10.0) == 10.0


def test_clamp_at_bounds_is_inclusive():
    assert _clamp(1.0, 1.0, 10.0) == 1.0
    assert _clamp(10.0, 1.0, 10.0) == 10.0
