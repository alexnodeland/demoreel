"""Pure scaffolder for `demoreel init` — turns answers into ready-to-render YAML text.

This module is deliberately I/O-free: it owns templates, the interactive question list,
answer-merge precedence, and the YAML string builder. The CLI (cli.py) gathers answers
(from flags and/or `input()` prompts), calls `build_spec(answers)`, and writes the file.

Every template, when run through `build_spec`, yields a spec that `demoreel validate`
accepts: a top-level `title`, `url`, `output`, and at least one scene. The YAML is
hand-formatted (not `yaml.dump`-ordered) so it reads like the curated example specs.
"""

from __future__ import annotations

import re
from typing import NamedTuple, cast

# --------------------------------------------------------------------------- questions


class Question(NamedTuple):
    """One interactive prompt. `key` must be an answer key build_spec understands.

    `choices`, when set, constrains the answer to a fixed set (the CLI validates against it).
    """

    key: str
    prompt: str
    default: str
    choices: tuple[str, ...] | None = None


# Ordered prompts the CLI walks for an interactive `demoreel init`. Keys are a subset of the
# answer keys build_spec reads; `choices` mirror the spec's accepted enum values.
QUESTIONS: list[Question] = [
    Question("template", "Template", "minimal", ("minimal", "tour", "social", "hero")),
    Question("title", "Demo title", "My Product"),
    Question("url", "App URL", "https://example.com"),
    Question("preset", "Theme preset", "studio", ("studio", "dark", "light", "minimal")),
    Question(
        "resolution",
        "Resolution",
        "1080p",
        ("1080p", "720p", "vertical", "square", "portrait"),
    ),
    Question("device", "Device frame", "none", ("none", "phone", "tablet")),
    Question("voice_engine", "Voice engine", "piper", ("piper", "say", "openai", "elevenlabs")),
    Question("transition", "Scene transition", "crossfade", ("cut", "crossfade", "dip")),
]


# --------------------------------------------------------------------------- templates

# Each value is a dict of default answers. build_spec reads: title, url, preset, resolution,
# voice_engine, device, transition, viewport, zoom, captions, scenes, intro, outro, output.
TEMPLATES: dict[str, dict] = {
    "minimal": {
        "title": "My Product",
        "url": "https://example.com",
        "preset": "studio",
        "resolution": "1080p",
        "device": "none",
        "voice_engine": "piper",
        "transition": "crossfade",
        "intro": {
            "title": "My Product",
            "subtitle": "A quick tour",
            "narrate": "Here's a quick look at what you can do.",
        },
        "scenes": [
            {"narrate": "This is the home page.", "goto": "/", "hold": 1.2},
            {
                "narrate": "Here's the thing I want to show you.",
                "highlight": "text=Get started",
                "hold": 1.4,
            },
        ],
        "outro": {
            "title": "Thanks for watching",
            "cta": "example.com",
            "narrate": "That's the tour — give it a try.",
        },
    },
    "tour": {
        "title": "Product — a quick tour",
        "url": "https://example.com",
        "preset": "studio",
        "resolution": "1080p",
        "device": "none",
        "voice_engine": "piper",
        "voice_model": "en_US-lessac-medium",
        "transition": "crossfade",
        "viewport": (1600, 900),
        "zoom": 1.6,
        "intro": {
            "title": "Product",
            "subtitle": "A guided walkthrough",
            "seconds": 2.6,
            "narrate": "Here's a quick tour of the product.",
        },
        "scenes": [
            {"narrate": "This is the home page.", "goto": "/", "hold": 1.2},
            {
                "narrate": "Everything starts from Get started.",
                "highlight": "text=Get started",
                "hold": 1.4,
            },
            {"narrate": "Let's open it up.", "click": "text=Get started"},
            {
                "chapter": {"title": "Core flow", "subtitle": "The main thing"},
                "narrate": "Now let's look at the core flow.",
                "spotlight": "text=Installation",
                "wait_for": "text=Installation",
                "hold": 2.0,
            },
            {
                "narrate": "Fast, reliable, and built to scale.",
                "scroll": {"by": 700},
                "callout": {"text": "Fast & reliable", "at": "h1"},
                "hold": 2.4,
            },
        ],
        "outro": {
            "title": "That's the tour",
            "subtitle": "example.com",
            "seconds": 2.6,
            "cta": "Learn more →",
            "narrate": "And that's the whirlwind tour. Thanks for watching.",
        },
    },
    "social": {
        "title": "Product — on the go",
        "url": "https://example.com",
        "preset": "studio",
        "resolution": "vertical",
        "device": "phone",
        "voice_engine": "piper",
        "voice_model": "en_US-lessac-medium",
        "transition": "crossfade",
        "viewport": (414, 896),
        "zoom": 1.5,
        "caption_size": 46,
        "intro": {
            "title": "Product",
            "subtitle": "In sixty seconds",
            "seconds": 1.8,
            "narrate": "Here's the product, in sixty seconds.",
        },
        "scenes": [
            {
                "chapter": "Home",
                "narrate": "This is the home page.",
                "goto": "/",
                "hold": 1.2,
            },
            {
                "chapter": "Get started",
                "narrate": "Everything starts from Get started.",
                "highlight": "text=Get started",
                "hold": 1.6,
            },
            {
                "narrate": "One tap and you're in.",
                "click": "text=Get started",
                "spotlight": "text=Installation",
                "wait_for": "text=Installation",
                "hold": 2.0,
            },
        ],
        "outro": {
            "title": "Try it",
            "subtitle": "example.com",
            "seconds": 2.0,
            "cta": "Get started →",
            "narrate": "Give it a try.",
        },
    },
    "hero": {
        "title": "Acme Analytics",
        "url": "https://app.example.com",
        "preset": "studio",
        "resolution": "1080p",
        "device": "none",
        "voice_engine": "piper",
        "voice_model": "en_US-lessac-medium",
        "transition": "crossfade",
        "viewport": (1600, 900),
        "zoom": 1.5,
        "chrome_url": "app.acme.com",
        "intro": {
            "title": "Acme Analytics",
            "subtitle": "ask your data anything",
            "seconds": 2.2,
            "narrate": "Meet Acme — analytics you talk to.",
        },
        "scenes": [
            {
                "name": "The prompt",
                "narrate": "It opens on a single prompt: ask anything about your data.",
                "goto": "/",
                "highlight": "h1",
                "hold": 1.8,
            },
            {
                "name": "New thread",
                "narrate": "Start a new thread.",
                "click": "#newthread",
                "callout": {"text": "one click to begin", "at": "#newthread"},
                "hold": 1.2,
            },
            {
                "name": "Ask in plain English",
                "narrate": "Then ask in plain English — revenue by region, last ninety days.",
                "type": {"selector": "#q", "text": "Revenue by region, last 90 days"},
                "hold": 1.4,
            },
            {
                "name": "Just answers",
                "narrate": "No SQL, no dashboards to wire up — just answers.",
                "highlight": ".hint",
                "hold": 2.0,
            },
        ],
        "outro": {
            "title": "Make it move",
            "subtitle": "demoreel",
            "seconds": 2.4,
            "cta": "github.com/our-nature/demoreel",
            "narrate": "This whole walkthrough? Rendered from a short YAML file, with demoreel.",
        },
    },
}


