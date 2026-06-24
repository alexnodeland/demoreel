# Contributing to demoreel

Thanks for working on **demoreel** — the engine that turns a declarative YAML
spec into a studio-quality demo video by driving a real browser (Playwright) and
composing the result with moviepy / opencv / PIL / numpy.

This guide covers the project layout, dev setup, the test suite, lint/format/types,
CI, the common extension points, and the commit / PR conventions.

The guiding principle, the same one the output aims for: **tools that feel made,
not generated** — calm, considered, human. Code in the same spirit. Prefer the
small, legible change over the clever one; leave the surface easy for the next
person to read.

- Repo: <https://github.com/our-nature/demoreel>
- Landing: <https://our-nature.github.io/demoreel/>
- License: MIT (Alex Nodeland), by the Our Nature studio.

---

## Project layout

The repo is a **git submodule** consumed by other repositories (it lives at
`.claude/skills/demo/` inside its host). That has one consequence worth keeping in
mind: changes here ship to consumers as a submodule bump, so keep `main` green and
keep the public surface (the YAML spec + the `demoreel` CLI) stable.

Two levels:

```
demo/                         # the skill — what host repos consume
├── SKILL.md                  # skill instructions for the agent
├── README.md                 # skill-facing overview
├── CONTRIBUTING.md           # you are here
├── site/                     # GitHub Pages landing source
├── .github/workflows/        # ci.yml, preview.yml, release.yml, pages.yml
└── engine/                   # the Python package — all the code lives here
    ├── pyproject.toml        # deps, extras, dev group, ruff/pytest/pyright config
    ├── uv.lock               # committed on purpose — pins a reproducible set
    ├── demoreel/             # the package
    │   ├── __init__.py       # __version__ — single source of truth
    │   ├── cli.py            # argparse entrypoint: render/validate/check/init/theme/voices/doctor
    │   ├── spec.py           # pydantic v2 spec models + templating + resolution presets
    │   ├── themes.py         # theme PRESETS (studio/dark/light/minimal)
    │   ├── tts.py            # voice engines (PROVIDERS registry) + fallback chain + cache
    │   ├── align.py          # word-level alignment for karaoke (faster-whisper)
    │   ├── capture.py        # Playwright drive + record; emits the camera/annotation track
    │   ├── overlay_js.py     # in-page cursor, keycast, and annotation drawing (JS)
    │   ├── keyframes.py      # click/annotation track → camera keyframes
    │   ├── stage.py          # studio framing: window chrome, backdrop, device frames
    │   ├── compose.py        # camera + captions + brand + audio + cards/transitions
    │   ├── subtitles.py      # .srt / .vtt / transcript emission, cue clamping
    │   ├── audio.py          # VO + SFX + ducked music mix
    │   ├── brand.py          # logo watermark, lower-third, intro/outro logo
    │   ├── swatch.py         # brand-from-logo palette extraction
    │   ├── check.py          # selector preflight (the `check` command)
    │   ├── export.py         # GIF / WebP export
    │   ├── player.py         # self-contained HTML chapter player
    │   └── render.py         # top-level render orchestration
    ├── examples/             # starter.yaml, playwright-tour.yaml, social-vertical.yaml,
    │   │                     #   parameterized.yaml, showcase/acme-hero.yaml (+ acme.html)
    └── tests/                # unit/ + integration/ + fixtures/ + conftest.py
```

**Everything you edit lives under `engine/`.** Run all dev commands from there
(CI sets `working-directory: engine`).

---

## Dev setup

You need [uv](https://docs.astral.sh/uv/). Python 3.10–3.13 are supported; 3.10 is
the type-check / lint target.

```bash
cd engine

# Install the package + dev tooling. Either of these works:
uv sync                              # default group (dev tooling, no TTS extras)
uv sync --all-extras --group dev     # everything: piper, kokoro, cloud, align + dev tools

# Browser is required for capture and the browser/slow tests:
uv run playwright install chromium

# Sanity-check the environment:
uv run demoreel doctor
```

`ffmpeg` ships via `imageio-ffmpeg` — no system install required.

### Optional extras

Install only the voice / alignment backends you need:

| Extra    | Pulls in           | Enables |
|----------|--------------------|---------|
| `piper`  | `piper-tts`        | Default local OSS neural voice (`en_US-lessac-medium`). |
| `kokoro` | `kokoro-onnx`      | Higher-quality local OSS neural voice (offline, no key). |
| `cloud`  | `openai`           | OpenAI TTS + any OpenAI-compatible endpoint (`voice.base_url`). |
| `align`  | `faster-whisper`   | Word-level alignment for **karaoke** captions. |
| `all`    | all four           | Everything at once. |

`say` (macOS) and `espeak` (espeak-ng) need no extra — they shell out to a binary.
`elevenlabs` needs only `ELEVENLABS_API_KEY` (stdlib `urllib`, no package).

A quick local loop once you're set up:

```bash
uv run demoreel validate examples/playwright-tour.yaml   # parse + plan, no browser/TTS
uv run demoreel check examples/playwright-tour.yaml      # open page, verify selectors
uv run demoreel render examples/starter.yaml --preview   # fast low-res pass
```

---

## The test suite

The default `uv run pytest` **excludes the `browser` and `slow` markers** (configured
in `pyproject.toml` via `addopts = "-m 'not browser and not slow'"`). It runs without a
real browser, ffmpeg, or any TTS backend — it's dependency-light (pydantic / numpy / PIL /
pyyaml only) — so it's the fast inner loop and the thing CI runs across the whole Python
matrix. The two heavier tiers are opt-in via their markers:

