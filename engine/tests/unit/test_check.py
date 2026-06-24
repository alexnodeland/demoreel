"""Unit tests for the pure selector helpers in ``demoreel.check``.

These cover ``_action_selector`` (what selector a scene's primary action probes) and
``_post_selectors`` (the annotation/wait selectors checked after the action runs). Both are
pure functions — no browser, no network — so they live in the default (unmarked) suite.
"""

from __future__ import annotations

import pytest

from demoreel.check import _action_selector, _post_selectors
from demoreel.spec import Arrow, Callout, Scene, ScrollAction, TypeAction

# --------------------------------------------------------------------------- _action_selector


def test_click_returns_selector_string():
    assert _action_selector("click", "#submit") == "#submit"


def test_hover_returns_selector_string():
    assert _action_selector("hover", ".menu-item") == ".menu-item"


def test_click_stringifies_non_string_value():
    # _action_selector does str(val) for click/hover — it does not assume a str input.
    assert _action_selector("click", 123) == "123"


def test_type_with_typeaction_selector_returns_that_selector():
    ta = TypeAction(selector="#search", text="hello")
    assert _action_selector("type", ta) == "#search"


def test_type_with_typeaction_without_selector_returns_none():
    ta = TypeAction(text="hello")  # selector defaults to None
    assert _action_selector("type", ta) is None


def test_type_without_typeaction_returns_none():
    # A bare-string `type:` action is not a TypeAction instance, so the type branch is
    # skipped and the function falls through to None.
    assert _action_selector("type", "just some text") is None


def test_scroll_with_to_returns_selector():
    sa = ScrollAction(to="#section-3")
    assert _action_selector("scroll", sa) == "#section-3"


def test_scroll_by_pixels_returns_none():
    sa = ScrollAction(by=400)  # to is None
    assert _action_selector("scroll", sa) is None


@pytest.mark.parametrize(
    ("kind", "val"),
    [
        ("goto", "/dashboard"),
        ("press", "Enter"),
        ("wait", 1.5),
    ],
)
def test_non_selector_actions_return_none(kind, val):
    assert _action_selector(kind, val) is None


# --------------------------------------------------------------------------- _post_selectors


def test_no_annotations_returns_empty_list():
    scene = Scene()
    assert _post_selectors(scene) == []


def test_highlight_only():
    scene = Scene(highlight="#hl")
    assert _post_selectors(scene) == ["#hl"]


def test_spotlight_only():
    scene = Scene(spotlight="#sp")
    assert _post_selectors(scene) == ["#sp"]


def test_focus_only():
    scene = Scene(focus="#fc")
    assert _post_selectors(scene) == ["#fc"]


def test_wait_for_only():
    scene = Scene(wait_for="#wf")
    assert _post_selectors(scene) == ["#wf"]


def test_callout_with_at_is_collected():
    scene = Scene(callout=Callout(text="look here", at="#target"))
    assert _post_selectors(scene) == ["#target"]


def test_callout_without_at_is_skipped():
    # A centered-banner callout (at=None) contributes no selector.
    scene = Scene(callout=Callout(text="centered banner"))
    assert _post_selectors(scene) == []


def test_callout_as_plain_string_is_skipped():
    # callout may be a bare string; only Callout instances with `at` contribute.
    scene = Scene(callout="just a banner")
    assert _post_selectors(scene) == []


def test_arrow_to_is_collected():
    scene = Scene(arrow=Arrow(to="#arrow-target"))
    assert _post_selectors(scene) == ["#arrow-target"]


def test_order_and_inclusion_with_several_set():
    # Order is fixed: highlight, spotlight, focus, wait_for, then callout.at, then arrow.to.
    scene = Scene(
        highlight="#hl",
        spotlight="#sp",
        focus="#fc",
        wait_for="#wf",
        callout=Callout(text="c", at="#co"),
        arrow=Arrow(to="#ar"),
    )
    assert _post_selectors(scene) == ["#hl", "#sp", "#fc", "#wf", "#co", "#ar"]


def test_subset_preserves_relative_order():
    # Only spotlight + wait_for + arrow set: relative ordering is preserved, gaps skipped.
    scene = Scene(spotlight="#sp", wait_for="#wf", arrow=Arrow(to="#ar"))
    assert _post_selectors(scene) == ["#sp", "#wf", "#ar"]


def test_callout_before_arrow():
    scene = Scene(callout=Callout(text="c", at="#co"), arrow=Arrow(to="#ar"))
    assert _post_selectors(scene) == ["#co", "#ar"]
