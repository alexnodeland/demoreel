"""CLI surface tests — exercise demoreel.cli.main and its helpers WITHOUT a browser/render.

Everything here drives the pure command path: argument parsing, --set parsing, the init /
validate / theme subcommands. render/check are deliberately not invoked (they open Chromium
and synthesize audio). Output is captured with capsys; files live under tmp_path.
"""

from __future__ import annotations

import argparse

import pytest
from PIL import Image

from demoreel import __version__, cli

# --------------------------------------------------------------------------- _overrides


def _ns(set_list: list[str] | None) -> argparse.Namespace:
    """A minimal Namespace shaped like the `set` arg that _overrides reads."""
    return argparse.Namespace(set=set_list)


def test_overrides_parses_simple_pair() -> None:
    assert cli._overrides(_ns(["KEY=VALUE"])) == {"KEY": "VALUE"}


def test_overrides_value_keeps_embedded_equals() -> None:
    # partition('=') splits on the FIRST '=', so the value retains the rest verbatim.
    assert cli._overrides(_ns(["K=a=b"])) == {"K": "a=b"}


def test_overrides_strips_key_whitespace_but_not_value() -> None:
    assert cli._overrides(_ns(["  K  = v "])) == {"K": " v "}


def test_overrides_empty_list_returns_empty_dict() -> None:
    assert cli._overrides(_ns([])) == {}


def test_overrides_none_returns_empty_dict() -> None:
    # `set` may be None (e.g. on a Namespace that never had the flag); the `or []` guards it.
    assert cli._overrides(_ns(None)) == {}


def test_overrides_missing_attr_returns_empty_dict() -> None:
    # getattr(..., "set", []) default path — Namespace without a `set` attribute at all.
    assert cli._overrides(argparse.Namespace()) == {}


def test_overrides_multiple_pairs_accumulate() -> None:
    assert cli._overrides(_ns(["A=1", "B=2"])) == {"A": "1", "B": "2"}


def test_overrides_later_pair_wins_on_duplicate_key() -> None:
    assert cli._overrides(_ns(["A=1", "A=2"])) == {"A": "2"}


def test_overrides_empty_value_is_allowed() -> None:
    # A trailing '=' is a present separator with an empty value — valid, not malformed.
    assert cli._overrides(_ns(["A="])) == {"A": ""}


def test_overrides_without_equals_raises_value_error() -> None:
    with pytest.raises(ValueError, match="KEY=VALUE"):
        cli._overrides(_ns(["KV"]))


# --------------------------------------------------------------------------- --version


def test_version_flag_exits_zero_and_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "demoreel" in out
    assert __version__ in out


# --------------------------------------------------------------------------- init