# --------------------------------------------------------------------------- helpers


def slugify(text: str) -> str:
    """lowercase, runs of non-alphanumerics → a single hyphen, trimmed of leading/trailing.

    "My Demo!"  → "my-demo"
    "  a/b  c "  → "a-b-c"
    """
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def template_answers(name: str) -> dict:
    """Return a deep copy of TEMPLATES[name]; raise ValueError listing valid names if unknown."""
    if name not in TEMPLATES:
        valid = ", ".join(sorted(TEMPLATES))
        raise ValueError(f"unknown template {name!r}; choose from: {valid}")
    return cast(dict, _deepcopy(TEMPLATES[name]))


def merge_answers(*layers: dict) -> dict:
    """Shallow-merge answer dicts left→right; later non-None/non-"" values win.

    None and "" are treated as "not provided" so CLI flags only override template defaults
    when the user actually passed something.
    """
    out: dict = {}
    for layer in layers:
        if not layer:
            continue
        for key, value in layer.items():
            if value is None or value == "":
                continue
            out[key] = value
    return out


def _deepcopy(obj):
    """Tiny structural deep-copy for the plain dict/list/scalar answer trees (no copy import)."""
    if isinstance(obj, dict):
        return {k: _deepcopy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deepcopy(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_deepcopy(v) for v in obj)
    return obj


# --------------------------------------------------------------------------- YAML emit


def _q(value: str) -> str:
    """Double-quote a scalar string for YAML, escaping embedded quotes/backslashes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _fmt_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _num(value)
    return _q(str(value))


def _num(value: object) -> str:
    """Render a number without a trailing .0 when it's integral."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _emit_card(name: str, card: dict, lines: list[str]) -> None:
    lines.append(f"{name}:")
    for key in ("title", "subtitle", "narrate", "cta"):
        if key in card:
            lines.append(f"  {key}: {_q(str(card[key]))}")
    if "seconds" in card:
        lines.append(f"  seconds: {_num(card['seconds'])}")


def _emit_inline_mapping(data: dict) -> str:
    parts = []
    for key, value in data.items():
        parts.append(f"{key}: {_fmt_scalar(value)}")
    return "{ " + ", ".join(parts) + " }"


def _emit_scene(scene: dict, lines: list[str]) -> None:
    # Ordered for readability: identity → chapter → narration → action → annotations → timing.
    order = [
        "name",
        "chapter",
        "narrate",
        "goto",
        "click",
        "hover",
        "press",
        "type",
        "scroll",
        "highlight",
        "spotlight",
        "callout",
        "arrow",
        "wait_for",
        "hold",
        "pause",
        "zoom",
    ]
    first = True
    keys = [k for k in order if k in scene]
    keys += [k for k in scene if k not in order]
    for key in keys:
        value = scene[key]
        prefix = "  - " if first else "    "
        first = False
        if key in ("type", "scroll", "callout", "arrow", "chapter") and isinstance(value, dict):
            lines.append(f"{prefix}{key}: {_emit_inline_mapping(value)}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f"{prefix}{key}: {_num(value)}")
        elif isinstance(value, bool):
            lines.append(f"{prefix}{key}: {'true' if value else 'false'}")
        else:
            lines.append(f"{prefix}{key}: {_q(str(value))}")


def build_spec(answers: dict) -> str:
    """Produce valid, commented demoreel YAML from an answers dict.

    Falls back to the `minimal` template's structure for missing keys; unknown keys are
    ignored. Always emits `title`, `url`, `output`, and at least one scene.
    """
    base = TEMPLATES["minimal"]

    title = str(answers.get("title") or base["title"])
    url = str(answers.get("url") or base["url"])
    output = str(answers.get("output") or f"{slugify(title) or 'demo'}.mp4")
    preset = str(answers.get("preset") or base["preset"])
    resolution = str(answers.get("resolution") or base.get("resolution") or "1080p")
    device = str(answers.get("device") or base.get("device") or "none")
    voice_engine = str(answers.get("voice_engine") or base["voice_engine"])
    voice_model = answers.get("voice_model")
    transition = str(answers.get("transition") or base.get("transition") or "crossfade")

    viewport = answers.get("viewport")
    zoom = answers.get("zoom")
    chrome_url = answers.get("chrome_url")
    caption_size = answers.get("caption_size")

    intro = answers.get("intro") if answers.get("intro") is not None else base.get("intro")
    outro = answers.get("outro") if answers.get("outro") is not None else base.get("outro")
    scenes = answers.get("scenes") or base["scenes"]

    lines: list[str] = []
    # Lead comment block — title + the render hint, mirroring the curated example specs.
    lines.append(f"# {title} — a demoreel spec.")
    lines.append("#")
    lines.append(f"#   demoreel validate {output.replace('.mp4', '.yaml')}   # parse + scene plan")
    lines.append(f"#   demoreel check    {output.replace('.mp4', '.yaml')}   # verify selectors")
    lines.append(f"#   demoreel render   {output}   # full render")
    lines.append("#")
    lines.append("# Point `url` + selectors at your own app, then iterate with --preview.")
    lines.append("")

    lines.append(f"title: {_q(title)}")
    lines.append(f"url: {_q(url)}")
    if viewport is not None:
        vw, vh = viewport
        lines.append(f"viewport: [{int(vw)}, {int(vh)}]")
    lines.append(f"output: {_q(output)}")
    lines.append(f"preset: {preset}   # studio · dark · light · minimal")
    lines.append("")

    # quality / frame blocks only when they diverge from the landscape defaults.
    if resolution and resolution != "1080p":
        lines.append("quality:")
        lines.append(f"  resolution: {resolution}")
    if device and device != "none":
        lines.append("frame:")
        lines.append(f"  device: {device}   # phone · tablet · none")
    elif chrome_url:
        lines.append(f"frame: {{ chrome_url: {_q(str(chrome_url))} }}")

    if zoom is not None:
        lines.append(f"camera: {{ zoom: {_num(zoom)} }}")

    if caption_size is not None:
        lines.append(f"captions: {{ style: pill, size: {int(caption_size)} }}")
    else:
        lines.append("captions: { style: pill }   # pill · lower_third · karaoke")

    voice_parts = [f"engine: {voice_engine}"]
    if voice_model:
        voice_parts.append(f"model: {voice_model}")
    lines.append(f"voice: {{ {', '.join(voice_parts)} }}")

    if transition and transition != "crossfade":
        lines.append(f"transition: {{ type: {transition} }}")
    lines.append("")

    if intro:
        _emit_card("intro", intro, lines)
        lines.append("")

    lines.append("scenes:")
    for scene in scenes:
        _emit_scene(scene, lines)
        lines.append("")

    if outro:
        _emit_card("outro", outro, lines)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
