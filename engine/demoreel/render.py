"""Orchestration — spec -> voiceover -> capture -> compose -> mp4.

Runs TTS first (so capture knows how long to dwell), normalizes the voiceover, optionally
aligns words for karaoke captions, records, then composes.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .audio import normalize_wav
from .capture import capture
from .compose import compose
from .spec import DemoSpec, ScrollAction, TypeAction, load_spec
from .tts import synthesize

Progress = Callable[[str], None]


def render(
    spec_path: str | Path,
    output: str | Path | None = None,
    keep_build: bool = False,
    progress: Progress | None = None,
    headed: bool = False,
    voice_engine: str | None = None,
    preview: bool = False,
    overrides: dict[str, str] | None = None,
    gif: bool = False,
    webp: bool = False,
    player: bool = False,
    gif_width: int = 720,
    gif_fps: int = 15,
) -> Path:
    spec = load_spec(spec_path, overrides)
    if headed:
        spec.headless = False
    if voice_engine:
        spec.voice.engine = voice_engine  # type: ignore[assignment]
    log = progress or (lambda *_: None)
    if preview:
        # fast pass: small + low fps, no karaoke/sfx (cached narration is reused as-is)
        spec.quality.resolution = (1280, 720)
        spec.quality.scale = 1
        spec.fps = 15
        spec.captions.style = "pill"
        spec.audio.sfx.enabled = False
        log("Preview mode: 1280×720 @ 15fps, pill captions, SFX off")

    out = Path(output) if output else Path(spec.output)
    build_dir = out.parent / ".demoreel" / out.stem
    build_dir.mkdir(parents=True, exist_ok=True)

    # 1. voiceover ------------------------------------------------------------------
    log(f"Synthesizing voiceover ({spec.voice.engine}) for {len(spec.scenes)} scenes…")
    narrations: list[tuple[str | None, float]] = []
    scene_texts: dict[int, str] = {}
    for i, scene in enumerate(spec.scenes):
        if scene.narrate:
            wav = build_dir / f"scene_{i:03d}.wav"
            dur = synthesize(scene.narrate, wav, spec.voice, log=log)
            if spec.audio.normalize:
                normalize_wav(str(wav))  # amplitude only; duration unchanged
            narrations.append((str(wav), dur))
            scene_texts[i] = scene.narrate
        else:
            narrations.append((None, 0.0))

    intro_wav = _card_voice(spec.intro, build_dir / "intro.wav", spec, log)
    outro_wav = _card_voice(spec.outro, build_dir / "outro.wav", spec, log)

    # 2. word alignment (karaoke captions) ------------------------------------------
    word_timings: dict[int, list] = {}
    if spec.captions.style == "karaoke":
        word_timings = _align(spec, narrations, log)

    # 3. capture --------------------------------------------------------------------
    log("Recording browser walkthrough…")
    cap = capture(spec, narrations, build_dir, log=log)
    log(f"Captured {cap.duration:.1f}s across {len(cap.scenes)} scenes.")

    # 4. compose --------------------------------------------------------------------
    log("Composing video (framing, camera, captions, audio)…")
    final = compose(spec, cap, scene_texts, build_dir, out, intro_wav, outro_wav, word_timings)

    # 5. optional extra outputs (gif / webp / interactive player) --------------------
    _extra_outputs(spec, cap, final, intro_wav, gif, webp, player, gif_width, gif_fps, log)

    if not keep_build:
        shutil.rmtree(build_dir, ignore_errors=True)
    log(f"Done → {final}")
    return final


def _extra_outputs(
    spec: DemoSpec,
    cap,
    final: Path,
    intro_wav: str | None,
    gif: bool,
    webp: bool,
    player: bool,
    gif_width: int,
    gif_fps: int,
    log: Progress,
) -> None:
    if gif:
        from .export import mp4_to_gif

        out = mp4_to_gif(final, final.with_suffix(".gif"), width=gif_width, fps=gif_fps, log=log)
        log(f"GIF → {out}")
    if webp:
        from .export import mp4_to_webp

        out = mp4_to_webp(final, final.with_suffix(".webp"), width=gif_width, fps=gif_fps, log=log)
        log(f"WebP → {out}")
    if player:
        from .player import build_player

        vtt = final.with_suffix(".vtt")
        out = build_player(
            final.with_suffix(".player.html"),
            video_filename=final.name,
            title=spec.title,
            chapters=_chapter_markers(spec, cap, intro_wav),
            vtt_filename=vtt.name if vtt.exists() else None,
            accent=spec.captions.accent,
        )
        log(f"Player → {out}")


def _chapter_markers(spec: DemoSpec, cap, intro_wav: str | None) -> list[tuple[float, str]]:
    """Chapter seek points on the FINAL timeline (intro card + each scene that names a chapter).

    Mirrors compose's content offset: the content video starts after the intro card, minus the
    crossfade overlap. Scene start times come from the capture timeline (real, not estimated)."""
    from .spec import Chapter

    intro_dur = 0.0
    if spec.intro:
        intro_dur = spec.intro.seconds
        if intro_wav and Path(intro_wav).exists():
            from .tts import wav_duration

            intro_dur = max(spec.intro.seconds, wav_duration(intro_wav) + 0.8)
    content_start = intro_dur
    if intro_dur > 0 and spec.transition.type == "crossfade":
        content_start = max(0.0, intro_dur - spec.transition.duration)

    marks: list[tuple[float, str]] = []
    if spec.intro:
        marks.append((0.0, spec.intro.title))
    for st in cap.scenes:
        scene = spec.scenes[st.index]
        label = None
        if isinstance(scene.chapter, Chapter):
            label = scene.chapter.title
        elif isinstance(scene.chapter, str):
            label = scene.chapter
        elif scene.name:
            label = scene.name
        if label:
            marks.append((round(content_start + st.t_start, 2), label))
    return marks


def _card_voice(card, wav_path: Path, spec: DemoSpec, log: Progress | None = None) -> str | None:
    if not card or not card.narrate:
        return None
    synthesize(card.narrate, wav_path, spec.voice, log=log)
    if spec.audio.normalize:
        normalize_wav(str(wav_path))
    return str(wav_path)


def _align(spec: DemoSpec, narrations, log) -> dict[int, list]:
    try:
        from .align import align_words
    except Exception:  # noqa: BLE001
        return {}
    timings: dict[int, list] = {}
    log("Aligning words for karaoke captions (whisper)…")
    for i, (wav, dur) in enumerate(narrations):
        if not wav or dur <= 0:
            continue
        try:
            timings[i] = align_words(wav)
        except Exception as exc:  # noqa: BLE001
            log(f"  alignment skipped for scene {i}: {exc}")
    return timings


# --------------------------------------------------------------------------- dry run


@dataclass
class PlanRow:
    index: int
    action: str
    zoom: str
    narration: str
    est_seconds: float


def plan(
    spec_path: str | Path, overrides: dict[str, str] | None = None
) -> tuple[DemoSpec, list[PlanRow], float]:
    spec = load_spec(spec_path, overrides)
    rows: list[PlanRow] = []
    total = (spec.intro.seconds if spec.intro else 0.0) + (
        spec.outro.seconds if spec.outro else 0.0
    )
    for i, scene in enumerate(spec.scenes):
        act = scene.primary_action()
        action = _describe(scene) if act or _has_annotation(scene) else "—"
        z = scene.effective_zoom(spec.camera)
        words = len((scene.narrate or "").split())
        est = max(words / 2.6, 0.0) + (scene.hold if scene.hold is not None else 0.6)
        est = max(est, 1.0) + (scene.pause or 0.0)
        rows.append(
            PlanRow(
                i, action, f"{z:.2f}×" if z else "—", (scene.narrate or "").strip(), round(est, 1)
            )
        )
        total += est
    return spec, rows, round(total, 1)


def _has_annotation(scene) -> bool:
    return any(
        getattr(scene, f) is not None
        for f in ("highlight", "spotlight", "callout", "arrow", "chapter")
    )


def _describe(scene) -> str:
    parts = []
    act = scene.primary_action()
    if act:
        kind, val = act
        if kind == "type":
            parts.append(f"type {val.text!r}" if isinstance(val, TypeAction) else f"type {val!r}")
        elif kind == "scroll" and isinstance(val, ScrollAction):
            parts.append(f"scroll {'to ' + val.to if val.to else f'by {val.by}px'}")
        elif kind == "wait":
            parts.append(f"wait {val}s")
        else:
            parts.append(f"{kind} {val}")
    for f in ("highlight", "spotlight", "callout", "arrow", "chapter"):
        if getattr(scene, f) is not None:
            parts.append(f"+{f}")
    return " ".join(parts) or "—"