```bash
uv run pytest                          # default: fast & dependency-light (not browser, not slow)
uv run pytest -m slow                  # moviepy / ffmpeg compositing tests
uv run pytest -m browser               # real Chromium renders via Playwright
uv run pytest -m "browser or slow"     # the whole heavy integration suite
```

Markers (also in `pyproject.toml`, `--strict-markers` is on — unknown markers fail):

| Marker    | Means |
|-----------|-------|
| `browser` | Needs a real Chromium via Playwright — actual page captures. |
| `slow`    | moviepy / ffmpeg compositing — full or partial render through the compose path. |
| `piper`   | Needs the `piper` extra and a downloaded voice model. |

Layout:

- `tests/unit/` — the bulk. Pure-logic tests for the spec, themes, templating,
  capture math, keyframes, compose logic, subtitles, audio, export, swatch, the
  device staging, the player, chapter rendering, TTS routing, and `check`. These
  must not touch the network, a browser, or ffmpeg.
- `tests/integration/` — the heavier tiers. `test_smoke_render.py` is an end-to-end
  render against a local `file://` fixture (marked `browser`/`slow`).
  `test_transitions_compositing.py` (marked `slow`) drives `concat_segments` with
  solid-color clips and asserts each transition's **mid-overlap frame** — this is what
  catches a transition silently degrading to a cut. When you add or change a transition,
  add or update its assertion here (see the transitions seam below).
- `tests/fixtures/` — local HTML + assets the tests drive (no network, no keys).
- `tests/conftest.py` — shared fixtures.

### Design: lazy-import heavy deps so the pure surface stays testable

This is the load-bearing convention for the test suite. **Heavy / optional
dependencies (piper, kokoro, openai, faster-whisper, and the browser/ffmpeg paths)
are lazy-imported behind `try/except` inside the functions that use them — never at
module top level.** That's why the default suite can import and exercise almost the
entire package (spec validation, theming, keyframe math, compose logic, subtitle
cueing, audio mixing math, TTS *routing*) without any of those deps installed.

Two practical consequences when you add code:

1. Keep new imports of optional deps inside the function body, guarded, with a clear
   error or fallback when absent — see `tts.py` for the pattern (`find_spec(...)` in
   `available()`, the real import inside the synth helper).
2. Pyright is configured with `reportMissingImports = false` /
   `reportMissingModuleSource = false` precisely because of this — don't "fix" a
   missing-stub complaint by adding a top-level import.

