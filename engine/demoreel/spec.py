"""Declarative demo spec — the YAML that Claude (or a human) authors to make a video.

A spec is a small, diffable document: global settings + an ordered list of scenes. Each
scene is one beat of the demo: narration + at most one primary browser action
(goto/click/type/...) + optional annotations (highlight/spotlight/callout/...) +
presentation hints (zoom, hold, pause, transition).

Defaults come from a named `preset` (see themes.py); explicit fields always win. The
default preset (`studio`) yields the Studio look: the recording floated on a gradient
backdrop inside a macOS browser window, with spring-eased zoom-to-click.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------- actions


class TypeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selector: str | None = None
    text: str
    delay: int = 45


class ScrollAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str | None = None
    by: int | None = None


# ----------------------------------------------------------------------- annotations


class Callout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    at: str | None = None  # selector to point at; None = centered banner
    placement: Literal["auto", "top", "bottom", "left", "right"] = "auto"


class Arrow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str  # selector the arrow points at
    text: str | None = None
    dir: Literal["up", "down", "left", "right"] = "up"


class Chapter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    subtitle: str | None = None
    seconds: float = 1.8


# --------------------------------------------------------------------------- scene


class Scene(BaseModel):
    """One beat: narration + at most one primary action + optional annotations/hints."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = None
    narrate: str | None = None
    narrate_after: bool = False

    # primary action (at most one)
    goto: str | None = None
    click: str | None = None
    hover: str | None = None
    type: TypeAction | str | None = None
    press: str | None = None
    scroll: ScrollAction | None = None
    wait: float | None = None

    # annotations / overlays (may combine with an action)
    highlight: str | None = None
    spotlight: str | None = None
    callout: Callout | str | None = None
    arrow: Arrow | None = None
    chapter: Chapter | str | None = None
    persist: bool = False  # keep annotations into the next scene (default: clear)

    # multi-tab: when this scene's action opens a new tab (target=_blank / window.open),
    # follow that tab's URL in the SAME recorded page so the flow stays in one continuous
    # video. (Playwright records one video per page, so this is how a "new tab" stays on screen.)
    follow_new_tab: bool = False

    # timing / presentation
    wait_for: str | None = None
    zoom: float | None = None
    no_zoom: bool = False
    focus: str | None = None  # explicit selector to frame the zoom on
    hold: float | None = None
    pause: float | None = None  # extra silent dwell before the action
    transition: str | None = None  # override transition INTO this scene (cut|crossfade|dip)

    _ACTION_FIELDS = ("goto", "click", "hover", "type", "press", "scroll", "wait")
    _FOCUS_FIELDS = (
        "focus",
        "callout",
        "arrow",
        "highlight",
        "spotlight",
        "click",
        "hover",
        "type",
    )

    @model_validator(mode="after")
    def _at_most_one_action(self) -> Scene:
        present = [f for f in self._ACTION_FIELDS if getattr(self, f) is not None]
        if len(present) > 1:
            raise ValueError(f"scene has multiple actions {present}; use one action per scene")
        return self

    def primary_action(self) -> tuple[str, object] | None:
        for f in self._ACTION_FIELDS:
            v = getattr(self, f)
            if v is not None:
                return f, v
        return None

    def focus_selector(self) -> str | None:
        """The selector the camera should frame for this scene's zoom, if any."""
        if self.focus:
            return self.focus
        if isinstance(self.callout, Callout) and self.callout.at:
            return self.callout.at
        if self.arrow:
            return self.arrow.to
        if self.highlight:
            return self.highlight
        if self.spotlight:
            return self.spotlight
        if self.click:
            return self.click
        if self.hover:
            return self.hover
        if isinstance(self.type, TypeAction) and self.type.selector:
            return self.type.selector
        return None

    def has_focus_point(self) -> bool:
        return self.focus_selector() is not None

    def effective_zoom(self, cam: CameraConfig) -> float | None:
        if self.no_zoom:
            return None
        if self.zoom is not None:
            return self.zoom
        if cam.auto_zoom and self.has_focus_point():
            return cam.zoom
        return None


# --------------------------------------------------------------------------- config blocks


class GradientBg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colors: list[str] = Field(min_length=2)
    angle: float = 135.0


class FrameConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: Literal["studio", "full_bleed"] = "studio"
    background: str | GradientBg | None = None  # hex | gradient | image path
    padding: float = 0.055  # fraction of min(OW, OH)
    radius: int = 14
    shadow: bool = True
    shadow_blur: int = 48
    shadow_opacity: float = 0.55
    chrome: Literal["browser", "none"] = "browser"
    chrome_url: str | None = None
    chrome_title: str | None = None
    # Mobile device shell: draw a phone/tablet bezel instead of the macOS browser window.
    # Best with a vertical/square resolution and a matching narrow viewport.
    device: Literal["none", "phone", "tablet"] = "none"


class CameraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_zoom: bool = True
    zoom: float = 1.6
    easing: Literal["smoothstep", "cubic", "spring"] = "spring"
    overshoot: float = 0.0  # no overshoot by default — overshoot reads as an unwanted shift
    idle_drift: bool = False  # off by default — the continuous wander reads as drift
    drift_amount: float = 0.006
    framing: Literal["element", "point"] = "element"
    settle: float = 0.38


class CursorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show: bool = True
    style: Literal["pointer", "dot"] = "pointer"
    size: int = 22
    color: str = "#6C5CE7"
    glide: Literal["ease", "linear"] = "ease"
    keycast: bool = True


class CaptionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    style: Literal["pill", "lower_third", "karaoke"] = "pill"
    font: str | None = None
    size: int = 40
    position: Literal["bottom", "top"] = "bottom"
    color: str = "#F5F5FA"
    box: str = "#08080F"
    accent: str = "#6C5CE7"
    max_chars: int = 92


class SfxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    click: bool = True
    typing: bool = True
    volume: float = 0.22


class AudioConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    music: str | None = None
    music_volume: float = 0.12
    duck: bool = True
    normalize: bool = True
    sfx: SfxConfig = Field(default_factory=SfxConfig)


class BrandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logo: str | None = None
    color: str | None = None
    watermark: bool = True
    watermark_position: Literal["bottom-right", "bottom-left", "top-right", "top-left"] = (
        "bottom-right"
    )
    watermark_opacity: float = 0.5
    name: str | None = None  # lower-third name
    title: str | None = None  # lower-third title


class Prelude(BaseModel):
    """Determinism + stabilization applied before/while recording."""

    model_config = ConfigDict(extra="forbid")
    hide: list[str] = Field(default_factory=list)  # selectors to hide (cookie banners, etc.)
    mask: list[str] = Field(default_factory=list)  # selectors to cover (dynamic regions)
    # Live-data redaction: scrub the *text* of these selectors so real names/numbers/emails
    # don't leak into a recording of a real app, while keeping layout intact. Reapplied after
    # every navigation + scene action (and via a MutationObserver) so late-rendered data is caught.
    redact: list[str] = Field(default_factory=list)
    redact_mode: Literal["scramble", "block", "label"] = "scramble"
    freeze_anim: bool = False
    inject_css: str | None = None
    inject_js: str | None = None


# Module-level so both the validator (classmethod) and the .size property can read it.
# Defining this inside the model as ``_PRESETS`` turns it into a pydantic
# ModelPrivateAttr descriptor, which ``cls._PRESETS`` then can't iterate over.
_RESOLUTION_PRESETS = {
    # landscape (16:9)
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
    "16:9": (1920, 1080),
    # social / vertical / square — pair with a matching viewport (and often a phone `device`)
    "vertical": (1080, 1920),  # 9:16 — reels / shorts / tiktok
    "9:16": (1080, 1920),
    "portrait": (1080, 1350),  # 4:5 — instagram portrait
    "4:5": (1080, 1350),
    "square": (1080, 1080),  # 1:1 — feed
    "1:1": (1080, 1080),
}


class Quality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str | tuple[int, int] = "1080p"
    scale: int = 1  # multiplies the capture viewport for a higher-res recording

    @model_validator(mode="after")
    def _normalize(self) -> Quality:
        # mode="after" validators DO run on default values (unlike field_validators), so
        # this is the single normalization point: resolve the preset/tuple to a concrete
        # (w, h), reject non-positive sizes, and round down to even pixels because
        # libx264 + yuv420p require even width/height (odd dims fail deep inside ffmpeg).
        r = self.resolution
        if isinstance(r, str):
            key = r.lower()
            if key not in _RESOLUTION_PRESETS:
                raise ValueError(
                    f"unknown resolution {r!r}; use {list(_RESOLUTION_PRESETS)} or [w,h]"
                )
            w, h = _RESOLUTION_PRESETS[key]
        else:
            w, h = int(r[0]), int(r[1])
            if w <= 0 or h <= 0:
                raise ValueError(f"resolution must be positive, got {(w, h)}")
        self.resolution = (w - (w % 2), h - (h % 2))
        return self

    @property
    def size(self) -> tuple[int, int]:
        r = self.resolution
        if isinstance(r, str):  # pragma: no cover - normalized to a tuple in _normalize
            w, h = _RESOLUTION_PRESETS[r.lower()]
            return (w, h)
        return r


class TransitionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cut", "crossfade", "dip"] = "crossfade"
    duration: float = 0.5


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str = "piper"  # validated against the tts provider registry
    model: str | None = None  # voice id/name (piper onnx, openai/kokoro voice, 11labs id)
    rate: float = 1.0
    volume: float = 1.0
    fallback: list[str] = Field(default_factory=list)  # engines to try if `engine` fails
    base_url: str | None = None  # OpenAI-compatible endpoint (engine: openai)
    tts_model: str | None = None  # underlying model id override (openai/elevenlabs)

    @model_validator(mode="after")
    def _check_engine(self) -> VoiceConfig:
        from .tts import provider_names

        known = provider_names()
        for eng in (self.engine, *self.fallback):
            if eng not in known:
                raise ValueError(f"unknown voice engine {eng!r}; choose from {known}")
        return self


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    subtitle: str | None = None
    seconds: float = 2.5
    narrate: str | None = None
    cta: str | None = None  # outro call-to-action line


# --------------------------------------------------------------------------- top-level


class DemoSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: str = "Demo"
    url: str | None = None
    viewport: tuple[int, int] = (1600, 900)
    fps: int = 30
    output: str = "demo.mp4"
    headless: bool = True
    storage_state: str | None = None
    preset: str = "studio"

    quality: Quality = Field(default_factory=Quality)
    frame: FrameConfig = Field(default_factory=FrameConfig)
    camera: CameraConfig = Field(default_factory=CameraConfig)
    cursor: CursorConfig = Field(default_factory=CursorConfig)
    captions: CaptionConfig = Field(default_factory=CaptionConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    brand: BrandConfig = Field(default_factory=BrandConfig)
    prelude: Prelude = Field(default_factory=Prelude)
    transition: TransitionConfig = Field(default_factory=TransitionConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)

    intro: Card | None = None
    outro: Card | None = None
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_first_navigation(self) -> DemoSpec:
        first = self.scenes[0]
        if first.goto is None and self.url is None:
            raise ValueError("the first scene must `goto` a URL (or set a top-level `url`)")
        return self

    def output_size(self) -> tuple[int, int]:
        return self.quality.size

    def aspect_mismatch(self) -> float:
        """Relative gap between the capture viewport aspect and the output aspect.

        ~0 means they match (crisp, full-bleed). A larger value means the content window
        will be letterboxed inside the output frame — surfaced as a warning, not an error.
        """
        vw, vh = self.viewport
        ow, oh = self.output_size()
        if not (vh and oh):
            return 0.0
        return abs(vw / vh - ow / oh) / (ow / oh)


# ${VAR} or ${VAR:-default} — the colon-dash default mirrors POSIX shell parameter expansion.
_VAR_RE = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def substitute_vars(text: str, overrides: dict[str, str] | None = None) -> str:
    """Expand ${VAR} / ${VAR:-default} in raw spec text from overrides + the environment.

    Lets one spec render many demos (per-tenant URL, release tag, persona name) without
    editing YAML. A missing variable with no default is an error, not a silent empty string —
    a typo'd ${URL} should fail loudly rather than quietly produce a broken demo.
    """
    ns = {**os.environ, **(overrides or {})}

    def repl(m: re.Match[str]) -> str:
        name, default = m.group(1), m.group(2)
        if name in ns:
            return ns[name]
        if default is not None:
            return default
        raise ValueError(
            f"spec references ${{{name}}} but it is not set; pass --set {name}=… "
            f"or use ${{{name}:-default}}"
        )

    return _VAR_RE.sub(repl, text)


def _substitute_tree(obj: object, overrides: dict[str, str] | None) -> object:
    """Expand ${VAR}s in the string *values* of a parsed YAML tree (never in keys or comments —
    comments are already gone after parsing, which is exactly why we substitute post-parse)."""
    if isinstance(obj, str):
        return substitute_vars(obj, overrides)
    if isinstance(obj, list):
        return [_substitute_tree(v, overrides) for v in obj]
    if isinstance(obj, dict):
        return {k: _substitute_tree(v, overrides) for k, v in obj.items()}
    return obj


def load_spec(path: str | Path, overrides: dict[str, str] | None = None) -> DemoSpec:
    """Parse a YAML spec, expand ${VAR}s, merge the selected preset under it, and validate."""
    from .themes import apply_preset

    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    raw = _substitute_tree(raw, overrides)
    merged = apply_preset(raw)  # type: ignore[arg-type]
    return DemoSpec.model_validate(merged)
