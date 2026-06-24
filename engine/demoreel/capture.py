"""Browser capture with Playwright.

Drives the page through the scenes while recording at retina resolution. Emits a timeline
(scene windows), a page-space camera track (zoom keyframes that follow each scene's focus
element), click/type event times (for SFX), and the page URL (for the browser chrome bar).

The visible cursor, keycast, and annotations are drawn in-page by overlay_js (so they
track real element rects and are captured by the recording). Camera focus points are kept
in CSS/viewport pixels; compose.py maps them into the framed "stage" coordinate space.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .keyframes import CameraTrack
from .overlay_js import OVERLAY_JS
from .spec import CameraConfig, DemoSpec, Scene, TypeAction

DEFAULT_HOLD = 0.6
LEAD_IN = 0.5
TAIL = 0.5


@dataclass
class SceneTiming:
    index: int
    name: str | None
    t_start: float
    t_end: float
    audio_start: float
    narration_wav: str | None
    narration_duration: float


@dataclass
class CaptureResult:
    video_path: str
    page_w: int  # CSS viewport (camera coordinate space)
    page_h: int
    video_w: int  # recorded pixels (page * scale)
    video_h: int
    duration: float
    scenes: list[SceneTiming]
    camera: CameraTrack
    clicks: list[float] = field(default_factory=list)  # click times (for SFX)
    type_spans: list[tuple[float, float]] = field(default_factory=list)
    page_url: str = ""


class CaptureError(RuntimeError):
    pass


@dataclass
class _Cam:
    z: float
    cx: float
    cy: float


def capture(
    spec: DemoSpec,
    narrations: list[tuple[str | None, float]],
    build_dir: Path,
    log: Callable[[str], None] | None = None,
) -> CaptureResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CaptureError(
            "playwright is not installed. `pip install playwright && playwright install chromium`."
        ) from exc

    _log = log or (lambda *_a: None)

    # Playwright records the page at its CSS-viewport size and pads record_video_size if
    # it's larger (it does NOT supersample via device_scale_factor). So to record at a
    # higher resolution we enlarge the actual viewport; `scale` multiplies it.
    scale = max(1, spec.quality.scale)
    page_w, page_h = spec.viewport[0] * scale, spec.viewport[1] * scale
    vid_w, vid_h = page_w, page_h
    video_dir = build_dir / "video"
    video_dir.mkdir(parents=True, exist_ok=True)

    cam_cfg = spec.camera
    cam = CameraTrack(page_w, page_h)  # plain page-space track; compose remaps + eases
    cam.add(0.0, 1.0, page_w / 2, page_h / 2)
    cur = _Cam(1.0, page_w / 2, page_h / 2)
    clicks: list[float] = []
    type_spans: list[tuple[float, float]] = []
    timings: list[SceneTiming] = []
    page_url = ""

    # browser + context are closed in finally blocks so a mid-scene failure (bad selector,
    # goto timeout, OOM) never leaks a Chromium process or orphans the partial recording.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=spec.headless)
        try:
            ctx_kwargs: dict = {
                "viewport": {"width": page_w, "height": page_h},
                "device_scale_factor": 1,
                "record_video_dir": str(video_dir),
                "record_video_size": {"width": vid_w, "height": vid_h},
            }
            if spec.storage_state:
                ctx_kwargs["storage_state"] = spec.storage_state
            context = browser.new_context(**ctx_kwargs)
            try:
                for script in _init_scripts(spec):
                    context.add_init_script(script)
                page = context.new_page()
                video = page.video

                t0 = time.monotonic()

                def now() -> float:
                    return time.monotonic() - t0

                page.wait_for_timeout(int(LEAD_IN * 1000))

                for i, scene in enumerate(spec.scenes):
                    wav, ndur = narrations[i]
                    hold = scene.hold if scene.hold is not None else DEFAULT_HOLD

                    # clear the previous scene's overlays unless it asked to persist
                    if i > 0 and not spec.scenes[i - 1].persist:
                        _evaluate(
                            page, "() => window.__demoreel && window.__demoreel.clearAnnotations()"
                        )
                        _evaluate(
                            page, "() => window.__demoreel && window.__demoreel.clearChapter()"
                        )

                    t_start = now()
                    if scene.pause:
                        page.wait_for_timeout(int(scene.pause * 1000))

                    # Probe the focus target BEFORE acting: a click that swaps the view (reveals a
                    # panel, advances a step) removes its own target, so the post-action probe finds
                    # nothing and the zoom is skipped. We still prefer the post-action rect when the
                    # element survives (layout may have settled); this is just the fallback.
                    pre_focus_sel = scene.focus_selector()
                    act0 = scene.primary_action()
                    pre_rect = (
                        _focus_rect(page, pre_focus_sel, page_w, page_h)
                        if pre_focus_sel and act0 and act0[0] != "goto"
                        else None
                    )

                    if scene.follow_new_tab:
                        followed = _follow_popup(
                            page, scene, spec, page_w, page_h, clicks, type_spans, now, _log
                        )
                        if followed:
                            page_url = followed
                        act = scene.primary_action()
                        kind = act[0] if act else None
                    else:
                        kind = _perform(page, scene, spec, page_w, page_h, clicks, type_spans, now)
                        if kind == "goto":
                            page_url = page.url or page_url
                            _configure(page, spec)
                    _annotate(page, scene)
                    _warn_missing_selectors(page, scene, i, _log)
                    _await_settle(page, scene, i, _log)
                    t_action_done = now()

                    # camera keyframes toward this scene's focus element
                    focus_sel = scene.focus_selector()
                    rect = _focus_rect(page, focus_sel, page_w, page_h) or pre_rect
                    if focus_sel and rect is None:
                        _log(f"  ⚠ scene {i}: focus target not found, zoom skipped: {focus_sel}")
                    zoom = _resolve_zoom(scene, cam_cfg, rect, page_w, page_h)
                    if zoom and rect is not None:
                        cx, cy = rect["cx"], rect["cy"]
                        # Skip a near-identical move: if we're already framing roughly here at a
                        # similar zoom, don't add a tiny pan/zoom that just reads as drift.
                        near = (
                            abs(zoom - cur.z) < 0.12
                            and abs(cx - cur.cx) < 0.05 * page_w
                            and abs(cy - cur.cy) < 0.05 * page_h
                        )
                        if not near:
                            prev = cam.last()
                            prev_t = prev.t if prev else 0.0
                            cam.add(max(t_action_done - 0.15, prev_t), cur.z, cur.cx, cur.cy)
                            cam.add(t_action_done + cam_cfg.settle, zoom, cx, cy)
                            cur = _Cam(zoom, cx, cy)
                    elif cur.z != 1.0:
                        cam.add(t_start + 0.05, cur.z, cur.cx, cur.cy)
                        cam.add(t_start + 0.05 + cam_cfg.settle, 1.0, cur.cx, cur.cy)
                        cur = _Cam(1.0, cur.cx, cur.cy)

                    # pace the scene to fit its narration
                    if scene.narrate_after:
                        audio_start = t_action_done
                        min_end = audio_start + ndur
                    else:
                        audio_start = t_start
                        min_end = max(t_action_done, t_start + ndur)
                    target_end = min_end + hold
                    remaining = target_end - now()
                    if remaining > 0:
                        page.wait_for_timeout(int(remaining * 1000))
                    t_end = now()

                    timings.append(
                        SceneTiming(i, scene.name, t_start, t_end, audio_start, wav, ndur)
                    )

                tail_start = now()
                page.wait_for_timeout(int(TAIL * 1000))
                tail_end = now()
                if cur.z != 1.0:
                    cam.add(tail_start, cur.z, cur.cx, cur.cy)
                    cam.add(tail_end, 1.0, cur.cx, cur.cy)
            finally:
                context.close()  # finalizes the recording

            if video is None:  # pragma: no cover - record_video_dir is set, so video exists
                raise CaptureError("playwright did not produce a recording")
            saved = video.path()
            raw_path = build_dir / "raw.webm"
            shutil.move(str(saved), str(raw_path))
        finally:
            browser.close()

    return CaptureResult(
        video_path=str(raw_path),
        page_w=page_w,
        page_h=page_h,
        video_w=vid_w,
        video_h=vid_h,
        duration=tail_end,
        scenes=timings,
        camera=cam,
        clicks=clicks,
        type_spans=type_spans,
        page_url=page_url or (spec.url or ""),
    )


# ------------------------------------------------------------------- init / configure


def _base_bg(spec: DemoSpec) -> str:
    """The base page color painted before the app's own CSS loads — the window panel color,
    so blank/pre-paint moments and transparent-bodied apps never flash white on a dark stage."""
    from .stage import _is_light

    return "#fcfcfe" if _is_light(spec.frame.background) else "#101016"


def _init_scripts(spec: DemoSpec) -> list[str]:
    base = _base_bg(spec)
    scripts = [
        # Runs at document_start on every document (incl. the blank lead-in + each navigation).
        # Inline element.style outranks a non-!important app rule, so a transparent body shows
        # this instead of Chromium's white — killing the white flash the user saw on a dark app.
        "(() => { const el = document.documentElement;"
        " if (el) el.style.background = " + repr(base) + "; })()",
        OVERLAY_JS,
    ]
    css = _prelude_css(spec)
    if css:
        scripts.append(
            "(() => { const s = document.createElement('style');"
            f" s.textContent = {css!r};"
            " (document.head || document.documentElement).appendChild(s); })()"
        )
    if spec.prelude.inject_js:
        scripts.append(spec.prelude.inject_js)
    return scripts


def _prelude_css(spec: DemoSpec) -> str:
    parts: list[str] = []
    pre = spec.prelude
    if pre.freeze_anim:
        # kill looping animations (spinners) but leave transitions so the cursor eases
        parts.append("*,*::before,*::after{animation:none!important}")
    for sel in pre.hide:
        parts.append(f"{sel}{{display:none!important}}")
    for sel in pre.mask:
        parts.append(f"{sel}{{filter:blur(12px)!important}}")
    if pre.inject_css:
        parts.append(pre.inject_css)
    return "\n".join(parts)


def _configure(page, spec: DemoSpec) -> None:
    cur = spec.cursor
    cfg = {
        "accent": spec.captions.accent,
        "cursorStyle": cur.style,
        "cursorSize": cur.size,
        "cursorColor": cur.color,
        "cursorShow": cur.show,
        "keycast": cur.keycast,
    }
    _evaluate(page, "(c) => window.__demoreel && window.__demoreel.configure(c)", cfg)
    _apply_redaction(page, spec)


def _apply_redaction(page, spec: DemoSpec) -> None:
    """Re-arm in-page text redaction after a (re)load — the overlay's NS is fresh per document,
    so each hard navigation must re-register the selectors; its MutationObserver then handles
    any data that renders later within that same page."""
    pre = spec.prelude
    if pre.redact:
        _evaluate(
            page,
            "(a) => window.__demoreel && window.__demoreel.redact(a[0], a[1])",
            [pre.redact, pre.redact_mode],
        )


def _follow_popup(
    page, scene: Scene, spec: DemoSpec, w, h, clicks, type_spans, now, log: Callable[[str], None]
) -> str | None:
    """Run a scene's action expecting it to open a new tab, then continue that tab's URL in the
    SAME recorded page so the flow stays in one video. Returns the followed URL (or None)."""
    try:
        with page.expect_popup(timeout=8000) as popup_info:
            _perform(page, scene, spec, w, h, clicks, type_spans, now)
        popup = popup_info.value
        url = popup.url
        popup.close()
        if url and url != "about:blank":
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(350)
            _configure(page, spec)
            return page.url
    except Exception as exc:  # noqa: BLE001 - a missing popup shouldn't crash the render
        log(f"  ⚠ scene: follow_new_tab opened no new tab ({exc})")
    return None


# --------------------------------------------------------------------------- actions


def _perform(page, scene: Scene, spec: DemoSpec, w, h, clicks, type_spans, now) -> str | None:
    act = scene.primary_action()
    if act is None:
        return None
    kind, val = act

    if kind == "goto":
        page.goto(_resolve_url(spec.url, str(val)), wait_until="domcontentloaded")
        page.wait_for_timeout(350)
    elif kind == "click":
        clicks.append(now())
        _click(page, str(val), spec.cursor, w, h)
    elif kind == "hover":
        center = _center(page, str(val), w, h)
        if center:
            _glide(page, center, spec.cursor)
    elif kind == "type":
        ta = val if isinstance(val, TypeAction) else TypeAction(text=str(val))
        if ta.selector:
            clicks.append(now())
            _click(page, ta.selector, spec.cursor, w, h)
        t_start = now()
        page.keyboard.type(ta.text, delay=ta.delay)
        type_spans.append((t_start, now()))
    elif kind == "press":
        page.keyboard.press(str(val))
    elif kind == "scroll":
        if val.to:
            page.locator(val.to).first.scroll_into_view_if_needed()
        elif val.by is not None:
            page.mouse.wheel(0, val.by)
    elif kind == "wait":
        page.wait_for_timeout(int(float(val) * 1000))  # type: ignore[arg-type]  # val is the float wait
    return kind


def _annotate(page, scene: Scene) -> None:
    from .spec import Arrow, Callout, Chapter

    if scene.chapter is not None:
        if isinstance(scene.chapter, Chapter):
            _evaluate(
                page,
                "(a) => window.__demoreel.chapter(a[0], a[1])",
                [scene.chapter.title, scene.chapter.subtitle or ""],
            )
        else:
            _evaluate(page, "(t) => window.__demoreel.chapter(t, '')", str(scene.chapter))
    if scene.spotlight:
        _evaluate(page, "(s) => window.__demoreel.spotlight(s)", scene.spotlight)
    if scene.highlight:
        _evaluate(page, "(s) => window.__demoreel.highlight(s)", scene.highlight)
    if scene.callout is not None:
        if isinstance(scene.callout, Callout):
            _evaluate(
                page,
                "(a) => window.__demoreel.callout(a[0], a[1], a[2])",
                [scene.callout.at, scene.callout.text, scene.callout.placement],
            )
        else:
            _evaluate(page, "(t) => window.__demoreel.banner(t)", str(scene.callout))
    if scene.arrow is not None:
        a: Arrow = scene.arrow
        _evaluate(
            page, "(x) => window.__demoreel.arrow(x[0], x[1], x[2])", [a.to, a.dir, a.text or ""]
        )
    page.wait_for_timeout(120)  # let overlays paint + settle


def _await_settle(page, scene: Scene, i: int, log: Callable[[str], None]) -> None:
    if scene.wait_for:
        try:
            page.locator(scene.wait_for).first.wait_for(state="visible", timeout=20000)
        except Exception:  # noqa: BLE001
            log(f"  ⚠ scene {i}: wait_for never became visible: {scene.wait_for}")


def _warn_missing_selectors(page, scene: Scene, i: int, log: Callable[[str], None]) -> None:
    """Log a per-scene warning for annotation selectors that match nothing.

    Overlays are drawn in-page and fail silently, so without this a typo'd highlight/
    callout/arrow selector yields a 'successful' but wrong video with no feedback.
    """
    from .spec import Callout

    checks: list[tuple[str, str]] = []
    if scene.highlight:
        checks.append(("highlight", scene.highlight))
    if scene.spotlight:
        checks.append(("spotlight", scene.spotlight))
    if isinstance(scene.callout, Callout) and scene.callout.at:
        checks.append(("callout", scene.callout.at))
    if scene.arrow:
        checks.append(("arrow", scene.arrow.to))
    for label, sel in checks:
        try:
            if page.locator(sel).count() == 0:
                log(f"  ⚠ scene {i}: {label} selector matched nothing: {sel}")
        except Exception:  # noqa: BLE001, S110 - the warning probe is best-effort
            pass


def _click(page, selector: str, cursor, w, h) -> None:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=15000)
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if not box:
        loc.click()
        return
    cx = _clamp(box["x"] + box["width"] / 2, 1, w - 1)
    cy = _clamp(box["y"] + box["height"] / 2, 1, h - 1)
    _glide(page, (cx, cy), cursor)
    page.mouse.down()
    page.wait_for_timeout(80)
    page.mouse.up()


def _glide(page, target, cursor) -> None:
    if cursor.glide == "linear":
        page.mouse.move(target[0], target[1], steps=24)
    else:
        page.mouse.move(target[0], target[1], steps=6)
        page.wait_for_timeout(340)  # let the eased cursor land before the click


def _center(page, selector: str, w, h):
    rect = _focus_rect(page, selector, w, h)
    return (rect["cx"], rect["cy"]) if rect else None


def _focus_rect(page, selector: str | None, w, h) -> dict | None:
    if not selector:
        return None
    try:
        loc = page.locator(selector).first
        loc.wait_for(state="visible", timeout=8000)
        loc.scroll_into_view_if_needed(timeout=4000)  # below-fold targets → real in-view rect
        box = loc.bounding_box()
    except Exception:  # noqa: BLE001
        return None
    if not box:
        return None
    return {
        "cx": _clamp(box["x"] + box["width"] / 2, 1, w - 1),
        "cy": _clamp(box["y"] + box["height"] / 2, 1, h - 1),
        "w": box["width"],
        "h": box["height"],
    }


def _resolve_zoom(scene: Scene, cam: CameraConfig, rect: dict | None, w, h) -> float | None:
    base = scene.effective_zoom(cam)
    if base is None or rect is None:
        return base
    # element-aware framing: small targets zoom harder, large targets less.
    if scene.zoom is None and cam.framing == "element":
        z_w = 0.55 * w / max(rect["w"], 1.0)
        z_h = 0.62 * h / max(rect["h"], 1.0)
        return _clamp(min(z_w, z_h), 1.25, 2.6)
    # framing == "point" (or an explicit scene.zoom): use the configured zoom as-is,
    # centered on the focus point, ignoring the element's size.
    return base


# --------------------------------------------------------------------------- helpers


def _evaluate(page, script: str, arg=None) -> None:
    try:
        if arg is None:
            page.evaluate(script)
        else:
            page.evaluate(script, arg)
    except Exception:  # noqa: BLE001, S110 - overlays are best-effort
        pass


def _resolve_url(base: str | None, val: str) -> str:
    if val.startswith(("http://", "https://", "about:", "file:")):
        return val
    if base:
        return base.rstrip("/") + "/" + val.lstrip("/")
    return val


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
