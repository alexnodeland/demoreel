"""demoreel command-line interface.

demoreel render scenes.yaml [-o out.mp4] [--headed] [--engine say] [--preview]
                           [--storyboard] [--keep]
demoreel validate scenes.yaml      # parse + print the scene plan (no browser/TTS)
demoreel check scenes.yaml         # open the page and verify every selector resolves
demoreel init [path.yaml]          # write a starter spec
demoreel voices                    # list available TTS voices
demoreel doctor                    # check the environment is ready
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "starter.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demoreel", description=__doc__)
    parser.add_argument("--version", action="version", version=f"demoreel {__version__}")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print the full traceback on failure (or set DEMOREEL_DEBUG=1)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_set(p):
        p.add_argument(
            "--set",
            metavar="KEY=VALUE",
            action="append",
            default=[],
            help="substitute ${KEY} in the spec (repeatable); also reads the environment",
        )

    pr = sub.add_parser("render", help="render a demo video from a YAML spec")
    pr.add_argument("spec")
    pr.add_argument("-o", "--output", help="output mp4 path (overrides spec.output)")
    pr.add_argument("--headed", action="store_true", help="show the browser window")
    pr.add_argument(
        "--engine", help="override voice engine (piper|kokoro|say|espeak|openai|elevenlabs)"
    )
    pr.add_argument("--preview", action="store_true", help="fast low-res pass for iteration")
    pr.add_argument("--storyboard", action="store_true", help="also write a contact sheet png")
    pr.add_argument("--gif", action="store_true", help="also export an animated GIF")
    pr.add_argument("--webp", action="store_true", help="also export an animated WebP")
    pr.add_argument(
        "--player", action="store_true", help="also write a self-contained HTML chapter player"
    )
    pr.add_argument("--gif-width", type=int, default=720, help="gif/webp width in px (default 720)")
    pr.add_argument("--gif-fps", type=int, default=15, help="gif/webp frame rate (default 15)")
    pr.add_argument("--keep", action="store_true", help="keep the .demoreel build dir")
    add_set(pr)

    pv = sub.add_parser("validate", help="parse a spec and print the plan")
    pv.add_argument("spec")
    add_set(pv)

    pc = sub.add_parser("check", help="open the page and verify selectors resolve")
    pc.add_argument("spec")
    pc.add_argument("--headed", action="store_true")
    add_set(pc)

    pi = sub.add_parser("init", help="write a starter spec")
    pi.add_argument("path", nargs="?", default="demo.yaml")

    pt = sub.add_parser("theme", help="derive a color palette from a logo image")
    pt.add_argument("logo", help="path to a logo image (png/jpg/svg-raster)")

    sub.add_parser("voices", help="list available TTS voices")
    sub.add_parser("doctor", help="check the environment")

    args = parser.parse_args(argv)
    return {
        "render": _render,
        "validate": _validate,
        "check": _check,
        "init": _init,
        "theme": _theme,
        "voices": lambda _a: _voices(),
        "doctor": lambda _a: _doctor(),
    }[args.cmd](args)


def _overrides(args) -> dict[str, str]:
    """Parse repeated --set KEY=VALUE into a dict (env still applies underneath)."""
    out: dict[str, str] = {}
    for item in getattr(args, "set", []) or []:
        key, sep, val = item.partition("=")
        if not sep:
            raise ValueError(f"--set expects KEY=VALUE, got {item!r}")
        out[key.strip()] = val
    return out


def _report_error(args, prefix: str, exc: Exception) -> int:
    if getattr(args, "debug", False) or os.environ.get("DEMOREEL_DEBUG"):
        import traceback

        traceback.print_exc()
    print(f"✗ {prefix}: {exc}", file=sys.stderr)
    return 1


def _render(args) -> int:
    from .render import render

    try:
        out = render(
            args.spec,
            output=args.output,
            keep_build=args.keep,
            headed=args.headed,
            voice_engine=args.engine,
            preview=args.preview,
            overrides=_overrides(args),
            gif=args.gif,
            webp=args.webp,
            player=args.player,
            gif_width=args.gif_width,
            gif_fps=args.gif_fps,
            progress=lambda m: print(f"  • {m}"),
        )
    except Exception as exc:  # noqa: BLE001
        return _report_error(args, "render failed", exc)
    print(f"✓ {out}")
    for side in (
        out.with_suffix(".srt"),
        out.with_suffix(".vtt"),
        out.with_suffix(".gif"),
        out.with_suffix(".webp"),
        out.with_suffix(".player.html"),
        out.parent / (out.stem + ".transcript.md"),
    ):
        if side.exists():
            print(f"✓ {side}")
    if args.storyboard:
        sb = out.with_suffix(".storyboard.png")
        if _storyboard(str(out), str(sb)):
            print(f"✓ {sb}")
    return 0


def _validate(args) -> int:
    from .render import plan

    try:
        spec, rows, total = plan(args.spec, _overrides(args))
    except Exception as exc:  # noqa: BLE001
        return _report_error(args, "invalid spec", exc)
    print(
        f"\n{spec.title}  —  {len(rows)} scenes, ~{total:.0f}s estimated  ·  preset: {spec.preset}\n"
    )
    print(f"  {'#':>2}  {'zoom':<6} {'action':<42} narration")
    print(f"  {'-' * 2}  {'-' * 6} {'-' * 42} {'-' * 28}")
    for r in rows:
        nar = (r.narration[:56] + "…") if len(r.narration) > 56 else r.narration
        act = (r.action[:40] + "…") if len(r.action) > 40 else r.action
        print(f"  {r.index:>2}  {r.zoom:<6} {act:<42} {nar}")
    w, h = spec.output_size()
    shell = spec.frame.device if spec.frame.device != "none" else spec.frame.chrome
    print(
        f"\n  voice: {spec.voice.engine}  •  {w}×{h} @ {spec.fps}fps  •  "
        f"frame: {spec.frame.style}/{shell}  •  captions: {spec.captions.style}"
    )
    # Only full_bleed actually letterboxes on a mismatch; studio/device float the content on a
    # backdrop on purpose (a vertical phone demo from a wide viewport is the intended look).
    if spec.frame.style == "full_bleed" and spec.aspect_mismatch() > 0.02:
        vw, vh = spec.viewport
        print(
            f"  ⚠ viewport {vw}×{vh} and output {w}×{h} differ in aspect — the window will "
            "be letterboxed. Match them for a full, crisp frame."
        )
    print("  ✓ spec is valid\n")
    return 0


def _check(args) -> int:
    from .check import check_live
    from .spec import load_spec

    try:
        spec = load_spec(args.spec, _overrides(args))
        if args.headed:
            spec.headless = False
        rows = check_live(spec)
    except Exception as exc:  # noqa: BLE001
        return _report_error(args, "check failed", exc)
    bad = [r for r in rows if not r.ok]
    print(f"\nselector check — {len(rows)} selectors, {len(bad)} missing\n")
    for r in rows:
        mark = "✓" if r.ok else "✗"
        print(f"  {mark} scene {r.scene:>2}: {r.selector}" + (f"  ({r.note})" if not r.ok else ""))
    print()
    return 0 if not bad else 1


def _init(args) -> int:
    dest = Path(args.path)
    if dest.exists():
        print(f"✗ {dest} already exists", file=sys.stderr)
        return 1
    if not EXAMPLE.exists():
        print(f"✗ bundled example not found at {EXAMPLE}", file=sys.stderr)
        return 1
    dest.write_text(EXAMPLE.read_text())
    print(f"✓ wrote starter spec → {dest}\n  edit it, then: demoreel render {dest}")
    return 0


def _theme(args) -> int:
    from .swatch import palette_from_logo

    try:
        pal = palette_from_logo(args.logo)
    except Exception as exc:  # noqa: BLE001
        return _report_error(args, "could not read logo", exc)
    accent = pal["accent"]
    bg = pal["background"]
    print(f"\npalette from {args.logo}")
    print(f"  accent      {accent}")
    print(f"  background  {bg[0]} → {bg[1]}")
    print(f"  dominant    {'  '.join(pal['colors'])}\n")
    print("drop this into your spec:\n")
    print("brand:")
    print(f'  color: "{accent}"')
    print("cursor:")
    print(f'  color: "{accent}"')
    print("captions:")
    print(f'  accent: "{accent}"')
    print("frame:")
    print("  background:")
    print(f'    colors: ["{bg[0]}", "{bg[1]}"]')
    print("    angle: 135\n")
    return 0


def _voices() -> int:
    from .tts import DEFAULT_KOKORO_VOICE, DEFAULT_PIPER_VOICE, PROVIDERS, list_say_voices

    print("\nvoice engines (✓ = ready on this machine):")
    for name, prov in PROVIDERS.items():
        print(f"  {'✓' if prov.available() else '–'} {name}")
    print(f"\npiper (local OSS, default voice {DEFAULT_PIPER_VOICE}):")
    print("  more at https://huggingface.co/rhasspy/piper-voices (e.g. en_US-ryan-high)")
    say = list_say_voices()
    if say:
        print(
            f"\nmacOS `say` ({len(say)}): {', '.join(say[:20])}" + (" …" if len(say) > 20 else "")
        )
    print(f"\nkokoro: {DEFAULT_KOKORO_VOICE}, af_bella, am_adam, … (needs --extra kokoro)")
    print(
        "openai: alloy, echo, fable, onyx, nova, shimmer "
        "(needs OPENAI_API_KEY; set voice.base_url for compatible endpoints)"
    )
    print("elevenlabs: <voice_id> (needs ELEVENLABS_API_KEY, no package)\n")
    return 0


def _doctor() -> int:
    ok = True
    print("\ndemoreel doctor\n")

    def check(label, fn):
        nonlocal ok
        try:
            detail = fn()
            print(f"  ✓ {label}{f'  ({detail})' if detail else ''}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  ✗ {label}: {exc}")

    check("pydantic", lambda: __import__("pydantic").VERSION)
    check("pyyaml", lambda: __import__("yaml").__version__)
    check("numpy", lambda: __import__("numpy").__version__)
    check("Pillow", lambda: __import__("PIL").__version__)
    check("opencv", lambda: __import__("cv2").__version__)
    check("moviepy", lambda: __import__("moviepy").__version__)
    check("ffmpeg (imageio)", lambda: __import__("imageio_ffmpeg").get_ffmpeg_exe())
    check("playwright chromium", _check_chromium)

    import shutil as _sh

    print("\n  voice engines:")
    for label, mod in [
        ("piper (--extra piper)", "piper"),
        ("kokoro (--extra kokoro)", "kokoro_onnx"),
        ("openai (--extra cloud)", "openai"),
    ]:
        try:
            __import__(mod)
            print(f"  ✓ {label}")
        except Exception:  # noqa: BLE001
            print(f"  – {label} (not installed)")
    say_note = ""
    if _sh.which("say") and not _sh.which("afconvert"):
        say_note = "  (afconvert missing → ffmpeg fallback)"
    print(f"  {'✓' if _sh.which('say') else '–'} macOS say{say_note}")
    print(f"  {'✓' if _sh.which('espeak-ng') else '–'} espeak-ng (cross-platform fallback)")
    print(f"  {'✓' if os.environ.get('OPENAI_API_KEY') else '–'} OPENAI_API_KEY")
    print(
        f"  {'✓' if os.environ.get('ELEVENLABS_API_KEY') else '–'} ELEVENLABS_API_KEY "
        "(elevenlabs needs no package)"
    )

    print("\n  captions:")
    try:
        __import__("faster_whisper")
        print("  ✓ faster-whisper (karaoke)")
    except Exception:  # noqa: BLE001
        print(
            "  – faster-whisper (karaoke needs `--extra align`; pill/lower_third work without it)"
        )

    from .tts import CACHE_DIR, DEFAULT_PIPER_VOICE, PIPER_DIR

    voice_file = PIPER_DIR / f"{DEFAULT_PIPER_VOICE}.onnx"
    if voice_file.exists():
        print(f"\n  cache: {CACHE_DIR}  ·  default piper voice ready ✓")
    else:
        print(
            f"\n  cache: {CACHE_DIR}  ·  default piper voice will download "
            "(~60MB, from HuggingFace) on first piper render"
        )

    print(
        "\n" + ("  ready ✓\n" if ok else "  missing required deps — `uv sync` in the engine dir\n")
    )
    return 0 if ok else 1


def _check_chromium() -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        path = p.chromium.executable_path
    if not path or not Path(path).exists():
        raise RuntimeError("run `playwright install chromium`")
    return "installed"


def _storyboard(video_path: str, out_png: str, cols: int = 3, rows: int = 3) -> bool:
    """Tile evenly-spaced frames into a contact sheet."""
    try:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        n = cols * rows
        idxs = [int(total * (k + 0.5) / n) for k in range(n)]
        tiles = []
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            tiles.append(cv2.resize(frame, (640, 360)))
        cap.release()
        if not tiles:
            return False
        while len(tiles) < n:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[r * cols : (r + 1) * cols]) for r in range(rows)])
        cv2.imwrite(out_png, grid)
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    raise SystemExit(main())
