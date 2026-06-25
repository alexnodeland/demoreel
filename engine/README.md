# demoreel

Turn a short YAML spec into a studio-quality demo video. `demoreel` drives a real browser with
Playwright, records the flow, and composes a finished `.mp4` that looks hand-made — the recording
floats on a gradient backdrop inside a macOS browser window, the camera zooms to each click, a
cursor glides and keys cast, narration is spoken and captioned, and the whole thing opens and
closes on themed title cards. The aim is tools that feel *made, not generated* — calm, considered,
human. One spec is the single source of truth; everything downstream is deterministic.

- **Repo:** <https://github.com/our-nature/demoreel> · **Landing:** <https://our-nature.github.io/demoreel/>
- **License:** MIT (Alex Nodeland), by the Our Nature studio
- **Stack:** Python 3.10–3.13, managed with [uv]; Playwright capture, moviepy/opencv/Pillow/numpy composition

[uv]: https://docs.astral.sh/uv/

---

## Install

```bash
cd engine
uv sync --extra piper            # default local OSS voice engine
uv run playwright install chromium
uv run demoreel doctor           # confirm the environment is ready
```

`ffmpeg` ships via `imageio-ffmpeg` — no system install required.

**Extras** (compose with `uv sync --extra <name>`, or `--all-extras`):

| Extra | Adds |
|-------|------|
| `piper` | Local OSS neural TTS (recommended default voice) |
| `kokoro` | Higher-quality local OSS neural TTS (Apache-2.0, offline) |
| `cloud` | OpenAI / OpenAI-compatible cloud TTS |
| `align` | Word-level alignment for **karaoke** captions (faster-whisper) |
| `all` | Everything above |

`say` (macOS), `espeak` (espeak-ng), and `elevenlabs` (set `ELEVENLABS_API_KEY`) need no extra.

---

## Quickstart

```bash
uv run demoreel init my-demo.yaml          # scaffold a spec from a template
$EDITOR my-demo.yaml                        # point url + selectors at your app
uv run demoreel validate my-demo.yaml      # parse + print the scene plan (no browser/TTS)
uv run demoreel check    my-demo.yaml      # open the page, verify every selector resolves
uv run demoreel render   my-demo.yaml      # full render → demo.mp4
```

Iterate fast with `--preview` (a low-res pass), then drop it for the final render — or run
`demoreel watch my-demo.yaml` to re-render a preview automatically as you edit. Prefer
`text=` / `role=` selectors — they survive redesigns, and `check` tells you up front which ones
don't resolve.

---

## The CLI

Global flags: `--version`, `--debug` (full traceback on failure; or set `DEMOREEL_DEBUG=1`).

| Command | What it does |
|---------|--------------|
| `render <spec>` | Render the demo video (and any extra outputs) |
| `watch <spec>` | Re-render a fast preview whenever the spec or a local asset changes |
| `validate <spec>` | Parse the spec and print the scene plan — fast, no browser or TTS |
| `check <spec>` | Open the page and verify every selector resolves |
| `init [path]` | Scaffold a spec from a template + flags/prompts (default `demo.yaml`) |
| `theme <logo>` | Derive a brand palette from a logo image and print spec snippets |
| `voices` | List available TTS voices on this machine |
| `doctor` | Check the environment (deps, browser, voice engines, cache) |

### `render` flags

