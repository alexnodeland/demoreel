# demoreel — YAML Spec Reference

A complete field reference for the demoreel YAML spec. demoreel turns one declarative
YAML document into a studio-quality demo video: it drives a real browser with Playwright,
then composes the recording with moviepy/opencv/PIL/numpy into a framed, narrated MP4.

This document mirrors the pydantic models in
[`demoreel/spec.py`](../engine/demoreel/spec.py) and the presets in
[`demoreel/themes.py`](../engine/demoreel/themes.py) exactly — every field, type,
default, and allowed value is taken from the code.

A spec is a small, diffable document: **global settings + an ordered list of scenes**.
Each scene is one beat of the demo — narration + at most one primary browser action +
optional annotations + presentation hints. Defaults come from a named `preset`; explicit
fields always win.

> **Validation:** every model sets `extra="forbid"` — an unknown/misspelled key is a hard
> error, not a silent no-op. Run `demoreel validate spec.yaml` (or `check`) to catch
> these before rendering.

---

## Table of contents

- [DemoSpec (top level)](#demospec-top-level)
- [Scene](#scene)
  - [Actions: TypeAction, ScrollAction](#actions)
  - [Annotations: Callout, Arrow, Chapter](#annotations)
- [Quality](#quality) · [Resolution presets](#resolution-presets-table)
- [FrameConfig](#frameconfig) · [GradientBg](#gradientbg)
- [CameraConfig](#cameraconfig)
- [CursorConfig](#cursorconfig)
- [CaptionConfig](#captionconfig)
- [AudioConfig](#audioconfig) · [SfxConfig](#sfxconfig)
- [BrandConfig](#brandconfig) · [Brand kits](#brand-kits)
- [Prelude](#prelude)
- [TransitionConfig](#transitionconfig)
- [VoiceConfig](#voiceconfig)
- [Card (intro / outro)](#card-intro--outro)
- [Templating](#templating)
- [Presets](#presets)
- [CLI: scaffolding & watch](#cli-scaffolding--watch)

---

## DemoSpec (top level)

The root document. `scenes` is required and must contain at least one scene. Either the
first scene must `goto` a URL, or a top-level `url` must be set (validated after load).

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `title` | `str` | `"Demo"` | Demo title — used for default chrome/title cards and metadata. |
| `url` | `str \| null` | `null` | Optional starting URL; the first scene's `goto` overrides it. One of `url` or scene-0 `goto` is required. |
| `viewport` | `[int, int]` | `[1600, 900]` | Browser capture viewport (width, height) in CSS px. |
| `fps` | `int` | `30` | Output video frame rate. |
| `output` | `str` | `"demo.mp4"` | Output file path (overridable with the CLI `-o/--output` flag). |
| `headless` | `bool` | `true` | Run the browser headless (CLI `--headed` flips this off). |
| `storage_state` | `str \| null` | `null` | Path to a Playwright `storage_state` JSON (cookies/localStorage) for authenticated demos. |
| `preset` | `str` | `"studio"` | Named theme preset deep-merged *under* this spec: `studio`, `dark`, `light`, `minimal`. |
| `brand_kit` | `str \| null` | `null` | Path to a reusable [brand kit](#brand-kits) YAML (resolved relative to the spec file), merged between preset and spec. |
| `quality` | [`Quality`](#quality) | `Quality()` | Output resolution + capture scale. |
| `frame` | [`FrameConfig`](#frameconfig) | `FrameConfig()` | Studio framing: backdrop, padding, shadow, chrome, device shell. |
| `camera` | [`CameraConfig`](#cameraconfig) | `CameraConfig()` | Auto zoom-to-click behavior and easing. |
| `cursor` | [`CursorConfig`](#cursorconfig) | `CursorConfig()` | Animated cursor + keycast. |
| `captions` | [`CaptionConfig`](#captionconfig) | `CaptionConfig()` | On-screen narration captions. |
| `audio` | [`AudioConfig`](#audioconfig) | `AudioConfig()` | Music, ducking, SFX. |
| `brand` | [`BrandConfig`](#brandconfig) | `BrandConfig()` | Logo watermark + lower-third. |
| `prelude` | [`Prelude`](#prelude) | `Prelude()` | Determinism: hide/mask/redact/freeze/inject before recording. |
| `transition` | [`TransitionConfig`](#transitionconfig) | `TransitionConfig()` | Default transition between scenes. |
| `voice` | [`VoiceConfig`](#voiceconfig) | `VoiceConfig()` | TTS engine + voice for narration. |
| `intro` | [`Card`](#card-intro--outro) `\| null` | `null` | Optional intro title card. |
| `outro` | [`Card`](#card-intro--outro) `\| null` | `null` | Optional outro title card (supports a `cta` line). |
| `scenes` | `list[`[`Scene`](#scene)`]` | — (required, min 1) | Ordered list of demo beats. |

> `viewport` configures the recorded browser; `quality.resolution` configures the final
> video frame. When the two aspect ratios differ, the content window is letterboxed inside
> the output — surfaced as a **warning**, not an error (`aspect_mismatch()`).

---

## Scene

One beat of the demo: narration + **at most one** primary action + optional
annotations/overlays + presentation hints. Accepts the alias-friendly `populate_by_name`
config. A validator enforces that no more than one *action* field is set per scene.

### Identity & narration

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `name` | `str \| null` | `null` | Optional scene label (for storyboard/debug readability). |
| `narrate` | `str \| null` | `null` | Voiceover + caption text for this beat. |
| `narrate_after` | `bool` | `false` | Speak the narration *after* the action runs instead of before. |

### Primary action (at most one)

Setting two or more of these raises a validation error (`use one action per scene`).

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `goto` | `str \| null` | `null` | Navigate to a URL. |
| `click` | `str \| null` | `null` | Click the element at this selector (also drives auto zoom-to-click). |
| `hover` | `str \| null` | `null` | Hover the element at this selector. |
| `type` | [`TypeAction`](#actions) `\| str \| null` | `null` | Type text. A bare string types into the focused element; a `TypeAction` targets a selector. |
| `press` | `str \| null` | `null` | Press a key / chord (e.g. `Enter`, `Control+A`). |
| `scroll` | [`ScrollAction`](#actions) `\| null` | `null` | Scroll to a selector or by a pixel delta. |
| `wait` | `float \| null` | `null` | Dwell N seconds with no action (pure pause beat). |

### Annotations / overlays (may combine with an action)

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `highlight` | `str \| null` | `null` | Draw a highlight box around this selector. |
| `spotlight` | `str \| null` | `null` | Dim everything except this selector (spotlight mask). |
| `callout` | [`Callout`](#annotations) `\| str \| null` | `null` | Labeled callout; a bare string is a centered banner. |
| `arrow` | [`Arrow`](#annotations) `\| null` | `null` | Arrow pointing at a selector. |
| `chapter` | [`Chapter`](#annotations) `\| str \| null` | `null` | Chapter title card; a bare string is the title with defaults. |
| `persist` | `bool` | `false` | Keep this scene's annotations into the next scene (default: cleared each scene). |

### Multi-tab

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `follow_new_tab` | `bool` | `false` | If the action opens a new tab (`target=_blank` / `window.open`), follow that URL in the *same* recorded page so the flow stays one continuous video. |

### Timing / presentation

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `wait_for` | `str \| null` | `null` | Wait for this selector to appear before proceeding. |
| `zoom` | `float \| null` | `null` | Explicit zoom factor for this scene (overrides camera auto-zoom). |
| `no_zoom` | `bool` | `false` | Force no zoom for this scene, even if a focus point exists. |
| `focus` | `str \| null` | `null` | Explicit selector to frame the zoom on (overrides the inferred focus point). |
| `hold` | `float \| null` | `null` | Hold the final frame N extra seconds after the action. |
| `pause` | `float \| null` | `null` | Extra silent dwell *before* the action runs. |
| `transition` | `str \| null` | `null` | Override the transition *into* this scene. One of `cut` \| `crossfade` \| `dip` \| `wipe` \| `push` \| `zoom_blur` (see [TransitionConfig](#transitionconfig)). |

**Zoom resolution order** (`effective_zoom`): `no_zoom` → no zoom; else explicit `zoom`;
else if `camera.auto_zoom` and a focus point exists → `camera.zoom`; else no zoom.

**Focus-point inference** (`focus_selector`, first non-empty wins): `focus` → `callout.at`
→ `arrow.to` → `highlight` → `spotlight` → `click` → `hover` → `type.selector`.

---

## Actions

### TypeAction

Keys: `selector`, `text`, `delay`. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `selector` | `str \| null` | `null` | Element to type into; `null` types into the focused element. |
| `text` | `str` | — (required) | The text to type. |
| `delay` | `int` | `45` | Per-keystroke delay in ms (drives the typing cadence + typing SFX). |

> Shorthand: `type: "hello"` is equivalent to `type: { text: "hello" }`.

### ScrollAction

Keys: `to`, `by`. `extra="forbid"`. Set one of `to` or `by`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `to` | `str \| null` | `null` | Selector to scroll into view. |
| `by` | `int \| null` | `null` | Pixel delta to scroll by (positive = down). |

---

## Annotations

### Callout

Keys: `text`, `at`, `placement`. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `text` | `str` | — (required) | Callout label text. |
| `at` | `str \| null` | `null` | Selector to point at; `null` renders a centered banner. |
| `placement` | `"auto" \| "top" \| "bottom" \| "left" \| "right"` | `"auto"` | Where to place the callout relative to its target. |

> Shorthand: `callout: "Note this"` is a centered banner.

### Arrow

Keys: `to`, `text`, `dir`. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `to` | `str` | — (required) | Selector the arrow points at. |
| `text` | `str \| null` | `null` | Optional label beside the arrow. |
| `dir` | `"up" \| "down" \| "left" \| "right"` | `"up"` | Direction the arrow points. |

### Chapter

Keys: `title`, `subtitle`, `seconds`. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `title` | `str` | — (required) | Chapter title. |
| `subtitle` | `str \| null` | `null` | Optional subtitle line. |
| `seconds` | `float` | `1.8` | How long the chapter card is held on screen. |

> Shorthand: `chapter: "Section Two"` uses the title with default subtitle/seconds.

---

## Quality

Keys: `resolution`, `scale`. `extra="forbid"`. An `after`-mode validator normalizes
`resolution` to a concrete even `(w, h)` tuple at load time.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `resolution` | `str \| [int, int]` | `"1080p"` | A named preset (see table) or a custom `[w, h]`. |
| `scale` | `int` | `1` | Multiplies the capture viewport for higher-res recording (then downscaled). |

**Normalization rules:** a string must be a known preset (case-insensitive) or it errors;
a tuple must be positive; both width and height are rounded **down to even** pixels
(libx264 + yuv420p require even dimensions).

### Resolution presets table

| Preset | Size (w×h) | Aspect / use |
|--------|-----------|--------------|
| `480p` | 854 × 480 | 16:9 landscape |
| `720p` | 1280 × 720 | 16:9 landscape |
| `1080p` | 1920 × 1080 | 16:9 landscape (**default**) |
| `1440p` | 2560 × 1440 | 16:9 landscape |
| `4k` | 3840 × 2160 | 16:9 landscape |
| `16:9` | 1920 × 1080 | 16:9 landscape (alias of 1080p) |
| `vertical` | 1080 × 1920 | 9:16 — reels / shorts / TikTok |
| `9:16` | 1080 × 1920 | 9:16 (alias of `vertical`) |
| `portrait` | 1080 × 1350 | 4:5 — Instagram portrait |
| `4:5` | 1080 × 1350 | 4:5 (alias of `portrait`) |
| `square` | 1080 × 1080 | 1:1 — feed |
| `1:1` | 1080 × 1080 | 1:1 (alias of `square`) |
| `[w, h]` | custom | any aspect; rounded down to even pixels |

> Pair social/vertical/square resolutions with a matching narrow `viewport` (and often a
> phone/tablet `frame.device`).

---

## FrameConfig

Studio framing — the recording floated on a backdrop inside a window or device shell.
`extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `style` | `"studio" \| "full_bleed"` | `"studio"` | `studio` = floated/padded window; `full_bleed` = edge-to-edge. |
| `background` | `str \|` [`GradientBg`](#gradientbg) `\| null` | `null` | Backdrop: hex color, gradient, or image path (preset usually supplies a gradient). |
| `padding` | `float` | `0.055` | Backdrop padding as a fraction of `min(out_w, out_h)`. |
| `radius` | `int` | `14` | Window corner radius (px). |
| `shadow` | `bool` | `true` | Draw a drop shadow under the window. |
| `shadow_blur` | `int` | `48` | Drop-shadow blur radius (px). |
| `shadow_opacity` | `float` | `0.55` | Drop-shadow opacity (0–1). |
| `chrome` | `"browser" \| "none"` | `"browser"` | Draw a macOS browser chrome (title bar + URL) or none. |
| `chrome_url` | `str \| null` | `null` | URL text shown in the browser chrome. |
| `chrome_title` | `str \| null` | `null` | Title text shown in the browser chrome. |
| `device` | `"none" \| "phone" \| "tablet"` | `"none"` | Draw a phone/tablet bezel instead of the macOS window. Best with a vertical/square resolution + narrow viewport. |

### GradientBg

Keys: `colors`, `angle`. `extra="forbid"`. Used as a `background` value.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `colors` | `list[str]` | — (required, **min 2**) | Gradient stop colors (hex), in order. |
| `angle` | `float` | `135.0` | Gradient angle in degrees. |

---

## CameraConfig

Auto zoom-to-click and easing. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `auto_zoom` | `bool` | `true` | Automatically zoom toward the focus point of each scene. |
| `zoom` | `float` | `1.6` | Zoom factor used by auto-zoom. |
| `easing` | `"smoothstep" \| "cubic" \| "spring"` | `"spring"` | Camera move easing curve. |
| `overshoot` | `float` | `0.0` | Overshoot fraction on the move (default 0 — overshoot reads as an unwanted shift). |
| `idle_drift` | `bool` | `false` | Continuous slow wander while idle (off by default — reads as drift). |
| `drift_amount` | `float` | `0.006` | Magnitude of idle drift when enabled. |
| `framing` | `"element" \| "point"` | `"element"` | Frame the whole element vs. a single point. |
| `settle` | `float` | `0.38` | Seconds to settle/hold after a camera move. |

---

## CursorConfig

Animated cursor + keycast. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `show` | `bool` | `true` | Render the synthetic cursor. |
| `style` | `"pointer" \| "dot"` | `"pointer"` | Cursor glyph. |
| `size` | `int` | `22` | Cursor size (px). |
| `color` | `str` | `"#6C5CE7"` | Cursor color (indigo accent; presets may override). |
| `glide` | `"ease" \| "linear"` | `"ease"` | Cursor movement easing. |
| `keycast` | `bool` | `true` | Show on-screen key/chord badges when keys are pressed. |

---

## CaptionConfig

On-screen narration captions. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `enabled` | `bool` | `true` | Render captions. |
| `style` | `"pill" \| "lower_third" \| "karaoke"` | `"pill"` | Caption style (`karaoke` highlights words in sync — needs the `align` extra). |
| `font` | `str \| null` | `null` | Font family/path; `null` uses the built-in default. |
| `size` | `int` | `40` | Caption font size (px). |
| `position` | `"bottom" \| "top"` | `"bottom"` | Caption placement. |
| `color` | `str` | `"#F5F5FA"` | Text color. |
| `box` | `str` | `"#08080F"` | Caption box/background color. |
| `accent` | `str` | `"#6C5CE7"` | Accent color (karaoke highlight; presets override). |
| `max_chars` | `int` | `92` | Max characters per caption line before wrapping/clamping. |

---

## AudioConfig

Music, ducking, normalization, SFX. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `music` | `str \| null` | `null` | Background music file path. |
| `music_volume` | `float` | `0.12` | Music volume (0–1). |
| `duck` | `bool` | `true` | Duck the music under narration. |
| `normalize` | `bool` | `true` | Loudness-normalize the final mix. |
| `sfx` | [`SfxConfig`](#sfxconfig) | `SfxConfig()` | Click/typing sound effects. |

### SfxConfig

Keys: `enabled`, `click`, `typing`, `volume`. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `enabled` | `bool` | `true` | Master switch for SFX. |
| `click` | `bool` | `true` | Play a click sound on click actions. |
| `typing` | `bool` | `true` | Play typing sounds during `type` actions. |
| `volume` | `float` | `0.22` | SFX volume (0–1). |

---

## BrandConfig

Logo watermark + lower-third. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `logo` | `str \| null` | `null` | Logo image path (watermark + intro/outro logo). |
| `color` | `str \| null` | `null` | Brand accent color (preset usually supplies one; or derive via the `theme` command). |
| `watermark` | `bool` | `true` | Show the logo watermark. |
| `watermark_position` | `"bottom-right" \| "bottom-left" \| "top-right" \| "top-left"` | `"bottom-right"` | Watermark corner. |
| `watermark_opacity` | `float` | `0.5` | Watermark opacity (0–1). |
| `name` | `str \| null` | `null` | Lower-third name line. |
| `title` | `str \| null` | `null` | Lower-third title line. |

---

## Brand kits

A **brand kit** is a reusable look bundle — an accent color, a gradient backdrop palette, a
logo + watermark settings, a caption font, and the lower-third name/title — that a team
applies across many demos. Load one from a top-level `brand_kit` directive; the path
resolves relative to the spec file.

```yaml
brand_kit: acme.brand.yaml
```

### Kit fields

A kit is a flat YAML document. Every field is optional — a sparse kit only fills the keys
it sets. `extra="forbid"`.

| Field | Type | Maps to spec leaf |
|-------|------|-------------------|
| `accent` | `str` (hex) | `brand.color`, `captions.accent`, **and** `cursor.color` |
| `background` | `[from, to]` (hex pair) | `frame.background.colors` (with `angle: 135`) |
| `logo` | `str` | `brand.logo` |
| `font` | `str` | `captions.font` |
| `name` | `str` | `brand.name` |
| `title` | `str` | `brand.title` |
| `watermark` | `bool` | `brand.watermark` |
| `watermark_position` | `str` | `brand.watermark_position` |
| `watermark_opacity` | `float` | `brand.watermark_opacity` |

A single `accent` fans out to all three accent leaves (cursor, captions, brand); a
`background` `[from, to]` pair becomes the frame's gradient backdrop at a 135° angle.

### Merge precedence

The kit is merged **between the preset and the spec** — it fills gaps under the spec and
overrides the preset. Highest wins:

```
spec  >  brand kit  >  preset
```

So a spec that sets `brand.title` or `captions.accent` overrides whatever the kit (or
preset) provides for those leaves, while the kit still beats the preset for every leaf the
spec leaves unset.

### Example `acme.brand.yaml`

```yaml
accent: "#FF6B00"                  # brand.color + captions.accent + cursor.color
background: ["#1A1206", "#0A0703"] # frame gradient backdrop [from, to] @135°
logo: ./assets/acme-logo.png       # corner watermark logo
font: Inter                        # caption font family
name: Acme                         # lower-third name
title: Product Demo                # lower-third title
watermark: true
watermark_position: bottom-right
watermark_opacity: 0.5
```

See `engine/examples/brand/acme.brand.yaml` (the kit) and
`engine/examples/brand/with-kit.yaml` (a spec referencing it, overriding two fields to show
the spec wins over the kit).

---

## Prelude

Determinism + stabilization applied before/while recording — so a real, live app records
identically every time. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `hide` | `list[str]` | `[]` | Selectors to hide (cookie banners, chat bubbles, etc.). |
| `mask` | `list[str]` | `[]` | Selectors to cover with a block (dynamic/sensitive regions). |
| `redact` | `list[str]` | `[]` | Selectors whose *text* is scrubbed so live names/numbers/emails don't leak; reapplied after every navigation, scene action, and via a MutationObserver. |
| `redact_mode` | `"scramble" \| "block" \| "label"` | `"scramble"` | How redacted text is replaced: shuffle characters, solid block, or a generic label. |
| `freeze_anim` | `bool` | `false` | Freeze CSS animations/transitions for stable frames. |
| `inject_css` | `str \| null` | `null` | Extra CSS injected before recording. |
| `inject_js` | `str \| null` | `null` | Extra JS injected before recording. |

---

## TransitionConfig

Default transition between scenes (overridable per-scene via `scene.transition`).
`extra="forbid"`. Applies at the intro→content→outro segment boundaries.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `type` | `"cut" \| "crossfade" \| "dip" \| "wipe" \| "push" \| "zoom_blur"` | `"crossfade"` | Transition style (see table below). |
| `duration` | `float` | `0.5` | Transition duration in seconds — the overlap length for overlapping types. |

### Transition types

| Type | Behavior | Overlaps? |
|------|----------|-----------|
| `cut` | Hard cut, no blend. Clips play back-to-back. | no |
| `dip` | Dip to color: the outgoing clip fades out and the incoming fades in. | no |
| `crossfade` | The incoming clip fades in over the outgoing (**default**). | yes |
| `wipe` | A hard-edged mask sweeps left→right, revealing the incoming clip. | yes |
| `push` | The outgoing clip slides out to the left while the incoming slides in from the right (both visible mid-transition). | yes |
| `zoom_blur` | A crossfade with a fast `1.08 → 1.0` scale ramp on the incoming clip (a quick "whip-zoom"). | yes |

Overlapping types (`crossfade`, `wipe`, `push`, `zoom_blur`) overlap adjacent segments by
`duration`, shortening the timeline accordingly; `cut` and `dip` do not overlap.

```yaml
transition: { type: push, duration: 0.4 }
```

---

## VoiceConfig

TTS engine + voice for narration. `extra="forbid"`. A validator checks `engine` and every
`fallback` entry against the TTS provider registry.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `engine` | `str` | `"piper"` | Voice engine — validated against the registry: `piper`, `kokoro`, `say`, `espeak`, `openai`, `elevenlabs`. |
| `model` | `str \| null` | `null` | Voice id/name (piper `.onnx`, openai/kokoro voice, ElevenLabs voice id). Piper default: `en_US-lessac-medium`. |
| `rate` | `float` | `1.0` | Speaking rate multiplier. |
| `volume` | `float` | `1.0` | Narration volume multiplier. |
| `fallback` | `list[str]` | `[]` | Ordered engines to try if `engine` fails; the synthesis chain ends in silence so a render never dies on a missing voice. |
| `base_url` | `str \| null` | `null` | OpenAI-compatible TTS endpoint (when `engine: openai`). |
| `tts_model` | `str \| null` | `null` | Underlying model id override (openai/elevenlabs). |

**Engine notes:**
- `piper` — default, local OSS, install with `--extra piper`; default voice `en_US-lessac-medium`.
- `kokoro` — local OSS neural TTS (higher quality, experimental); install with `--extra kokoro`; needs `KOKORO_MODEL_PATH` + `KOKORO_VOICES_PATH`.
- `say` — macOS built-in (no install).
- `espeak` — espeak-ng (cross-platform robotic fallback).
- `openai` — needs `OPENAI_API_KEY`, install with `--extra cloud`; supports `base_url` for OpenAI-compatible endpoints.
- `elevenlabs` — cloud REST, needs `ELEVENLABS_API_KEY` (no package, experimental).

> Synthesis is content-addressed and cached on disk, so re-renders only re-synthesize
> changed narration.

---

## Card (intro / outro)

A title card. Used for `intro` and `outro`. `extra="forbid"`.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `title` | `str` | — (required) | Card title. |
| `subtitle` | `str \| null` | `null` | Card subtitle. |
| `seconds` | `float` | `2.5` | How long the card is held. |
| `narrate` | `str \| null` | `null` | Optional narration spoken over the card. |
| `cta` | `str \| null` | `null` | Outro call-to-action line. |

---

## Templating

Spec text supports POSIX-style variable expansion **after** YAML parsing (in string
values only — never in keys or comments). Variables resolve from `--set KEY=VALUE`
overrides first, then the process environment.

| Syntax | Behavior |
|--------|----------|
| `${VAR}` | Substitute `VAR`; **error** if unset and no default (a typo fails loudly). |
| `${VAR:-default}` | Substitute `VAR`, or `default` if `VAR` is unset. |

Pass values on the CLI (repeatable):

```sh
demoreel render spec.yaml --set URL=https://staging.example.com --set TENANT=acme
```

```yaml
url: ${URL:-https://app.example.com}
title: ${TENANT:-Acme} — Product Tour
```

This lets one spec render many demos (per-tenant URL, release tag, persona name) without
editing YAML. `validate` and `check` also accept `--set`.

---

## Presets

`preset` selects a partial spec dict that is deep-merged **under** your YAML — your
explicit fields always win. The model defaults already encode the Studio look, so presets
stay small. Default: `studio`. An unknown preset name falls back to `studio`.

| Preset | Look | Key overrides |
|--------|------|---------------|
| `studio` | Indigo-tinted dark Studio backdrop with browser chrome (**default**). | gradient `#1B1B2E→#0B0B12` @135°; spring easing; indigo `#6C5CE7` cursor/caption/brand accent. |
| `dark` | Neutral untinted dark, teal accent. | gradient `#15151A→#070709` @135°; teal `#5EE0C8` cursor/caption/brand accent. |
| `light` | Light Studio look for product/leadership audiences. | gradient `#EEF1F6→#D9DEE8` @135°; softer shadow (`shadow_opacity: 0.28`); dark caption text on white box; indigo `#4338CA` accents. |
| `minimal` | Edge-to-edge, no chrome, no backdrop — fast and neutral. | `full_bleed` frame, `chrome: none`, solid `#0B0B12` background; cubic easing, no idle drift; watermark off. |

---

## CLI: scaffolding & watch

### `demoreel init` — scaffold a spec

`demoreel init` writes a ready-to-render spec from a **template + answers** (not a verbatim
copy of a starter file). Every template produces a spec that `demoreel validate` accepts.

| Template | For |
|----------|-----|
| `minimal` | The smallest valid spec — a title card, two scenes, an outro. Start here. |
| `tour` | A multi-scene guided walkthrough (intro → chapters → callouts → outro), landscape 1080p. |
| `social` | A 9:16 vertical cut inside a phone frame — Reels / Shorts / TikTok. |
| `hero` | A studio-polished hero reel (named chapter scenes, typed query, CTA outro) for a README/site. |

**Flags** (each overrides the template default only when provided):

| Flag | Effect |
|------|--------|
| `--template` | Template to scaffold from (`minimal`, `tour`, `social`, `hero`). |
| `--title` | Demo title; also seeds the default output filename. |
| `--url` | Starting URL. |
| `--preset` | Theme preset (`studio`, `dark`, `light`, `minimal`). |
| `--resolution` | Output resolution (a named preset or `WxH`). |
| `--device` | Device shell (`none`, `phone`, `tablet`). |
| `--voice-engine` | TTS engine for narration. |
| `--transition` | Default scene transition. |
| `-o`, `--output` | Output spec path (otherwise derived from a slug of the title). |
| `-y`, `--yes` | Skip prompts; build non-interactively from the template + flags. |

`init` runs **interactively** — prompting for each value with defaults and validating
choice-backed answers — when stdin is a TTY and `--yes` was not passed. Otherwise it builds
non-interactively from the template and flags. The output filename derives from a slug of
the title (`"My App"` → `my-app.yaml`) unless `--output` is given.

```bash
demoreel init demo.yaml --template social --title "My App" --url https://myapp.com
demoreel validate demo.yaml   # parse + scene plan (fast, no browser)
demoreel render   demo.yaml   # full render
```

### `demoreel watch` — re-render on change

`demoreel watch spec.yaml` keeps a fast `--preview` render in sync with the spec as you
edit. It renders once immediately, then re-renders whenever the spec **or a referenced
local asset** changes.

```bash
demoreel watch spec.yaml [--interval 1.0] [--engine ENGINE] [-o OUT] [--set K=V]
```

| Flag | Default | Effect |
|------|---------|--------|
| `--interval` | `1.0` | Poll interval in seconds. |
| `--engine` | — | Override the voice engine for the preview. |
| `-o`, `--output` | — | Preview output path. |
| `--set` | — | Template overrides (`KEY=VALUE`, repeatable), as for `render`. |

It watches the spec file plus the **local** files it points at: `audio.music`, `brand.logo`,
a `brand_kit`, `prelude.inject_css` / `prelude.inject_js` file paths, and a `file://` page
URL. Remote `http(s)` URLs are not watched. The watch list is re-evaluated each tick, so
adding an asset reference is picked up without a restart.

Watch mode is polling-based (no extra dependencies) — it compares file modification times
on the interval. A broken or mid-edit spec does **not** kill the watcher: the failed render
is logged and watching continues until the spec parses again. `Ctrl-C` stops gracefully
(exit `0`).

---

## Quick example

```yaml
title: Acme Hero Tour
url: ${URL:-https://app.acme.test}
preset: studio
quality:
  resolution: 1080p
voice:
  engine: piper
  fallback: [say, espeak]
intro:
  title: Acme
  subtitle: A 60-second tour
scenes:
  - name: open
    goto: ${URL:-https://app.acme.test}
    narrate: Welcome to Acme.
    wait_for: "#dashboard"
  - name: search
    click: "#search"
    type: { selector: "#search", text: "revenue Q3" }
    narrate: Search anything in natural language.
    callout: { text: "Natural-language search", at: "#search" }
  - name: result
    highlight: "#results .top"
    narrate: Results appear instantly.
outro:
  title: Thanks for watching
  cta: Try Acme free at acme.test
```