Coverage runs in CI (`--cov=demoreel --cov-report=term-missing`); `cli.py` is omitted
from the coverage source (it's exercised by the CLI smoke step instead).

---

## Lint, format, and types

Three gates, all run from `engine/`:

```bash
uv run ruff check .          # lint
uv run ruff format .         # format (CI runs `ruff format --check .`)
uv run pyright               # type-check
```

- **Formatter:** ruff, `line-length = 100`. `examples/` is excluded from ruff.
- **Lint ruleset:** `E`, `W` (pycodestyle), `F` (pyflakes), `I` (import sort),
  `UP` (pyupgrade), `B` (bugbear), `BLE` (blind-except), `S` (bandit / security),
  `SIM` (simplify), `RUF` (ruff-specific).
- **Ignored, deliberately:** `S603`/`S607` (we shell out to `say`/`afconvert`/`ffmpeg`
  on PATH), `E501` (length is the formatter's job), `RUF001` (typographic `×`/`–`/`—`
  are used on purpose in user-facing strings). Tests relax `S101`/`S310`/`BLE001`.
- **Type-check target:** Python 3.10, `basic` mode, over `demoreel/` only. Missing-import
  / missing-module-source / attribute-access issues are suppressed for the lazy optional
  deps (see above). Don't reach for blanket `# type: ignore` — narrow the type or guard
  the import instead.

If the source carries a `# noqa: <CODE>`, it's intentional — the corresponding rule is
turned *on* in `select`. Prefer fixing over silencing; when you must silence, scope it to
a single code on a single line and say why.

---

## The justfile

`engine/justfile` wraps the common tasks (run `just` in `engine/` for the list). Each target
mirrors what CI runs, so local green == CI green:

| Target | What it runs |
|------------|-------------------|
| `just setup` | `uv sync --all-extras --group dev` + `playwright install chromium` |
| `just ci`    | `ruff check` + `ruff format --check` + `pyright` + `pytest --cov` |
| `just check` | same as `ci` (the full gate) |
| `just fix`   | `ruff check --fix` + `ruff format` |
| `just test`  | the fast unit suite (browser/slow excluded) |
| `just test-browser` | the `browser`+`slow` integration suite |
| `just hero`  | render the bundled showcase hero to `/tmp` |

(Don't have `just`? Run the underlying `uv run …` commands directly — they're shown in each
recipe.)

---

## CI overview

Three workflows under `.github/workflows/`, all with `working-directory: engine`.

**`ci.yml`** (on push to `main`, all PRs, manual dispatch):

- **lint + types** — `uv sync --frozen`, then `ruff check`, `ruff format --check`,
  and `pyright`.
- **test** — matrix across Python **3.10 / 3.11 / 3.12 / 3.13**. Each runs
  `uv sync --frozen --python <ver>`, then `pytest` with coverage (the default,
  browser-free suite), then a **CLI smoke** chain: `init → validate → validate an
  example → doctor`. This is the highest-signal cheap check — the local UX a fresh
  user hits first.
- **render (browser)** — installs Chromium and runs `pytest -m "browser or slow"`
  against a local `file://` fixture (no network, no keys). It is `continue-on-error`
  and only runs on PRs / nightly (`if: github.event_name != 'push'`) — slower and
  flakier integration, so it **never blocks**. Rendered `.mp4`/`.srt` artifacts are
  uploaded for inspection.

Because CI uses `uv sync --frozen`, **`uv.lock` is committed** and must stay in sync
with `pyproject.toml`. If you change dependencies, run `uv sync` (or `uv lock`) and
commit the updated lockfile, or `--frozen` will fail.

**`preview.yml`** (on every `pull_request`):

- Renders a fast, fully-**offline** example — the bundled `examples/showcase/acme-hero.yaml`
  against `examples/showcase/acme.html` via a `file://` URL, with `--preview --gif --player`.
- Uploads `demo.mp4`, `demo.gif`, and `demo.player.html` as the **`demo-preview`** artifact
  (7-day retention) and posts/updates a single sticky PR comment linking the run.
- **Non-blocking**: the render step is `continue-on-error`, so a broken preview never blocks a
  merge, and it degrades gracefully on fork PRs (where the comment step lacks write access).

This gives every PR a downloadable clip to eyeball alongside the diff — refreshed in place on
each push.

**`release.yml`** (on `v*` tags, manual dispatch):

- Verifies the **git tag matches `demoreel.__version__`** (single source:
  `engine/demoreel/__init__.py`) — a mismatch fails the release.
- Builds sdist + wheel (`uv build`), creates a GitHub Release with generated notes,
  and (opt-in, when repo var `PUBLISH_TO_PYPI=true` via a PyPI Trusted Publisher /
  OIDC) publishes to PyPI.

To cut a release: bump `__version__` in `engine/demoreel/__init__.py`, update the
changelog, tag `vX.Y.Z` matching that version, and push the tag.

---

## How to add things

Most features have a single, well-defined seam. The four most common:

### A new TTS voice provider

In `demoreel/tts.py`:

1. Subclass `TTSProvider`. Set `name`, implement `available()` (return `True` only
   when the dependency / binary is present — check with `find_spec(...)` or
   `shutil.which(...)`, **not** by importing at module top level), and implement
   `synthesize(text, out_wav, voice)` to write a WAV to `out_wav`.
2. Register the instance in the `PROVIDERS` dict (`{p.name: p for p in (...)}`).
   That single registration wires it into spec validation, the `--engine` flag, the
   `voice.fallback` chain, and the content-addressed cache — nothing else to touch.
3. If it needs a new package, add it under `[project.optional-dependencies]` as its
   own extra (and to `all`); keep the import lazy. API-key-only providers (no package)
   need no extra — see `_ElevenLabs`.
4. Add a unit test in `tests/unit/test_tts.py` exercising routing/`available()`. Keep
   it dependency-free (mock the synth call); real audio belongs behind a marker.

### A new theme preset

In `demoreel/themes.py`: add an entry to `PRESETS` (e.g. `"studio"`, `"dark"`,
`"light"`, `"minimal"`). Presets deep-merge over the default, so you only specify the
keys that differ. Add a case to `tests/unit/test_themes.py`. Stay on-brand —
indigo accent `#6C5CE7`, sparing teal `#5EE0C8`, dark by default.

### A new resolution preset

In `demoreel/spec.py`: add a `name: (w, h)` entry to `_RESOLUTION_PRESETS`. Widths
and heights are rounded down to even (libx264 + yuv420p require it) by the `Quality`
validator — you don't need to pre-round. Add coverage in `tests/unit/test_spec.py`.
A custom `[w, h]` is always accepted without a preset.

### A new annotation

Annotations are drawn **in-page** (so they record naturally and the camera can find
them), which means three coordinated edits:

1. **`demoreel/spec.py`** — add the field to the `Scene` model (and a config model
   like `Callout`/`Arrow`/`Chapter` if it carries options). `extra="forbid"` is on,
   so the field must exist to be accepted.
2. **`demoreel/overlay_js.py`** — implement the drawing function on the
   `window.__demoreel` overlay object (alongside `highlight`, `spotlight`, `callout`,
   `arrow`, `chapter`, `banner`) and export it. Build nodes with `textContent`, never
   `innerHTML`, so user strings can't inject markup.
3. **`demoreel/capture.py`** — wire it in `_annotate(page, scene)`: read the scene
   field and `_evaluate(...)` the matching `window.__demoreel.*` call.

If the annotation should steer the camera (most do), make sure its target flows into
the keyframe track (`keyframes.py`) so zoom follows it. Add a unit test covering the
spec parsing and any capture math.

### A new (or changed) scene transition

Transitions stitch the intro → content → outro segment boundaries. A scene sets
`transition: { type, duration }` (default `crossfade`, `0.5s`); `duration` is the overlap
length. The supported types are `cut`, `crossfade`, `dip`, `wipe`, `push`, and `zoom_blur` —
`crossfade`/`wipe`/`push`/`zoom_blur` overlap adjacent segments by `duration` (the timeline
shortens accordingly), while `cut` and `dip` do not.

1. **`demoreel/spec.py`** — add the type to the transition `type` literal so the spec accepts
   it.
2. **`demoreel/compose.py`** — implement the blend in the `concat_segments` path. Honor
   whether the type overlaps (and by how much) so the timeline math stays correct.
3. **`tests/integration/test_transitions_compositing.py`** — add (or update) an assertion on
   the transition's **mid-overlap frame**. This is required, not optional: the unit suite
   can't see the composited pixels, so a missing assertion is how a transition silently
   degrades to a cut without anything going red. The suite is marked `slow` — run
   `uv run pytest -m slow` before pushing.

### A new spec template (`demoreel init`)

In the `init` scaffolder (`demoreel/cli.py`): templates are `minimal`, `tour`, `social`, and
`hero`, and **every template must produce a spec that `demoreel validate` accepts**. Add a
test that scaffolds your template and validates the output. The CLI smoke chain in CI
(`init → validate → …`) is the first thing a fresh user hits, so keep it green.

---

## Commit and PR conventions

- **Conventional commits.** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`,
  `ci:`, `perf:`. Keep the subject imperative and scoped (e.g.
  `feat(tts): add elevenlabs provider`).
- **Keep the suite green.** Run `uv run ruff check .`, `uv run ruff format .`,
  `uv run pyright`, and `uv run pytest` before pushing. If you touched a
  browser/render path, also run `uv run pytest -m "browser or slow"` locally.
- **Update the changelog.** Note user-visible changes in [`CHANGELOG.md`](CHANGELOG.md)
  (Keep a Changelog format). Bug-fix entries should say what was wrong and what changed —
  terse but concrete.
- **Lockfile.** If you change dependencies, commit the updated `uv.lock` (CI's
  `--frozen` depends on it).
- **Don't commit rendered output.** `.mp4`, `.webm`, `.srt`, `.wav`, `.aiff`, and the
  `.demoreel/` build dir are git-ignored — keep them out of PRs.
- **Small, legible PRs.** One concern per PR. Describe the change and how you verified
  it; attach a short rendered clip or storyboard when the change is visual.

---

See [`CHANGELOG.md`](CHANGELOG.md) for the running history of user-visible changes.