| Flag | Effect |
|------|--------|
| `-o, --output PATH` | Output `.mp4` path (overrides `output` in the spec) |
| `--headed` | Show the browser window during capture |
| `--engine NAME` | Override the voice engine (`piper`/`kokoro`/`say`/`espeak`/`openai`/`elevenlabs`) |
| `--preview` | Fast low-res pass for iteration |
| `--storyboard` | Also write a contact-sheet PNG of evenly-spaced frames |
| `--gif` | Also export an animated GIF |
| `--webp` | Also export an animated WebP |
| `--player` | Also write a self-contained HTML chapter player |
| `--gif-width PX` | GIF/WebP width (default `720`) |
| `--gif-fps N` | GIF/WebP frame rate (default `15`) |
| `--keep` | Keep the `.demoreel` build directory |
| `--set KEY=VALUE` | Substitute `${KEY}` in the spec — repeatable; see [Templating](#templating) |

Alongside the `.mp4`, a render emits `.srt`, `.vtt`, and a `.transcript.md`, plus any of
`.gif` / `.webp` / `.player.html` / `.storyboard.png` you asked for.

`validate` and `check` also accept `--set`; `check` also accepts `--headed`.

---

## Authoring a spec

A spec is a small, diffable document: global settings plus an ordered list of scenes. Each scene
is one beat — narration, at most one primary browser action, optional annotations, and a few
presentation hints. Defaults come from a named `preset`; any field you set wins over it.

```yaml
title: "My Product"
url: "https://example.com"          # base URL; scene `goto` may be relative or absolute
preset: studio                       # studio (default) · dark · light · minimal

voice:    { engine: piper }          # piper (local) · say · openai · elevenlabs · kokoro · espeak
captions: { style: pill }            # pill · lower_third · karaoke (karaoke needs --extra align)

intro:
  title: "My Product"
  subtitle: "A 30-second tour"
  narrate: "Here's a quick look at what you can do."

scenes:
  - narrate: "This is the home page."
    goto: "/"
    hold: 1.2

  - narrate: "Here's the thing I want to show you."
    highlight: "text=Get started"    # outline a selector; the camera frames it
    hold: 1.4

  - narrate: "One click, and we're in."
    click: "text=Get started"        # the camera zooms to the click automatically

outro:
  title: "Thanks for watching"
  cta: "example.com"
  narrate: "That's the tour — give it a try."
```

A scene carries **one** primary action (`goto` / `click` / `hover` / `type` / `press` / `scroll`
/ `wait`), optional annotations (`highlight`, `spotlight`, `callout`, `arrow`, `chapter`), and
hints (`focus`, `zoom` / `no_zoom`, `hold`, `pause`, `wait_for`, `persist`, `follow_new_tab`).
The full field-by-field reference lives in [docs/spec-reference.md](docs/spec-reference.md).

### Transitions

`transition: { type, duration }` controls how a segment is stitched onto the previous one,
applied at the intro → content → outro boundaries. `duration` (default `0.5`) is the overlap
length in seconds. Six types:

| Type | Effect |
|------|--------|
| `cut` | Hard cut — clips play back-to-back, no overlap. |
| `crossfade` | **Default.** Incoming fades in over the outgoing as they overlap. |
| `dip` | Dip to black — outgoing fades out, incoming fades in (no overlap). |
| `wipe` | A hard-edged mask sweeps left→right to reveal the incoming clip. |
| `push` | Outgoing slides out to the left while the incoming slides in from the right (both visible mid-transition). |
| `zoom_blur` | A whip-zoom crossfade — the incoming scales `1.08 → 1.0` as it fades in. |

`crossfade`, `wipe`, `push`, and `zoom_blur` overlap adjacent segments by `duration` (the
timeline shortens accordingly); `cut` and `dip` do not.

```yaml
transition: { type: push, duration: 0.4 }
```

Runnable examples in [`examples/`](examples):

| File | Shows |
|------|-------|
| [`starter.yaml`](examples/starter.yaml) | The minimal spec shape (close to `init --template minimal`) |
| [`playwright-tour.yaml`](examples/playwright-tour.yaml) | A full landscape walkthrough with chapters + callouts |
| [`social-vertical.yaml`](examples/social-vertical.yaml) | A 9:16 vertical cut inside a phone frame |
| [`parameterized.yaml`](examples/parameterized.yaml) | `${VAR}` templating + live-data redaction |
| [`brand/acme.brand.yaml`](examples/brand/acme.brand.yaml) | A brand kit, with [`brand/with-kit.yaml`](examples/brand/with-kit.yaml) referencing it |
| [`showcase/acme-hero.yaml`](examples/showcase/acme-hero.yaml) | The site hero (self-contained against `showcase/acme.html`) |

---

## Presets & resolutions

**Presets** seed the look (theme, framing, camera, captions): `studio` (default), `dark`,
`light`, `minimal`.

**Resolution** is set under `quality.resolution`, as a named preset or a custom `[w, h]`
(rounded down to even pixels — libx264 needs even dimensions):

| Group | Presets |
|-------|---------|
| Landscape (16:9) | `480p`, `720p`, `1080p`, `1440p`, `4k`, `16:9` |
| Vertical (9:16) | `vertical`, `9:16` → 1080×1920 — reels / shorts / TikTok |
| Portrait (4:5) | `portrait`, `4:5` → 1080×1350 — Instagram portrait |
| Square (1:1) | `square`, `1:1` → 1080×1080 — feed |

For a mobile cut, set `frame.device` to `phone` or `tablet` to draw a device bezel instead of the
macOS browser window. Pair it with a narrow `viewport` and a vertical/square resolution:

```yaml
viewport: [414, 896]          # mobile CSS viewport drives the page at phone width
quality: { resolution: vertical }
frame:   { device: phone }    # phone · tablet · none
```

---

## Voice engines

Set `voice.engine` (or override per-render with `--engine`). Synthesis is **content-addressed
cached** on disk (keyed by engine + voice + rate + text), so re-rendering unchanged narration is
instant and, for cloud engines, free. A configurable **fallback chain** (`voice.fallback`) tries
the next engine when the preferred one is unavailable, degrading to silence rather than aborting
the render.

| Engine | Notes | Needs |
|--------|-------|-------|
| `piper` | **Default.** Local OSS neural TTS; auto-downloads voices from HuggingFace | `--extra piper`; default voice `en_US-lessac-medium` |
| `kokoro` | Higher-quality local OSS neural TTS (Apache-2.0, offline) | `--extra kokoro` |
| `say` | macOS built-in `say` — zero install, fast to iterate | macOS |
| `espeak` | espeak-ng — cross-platform robotic fallback | `espeak-ng` on PATH |
| `openai` | Cloud TTS, or any OpenAI-compatible endpoint via `voice.base_url` | `--extra cloud`, `OPENAI_API_KEY` |
| `elevenlabs` | Cloud TTS via REST | `ELEVENLABS_API_KEY` (no package) |

Discover what's ready and which voices exist:

```bash
uv run demoreel doctor    # which engines/keys are present, cache + default-voice status
uv run demoreel voices    # available engines and example voice names
```

---

## Captions

Captions are on by default; pick a style under `captions.style`:

- **`pill`** — a rounded caption pill (the default).
- **`lower_third`** — a broadcast-style lower-third band.
- **`karaoke`** — word-by-word highlight synced to the narration. Needs `--extra align`
  (faster-whisper) for word-level timing; `pill` and `lower_third` work without it.

---

## Extra outputs

Ask `render` for more than the `.mp4`:

```bash
uv run demoreel render my-demo.yaml --gif --webp        # looping social previews
uv run demoreel render my-demo.yaml --player            # self-contained HTML chapter player
uv run demoreel render my-demo.yaml --storyboard        # contact-sheet PNG of frames
```

`--gif` / `--webp` size with `--gif-width` and `--gif-fps`. The `--player` page reads scene
`name`s as a chapter rail. (`.srt`, `.vtt`, and `.transcript.md` are always written.)

---

## Scaffolding a spec

`demoreel init` writes a ready-to-render spec from a **template + answers**, not a verbatim
copy — every template produces a spec that `validate` accepts. Templates:

| Template | For |
|----------|-----|
| `minimal` | The smallest valid spec — a title card, two scenes, an outro. Start here. |
| `tour` | A multi-scene guided walkthrough (intro → chapters → callouts → outro), landscape 1080p. |
| `social` | A 9:16 vertical cut inside a phone frame — Reels / Shorts / TikTok. |
| `hero` | A studio-polished hero reel (named chapters, typed query, CTA outro) for a README/site. |

Each flag overrides the template default only when provided: `--template`, `--title`, `--url`,
`--preset`, `--resolution`, `--device`, `--voice-engine`, `--transition`, `-o/--output`,
`-y/--yes`. The output filename is derived from a slug of the title (`"My App"` → `my-app.yaml`)
unless you pass `--output`.

```bash
uv run demoreel init demo.yaml --template social --title "My App" --url https://myapp.com
```

When stdin is a TTY and you don't pass `--yes`, `init` runs **interactively** — prompting for
each answer with defaults and rejecting out-of-range choices; otherwise it builds
non-interactively from the template and flags.

## Watch mode

`demoreel watch <spec>` keeps a fast `--preview` in sync with your spec as you edit. It renders
once on start, then polls for changes and re-renders whenever the spec — or a **local** asset it
points at — is saved:

```bash
uv run demoreel watch demo.yaml --interval 1.0
```

`watch` accepts `--interval`, `--engine`, `-o/--output`, and `--set K=V`. It watches the spec
file plus the local files it references — `audio.music`, `brand.logo`, a `brand_kit`,
`prelude.inject_css` / `inject_js`, and a `file://` page URL. Remote `http(s)` URLs are not
watched. The watch list is re-evaluated each tick, so adding an asset reference is picked up
without a restart. A broken or mid-edit spec doesn't kill the watcher — it keeps watching until
the spec parses again. `Ctrl-C` stops gracefully.

## Templating

Render many demos from one spec. `${VAR}` and `${VAR:-default}` (POSIX-style) expand from
`--set` flags and the environment *before* parsing — a missing variable with no default fails
loudly rather than producing a broken demo:

```bash
uv run demoreel render parameterized.yaml \
    --set TENANT=Acme \
    --set APP_URL=https://app.acme.test
```

```yaml
title: "${TENANT:-Your product} — a tour"
url: "${APP_URL:-https://playwright.dev}"
output: "${TENANT:-demo}-tour.mp4"
```

---

## Redaction

When recording a real app, scrub live data before it reaches the frame. `prelude.redact` lists
selectors whose **text** is replaced while layout stays intact — reapplied after every navigation
and scene action (and via a MutationObserver, so late-rendered data is caught too):

```yaml
prelude:
  hide:   [".cookie-banner", "#intercom-container"]   # remove distracting chrome
  redact: [".user-name", ".account-id", "[data-pii]"] # scrub names / numbers / emails
  redact_mode: scramble                                # scramble (default) · block (•••) · label
```

---

## Brand from a logo

Derive a coherent palette from a logo image and paste the snippets into your spec:

```bash
uv run demoreel theme path/to/logo.png
```

It prints an accent color, a two-stop background gradient, and the dominant swatches, ready to
drop into `brand`, `cursor`, `captions`, and `frame.background`. The studio accent is indigo
`#6C5CE7`, with teal `#5EE0C8` used sparingly.

---

## Brand kits

A **brand kit** is a reusable look bundle a team applies across many demos. Reference one with a
top-level directive — the path resolves relative to the spec file:

```yaml
brand_kit: ./brand/acme.brand.yaml
```

Kit fields: `accent`, `background` (a `[from, to]` hex gradient), `logo`, `font`, `name`,
`title`, `watermark`, `watermark_position`, `watermark_opacity`. The kit fans out to the spec:
`accent` sets `brand.color`, `captions.accent`, and `cursor.color`; `background` sets
`frame.background.colors` (angle `135`). A sparse kit only fills the keys it sets.

Merge precedence, **highest wins: spec > brand kit > preset**. The kit fills gaps left by the
spec and overrides the preset, so a spec's own explicit fields still win over the kit.

```yaml
# acme.brand.yaml
accent: "#FF6B00"                  # → brand.color + captions.accent + cursor.color
background: ["#1A1206", "#0A0703"] # → frame.background.colors (angle 135)
logo: ./assets/acme-logo.png
font: Inter
name: Acme
title: Product Demo
watermark: true
watermark_position: bottom-right
watermark_opacity: 0.5
```

See [`examples/brand/acme.brand.yaml`](examples/brand/acme.brand.yaml) (the kit) and
[`examples/brand/with-kit.yaml`](examples/brand/with-kit.yaml) (a spec referencing it, overriding
two fields to show the spec wins).

---

## Troubleshooting

Common issues — selectors that don't resolve, headless flakiness, voice setup, render
performance — are covered in [docs/troubleshooting.md](docs/troubleshooting.md). When in doubt,
run `demoreel doctor` (environment) and `demoreel check <spec>` (selectors) first.

---

## Development

```bash
uv sync --all-extras --group dev      # or `uv sync` for the lean dev set
uv run pytest                          # fast suite (browser/slow markers excluded by default)
uv run pytest -m "browser or slow"     # the full integration suite (needs a real browser)
uv run ruff check . && uv run ruff format .
uv run pyright
```

A `justfile` mirrors the CI gate: `just ci`, `just check`, `just fix`, `just test`.

The default `pytest` run is dependency-light (pydantic / numpy / Pillow / pyyaml only) — it runs
`-m "not browser and not slow"`. moviepy-level compositing tests are marked `slow` and real
Chromium renders are marked `browser`.

**PR previews.** Every pull request auto-renders a fast, fully-offline example
(`examples/showcase/acme-hero.yaml` against `acme.html` via a `file://` URL) and uploads the
`mp4` / `gif` / HTML player as the `demo-preview` artifact (7-day retention). A single sticky PR
comment links the run, refreshed in place on each push. The render is non-blocking and degrades
gracefully on fork PRs.

---

## What's new

**0.3.0** (2026-06-24):

- **Scene transitions** — `cut` / `crossfade` / `dip` / `wipe` / `push` / `zoom_blur` between segments.
- **Brand kits** — a reusable `brand_kit:` look bundle (precedence: spec > kit > preset).
- **`init` scaffolder** — `minimal` / `tour` / `social` / `hero` templates with flags or interactive prompts.
- **Watch mode** — `demoreel watch` re-renders a preview on spec/local-asset change.
- **PR preview renders** — CI auto-renders an offline example and posts a sticky artifact comment.

## Recent fixes

- Opaque window panel so dark/glassy apps no longer bleed through the backdrop.
- Theme base color painted before app CSS loads — kills the white flash and the
  transparent-body → white render.
- Focus rect probed before self-removing clicks, so reveal-clicks still zoom.
- `init` now writes a real bundled starter spec.
- Pydantic v2 `model_validator` normalization for `Quality` (resolution presets + even-pixel rounding).
- 8-bit WAV read fix; subtitle cue clamping; crossfade caption-offset sync.
