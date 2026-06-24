"""Unit tests for spec templating + the newer spec fields/presets.

Covers ``substitute_vars`` / ``load_spec`` variable expansion (post-parse, so comments
never expand), the resolution-preset table on ``Quality``, and the device/redaction/
follow-new-tab fields. All pure-model — no browser, ffmpeg, or network.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from demoreel.spec import (
    FrameConfig,
    Prelude,
    Quality,
    Scene,
    load_spec,
    substitute_vars,
)

# --------------------------------------------------------------------------- substitute_vars


def test_substitute_from_overrides() -> None:
    assert substitute_vars("go ${URL} now", {"URL": "https://x.test"}) == "go https://x.test now"


def test_substitute_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DR_TENANT", "acme")
    assert substitute_vars("tenant=${DR_TENANT}") == "tenant=acme"


def test_override_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # overrides are merged ON TOP of os.environ, so the override takes precedence.
    monkeypatch.setenv("DR_PICK", "from_env")
    assert substitute_vars("${DR_PICK}", {"DR_PICK": "from_override"}) == "from_override"


def test_default_used_when_unset() -> None:
    # nothing in overrides or env -> the :-default branch fires.
    assert substitute_vars("${DR_NOPE_UNSET:-fallback}") == "fallback"


def test_default_ignored_when_set() -> None:
    assert substitute_vars("${X:-fallback}", {"X": "real"}) == "real"


def test_empty_default_is_used() -> None:
    # an empty default ("") is still a default — group(2) is "" (not None), so no error.
    assert substitute_vars("[${DR_NOPE_UNSET:-}]") == "[]"


def test_missing_var_no_default_raises() -> None:
    with pytest.raises(ValueError, match=r"DR_DEFINITELY_MISSING"):
        substitute_vars("${DR_DEFINITELY_MISSING}")


def test_multiple_vars_in_one_string() -> None:
    out = substitute_vars(
        "${SCHEME}://${HOST}/${PATH}",
        {"SCHEME": "https", "HOST": "h.test", "PATH": "p"},
    )
    assert out == "https://h.test/p"


def test_no_vars_string_unchanged() -> None:
    # contains $, {, } but never the ${NAME} shape, so nothing matches and it passes through.
    s = "a plain string with $ and { } but no expansion for $X or {Y}"
    assert substitute_vars(s) == s


def test_default_with_special_chars() -> None:
    # the default may contain anything except a closing brace.
    assert substitute_vars("${U:-https://a.test/x?y=1&z=2}") == "https://a.test/x?y=1&z=2"


# --------------------------------------------------------------------------- load_spec overrides


def test_load_spec_substitutes_value(write_spec) -> None:
    path = write_spec(
        {
            "url": "${DEMO_URL}",
            "scenes": [{"goto": "/"}],
        }
    )
    spec = load_spec(path, {"DEMO_URL": "https://tenant.test"})
    assert spec.url == "https://tenant.test"


def test_load_spec_substitutes_nested_value(write_spec) -> None:
    # substitution walks the whole tree, including list/dict values.
    path = write_spec(
        {
            "title": "${WHO}'s demo",
            "url": "https://x.test",
            "scenes": [{"narrate": "Welcome ${WHO}", "goto": "/"}],
        }
    )
    spec = load_spec(path, {"WHO": "Alex"})
    assert spec.title == "Alex's demo"
    assert spec.scenes[0].narrate == "Welcome Alex"


def test_load_spec_does_not_substitute_comment(tmp_path) -> None:
    # ${NOPE} lives only in a YAML comment; comments are gone after parsing, so this must
    # NOT raise even though NOPE is undefined. This is the whole reason substitution is
    # post-parse rather than a raw-text pass.
    path = tmp_path / "with_comment.yaml"
    path.write_text(
        "# this is a comment with ${NOPE} that must never be substituted\n"
        "url: https://x.test\n"
        "scenes:\n"
        "  - goto: /\n"
    )
    spec = load_spec(path)  # no overrides; would raise if ${NOPE} were expanded
    assert spec.url == "https://x.test"


def test_load_spec_missing_var_in_value_raises(write_spec) -> None:
    path = write_spec({"url": "${UNDEFINED_IN_VALUE}", "scenes": [{"goto": "/"}]})
    with pytest.raises(ValueError, match=r"UNDEFINED_IN_VALUE"):
        load_spec(path)


# --------------------------------------------------------------------------- resolution presets


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [
        ("vertical", (1080, 1920)),
        ("9:16", (1080, 1920)),
        ("square", (1080, 1080)),
        ("1:1", (1080, 1080)),
        ("portrait", (1080, 1350)),
        ("4:5", (1080, 1350)),
        ("16:9", (1920, 1080)),
        ("1080p", (1920, 1080)),
        ("720p", (1280, 720)),
        ("4k", (3840, 2160)),
    ],
)
def test_resolution_preset_size(resolution: str, expected: tuple[int, int], make_spec) -> None:
    spec = make_spec(quality={"resolution": resolution})
    assert spec.quality.size == expected
    assert spec.output_size() == expected


def test_resolution_preset_case_insensitive(make_spec) -> None:
    # _normalize lowercases the key before lookup.
    spec = make_spec(quality={"resolution": "VERTICAL"})
    assert spec.quality.size == (1080, 1920)


def test_resolution_custom_tuple_rounded_down_to_even(make_spec) -> None:
    # odd dims fail inside libx264/yuv420p, so _normalize rounds each axis DOWN to even.
    spec = make_spec(quality={"resolution": (1281, 721)})
    assert spec.quality.size == (1280, 720)


def test_resolution_even_tuple_unchanged() -> None:
    q = Quality(resolution=(1920, 1080))
    assert q.size == (1920, 1080)


def test_resolution_unknown_string_raises() -> None:
    with pytest.raises(ValidationError, match=r"unknown resolution"):
        Quality(resolution="ultrawide")


def test_resolution_non_positive_raises() -> None:
    with pytest.raises(ValidationError, match=r"must be positive"):
        Quality(resolution=(0, 1080))


def test_resolution_negative_raises() -> None:
    with pytest.raises(ValidationError, match=r"must be positive"):
        Quality(resolution=(1920, -10))


def test_quality_default_is_1080p() -> None:
    # mode="after" validators run on the default value too, so the default resolves to a tuple.
    assert Quality().size == (1920, 1080)


# --------------------------------------------------------------------------- frame device


def test_frame_device_default_none(make_spec) -> None:
    assert make_spec().frame.device == "none"
    assert FrameConfig().device == "none"


@pytest.mark.parametrize("device", ["phone", "tablet", "none"])
def test_frame_device_accepted(device: str, make_spec) -> None:
    spec = make_spec(frame={"device": device})
    assert spec.frame.device == device


def test_frame_device_unknown_raises(make_spec) -> None:
    with pytest.raises(ValidationError):
        make_spec(frame={"device": "watch"})


# --------------------------------------------------------------------------- prelude redaction


def test_prelude_redact_defaults() -> None:
    p = Prelude()
    assert p.redact == []
    assert p.redact_mode == "scramble"


def test_prelude_redact_default_is_independent() -> None:
    # default_factory=list -> each instance gets its own list, not a shared mutable default.
    a = Prelude()
    b = Prelude()
    a.redact.append(".pii")
    assert b.redact == []


@pytest.mark.parametrize("mode", ["scramble", "block", "label"])
def test_prelude_redact_mode_accepted(mode: str) -> None:
    p = Prelude(redact=[".name", "#email"], redact_mode=mode)
    assert p.redact_mode == mode
    assert p.redact == [".name", "#email"]


def test_prelude_redact_mode_unknown_raises() -> None:
    with pytest.raises(ValidationError):
        Prelude(redact_mode="encrypt")


# --------------------------------------------------------------------------- scene follow_new_tab


def test_scene_follow_new_tab_default_false() -> None:
    assert Scene().follow_new_tab is False


def test_scene_follow_new_tab_true() -> None:
    assert Scene(follow_new_tab=True).follow_new_tab is True
