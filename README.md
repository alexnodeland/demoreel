# demoreel

[![CI](https://github.com/our-nature/demoreel/actions/workflows/ci.yml/badge.svg)](https://github.com/our-nature/demoreel/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-6C5CE7.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10–3.13-5EE0C8.svg)

**Studio-quality demo videos, generated from a YAML spec.** A [Claude Code](https://claude.com/claude-code)
skill + a standalone Python engine that drives a real browser (Playwright) and renders a
finished `.mp4` that looks hand-made — the kind of polished product walkthrough you'd
normally make in Screen Studio, but scripted, diffable, and reproducible.

<p align="center">
  <img src="docs/media/acme-hero.gif" alt="A demoreel walkthrough: a web app floated on a gradient backdrop inside a browser window, the camera zooming to each action, with an animated cursor and captions." width="100%">
  <br>
  <em>↑ rendered from the spec below — <a href="engine/examples/showcase/acme-hero.yaml"><code>examples/showcase/acme-hero.yaml</code></a></em>
</p>

```yaml
scenes:
  - { narrate: "Start a new thread.", click: "#newthread", callout: { text: "one click to begin", at: "#newthread" } }
  - { narrate: "Ask in plain English.", type: { selector: "#q", text: "Revenue by region, last 90 days" } }
```

→ a 1080p video with the page floated on a gradient backdrop inside a macOS browser window,
the camera zooming to each click, an animated cursor, a voiceover, and synced captions.

**[View the landing page →](https://our-nature.github.io/demoreel/)**

## What you get

- 🎬 **Studio framing** — gradient backdrop, browser chrome, rounded window, drop shadow;
  the camera zooms *past* the window edge into the content. Or a **phone/tablet** device shell.
- 🎯 **Auto zoom-to-click** — element-aware, spring-eased; it follows what you do.
- 🖱️ **Animated cursor + keycast** — a glowing pointer that glides to each target.
- ✨ **Annotations** — `highlight`, `spotlight` (dim the rest), `callout`, `arrow`, `chapter`.
- 🔊 **Voiceover** — local open-source Piper (default), macOS `say`, Kokoro, espeak, OpenAI,
  or ElevenLabs; auto-fallback, cached, with ducked music and procedural SFX.
- 📝 **Captions** — `pill`, `lower_third`, or word-by-word **karaoke** (Whisper); plus
  `.srt` / `.vtt` / `.transcript.md` sidecars.
- 📐 **Any aspect** — `1080p` … `4k`, plus social **`vertical`** (9:16), **`square`** (1:1),
  **`portrait`** (4:5).
- 📦 **Extra outputs** — animated **`--gif`** / **`--webp`**, and a self-contained interactive
  HTML **`--player`** with a clickable chapter rail.
- 🔁 **Templating** — `${VAR}` / `${VAR:-default}` + `--set KEY=VALUE`, so one spec renders
  a demo per tenant, release, or persona.
- 🛡️ **Live-data redaction** — scrub real names/numbers/emails on camera, layout intact.
- 🎨 **Brand kit** — logo watermark, lower-third, outro CTA, and `demoreel theme <logo>` to
  derive a palette from your logo. **Themes:** `studio` · `dark` · `light` · `minimal`.

No system `ffmpeg` needed (bundled via `imageio-ffmpeg`).

## Install as a Claude Code skill

Mount this repo at `.claude/skills/demo` in your project — as a submodule:

```bash
git submodule add https://github.com/our-nature/demoreel .claude/skills/demo
cd .claude/skills/demo/engine
uv sync --extra piper && uv run playwright install chromium
```

Then ask Claude Code to `/demo <what to demo>`. The skill (`SKILL.md`) is a craft playbook:
it scouts the live app for real selectors, storyboards a narrative, renders a preview, and
reviews its own frames before the final cut. If your project ships a *demo house-style* doc,
the skill reads and applies it (preset/branding, voice, default URL, which flows matter).

## Use the engine directly (no skill)

```bash
cd engine
uv sync --extra piper && uv run playwright install chromium
uv run demoreel init my-demo.yaml      # starter spec
uv run demoreel validate my-demo.yaml  # parse + scene plan (fast, no browser)
uv run demoreel check    my-demo.yaml  # verify selectors against the live page
uv run demoreel render   my-demo.yaml -o out.mp4 --gif --player
uv run demoreel doctor                 # check the environment is ready
```

Reproduce the hero above:

```bash
cd engine
PAGE="file://$(pwd)/examples/showcase/acme.html"
uv run demoreel render examples/showcase/acme-hero.yaml --set PAGE="$PAGE" --gif --player
```

## Docs

- [`engine/README.md`](engine/README.md) — install, the full CLI, voices, captions, outputs.
- [`docs/spec-reference.md`](docs/spec-reference.md) — every spec field, default, and option.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — common issues + FAQ.
- [`SKILL.md`](SKILL.md) — the Claude Code authoring playbook.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`CHANGELOG.md`](CHANGELOG.md)

## Layout

```
SKILL.md            the Claude Code skill (authoring playbook)
engine/             the demoreel Python package
  demoreel/         spec · capture · stage · compose · audio · subtitles · brand · tts · …
  examples/         runnable specs (playwright-tour, social-vertical, parameterized, showcase/)
  tests/            unit (browser-free) + integration (browser/slow) suites
  README.md         engine + CLI reference
docs/               spec reference, troubleshooting, media
```

## License

MIT — see [LICENSE](LICENSE).