def test_init_writes_starter_and_returns_zero(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    dest = tmp_path / "d.yaml"
    rc = cli.main(["init", str(dest)])
    assert rc == 0
    assert dest.exists()
    assert dest.read_text() == cli.EXAMPLE.read_text()
    out = capsys.readouterr().out
    assert "✓ wrote starter spec" in out
    assert str(dest) in out


def test_init_refuses_to_overwrite_existing(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    dest = tmp_path / "d.yaml"
    assert cli.main(["init", str(dest)]) == 0
    capsys.readouterr()  # drain the success message

    rc = cli.main(["init", str(dest)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert captured.out == ""


# --------------------------------------------------------------------------- validate


def test_validate_on_init_output_is_valid(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    spec = tmp_path / "starter.yaml"
    assert cli.main(["init", str(spec)]) == 0
    capsys.readouterr()  # drain init output

    rc = cli.main(["validate", str(spec)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "✓ spec is valid" in out


def test_validate_prints_plan_header_and_scene_count(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "starter.yaml"
    assert cli.main(["init", str(spec)]) == 0
    capsys.readouterr()

    assert cli.main(["validate", str(spec)]) == 0
    out = capsys.readouterr().out
    # plan() reports one row per scene; the starter ships three.
    assert "3 scenes" in out
    assert "narration" in out  # the table header
    assert "voice:" in out


def test_validate_set_substitutes_variable(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A unique var name so a stray environment variable can't satisfy it for us.
    monkeypatch.delenv("DEMO_BRAND", raising=False)
    spec = tmp_path / "branded.yaml"
    spec.write_text(
        'title: "${DEMO_BRAND} Tour"\n'
        'url: "https://example.com"\n'
        "scenes:\n"
        '  - narrate: "hello"\n'
        '    goto: "/"\n'
    )
    rc = cli.main(["validate", str(spec), "--set", "DEMO_BRAND=Acme"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Acme" in out
    assert "✓ spec is valid" in out


def test_validate_missing_var_without_set_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DEMO_BRAND", raising=False)
    spec = tmp_path / "branded.yaml"
    spec.write_text(
        'title: "${DEMO_BRAND} Tour"\n'
        'url: "https://example.com"\n'
        "scenes:\n"
        '  - narrate: "hello"\n'
        '    goto: "/"\n'
    )
    rc = cli.main(["validate", str(spec)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "invalid spec" in err
    assert "DEMO_BRAND" in err


def test_validate_nonexistent_file_returns_one(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["validate", str(tmp_path / "missing.yaml")])
    assert rc == 1
    assert "invalid spec" in capsys.readouterr().err


# --------------------------------------------------------------------------- theme


def _solid_logo(path, color: tuple[int, int, int] = (37, 99, 235)) -> None:
    Image.new("RGB", (64, 64), color).save(path)


def test_theme_prints_accent_and_hex(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    logo = tmp_path / "logo.png"
    _solid_logo(logo)
    rc = cli.main(["theme", str(logo)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "accent" in out
    assert "#" in out
    # The accent line and the spec snippet both surface a hex color.
    assert "color:" in out


def test_theme_missing_file_returns_one(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["theme", str(tmp_path / "nope.png")])
    assert rc == 1
    assert "could not read logo" in capsys.readouterr().err


# --------------------------------------------------------------------------- aspect warning gating


_MISMATCHED_SPEC = (
    'title: "{title}"\n'
    "preset: {preset}\n"
    "viewport: [1080, 1920]\n"  # vertical capture vs a landscape (1080p) output → big mismatch
    "quality: {{ resolution: 1080p }}\n"
    'url: "https://example.com"\n'
    "scenes:\n"
    '  - narrate: "hi"\n'
    '    goto: "/"\n'
)


def test_studio_mismatch_does_not_warn_letterbox(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = tmp_path / "studio.yaml"
    spec.write_text(_MISMATCHED_SPEC.format(title="Studio", preset="studio"))
    assert cli.main(["validate", str(spec)]) == 0
    out = capsys.readouterr().out
    assert "letterboxed" not in out
    assert "⚠" not in out
    assert "✓ spec is valid" in out


def test_full_bleed_mismatch_does_warn_letterbox(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The `minimal` preset is the only built-in full_bleed style.
    spec = tmp_path / "minimal.yaml"
    spec.write_text(_MISMATCHED_SPEC.format(title="Minimal", preset="minimal"))
    assert cli.main(["validate", str(spec)]) == 0
    out = capsys.readouterr().out
    assert "letterboxed" in out
    assert "⚠" in out
    assert "✓ spec is valid" in out  # still valid — a warning, not an error


def test_full_bleed_matching_aspect_does_not_warn(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Same full_bleed preset but a matching 16:9 viewport → no letterbox warning.
    spec = tmp_path / "minimal-match.yaml"
    spec.write_text(
        'title: "Minimal"\n'
        "preset: minimal\n"
        "viewport: [1920, 1080]\n"
        "quality: { resolution: 1080p }\n"
        'url: "https://example.com"\n'
        "scenes:\n"
        '  - narrate: "hi"\n'
        '    goto: "/"\n'
    )
    assert cli.main(["validate", str(spec)]) == 0
    out = capsys.readouterr().out
    assert "letterboxed" not in out


# --------------------------------------------------------------------------- argparse guards


def test_no_subcommand_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    # subparsers are required=True, so a bare invocation is a usage error (exit 2).
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code != 0


def test_unknown_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["frobnicate"])
    assert excinfo.value.code != 0
