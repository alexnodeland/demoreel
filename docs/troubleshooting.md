# Troubleshooting & FAQ

Practical fixes for the things that actually go wrong when rendering a demo with
[demoreel](https://github.com/our-nature/demoreel). Most problems fall into one of three
buckets: **the environment isn't set up** (deps, browser, voices), **the spec describes the
page wrong** (selectors, URLs, aspect), or **a voice engine isn't available**. The engine is
built to degrade gracefully — a missing voice falls back to another engine and ultimately to
silence rather than aborting — so a "failed" render is usually a hard error you can read.

All commands below run from the engine directory:

```bash
cd .claude/skills/demo/engine
```

**First move for almost any issue:** run `uv run demoreel doctor`. It checks every required
dependency, Chromium, each voice engine, the karaoke aligner, your API keys, and whether the
default Piper voice is already cached. Re-run it after any fix.

**Two flags that unlock everything else:**

- `--debug` (or `DEMOREEL_DEBUG=1`) prints the full Python traceback instead of the one-line
  `✗ render failed: …`. Reach for it the moment an error message isn't self-explanatory.
- `--headed` (on `render` and `check`) shows the real Chromium window so you can watch what
  the page is doing — invaluable for selector and timing problems.

---

## Environment & setup

### `demoreel doctor` says a dependency is missing

Doctor checks the required libraries (pydantic, pyyaml, numpy, Pillow, opencv, moviepy,
ffmpeg-via-imageio) and Chromium. A `✗` on any required dep means the environment isn't
synced. Fix:

```bash
uv sync --all-extras --group dev   # everything, including dev tools
# or, minimally:
uv sync --extra piper              # core + the default local voice
```

`ffmpeg` itself is **not** a system dependency — it ships through `imageio-ffmpeg`, so you
never need to `brew install ffmpeg`. If doctor flags `ffmpeg (imageio)`, that's the Python
package missing, not a system binary; re-sync.

The voice-engine and caption lines in doctor are informational — a `–` next to `kokoro`,
`openai`, or `faster-whisper` just means that **optional** extra isn't installed. Doctor only
exits non-zero on missing **required** deps.

### `playwright: chromium is not installed` / `run playwright install chromium`

Playwright is installed by `uv sync`, but the browser binary is a separate download. Install
it once:

```bash
uv run playwright install chromium
```

Doctor surfaces this as `✗ playwright chromium: run playwright install chromium`. The same
error appears at render time as `playwright is not installed. … && playwright install
chromium`. After installing, `uv run demoreel doctor` should show `✓ playwright chromium
(installed)`.

### First Piper render stalls "downloading" / pulls ~60MB

Piper is the default voice and it auto-downloads its model from HuggingFace the **first** time
you render with it (the default voice `en_US-lessac-medium` is ~60MB: a `.onnx` plus a small
`.onnx.json`). This is a one-time cost — the model is cached and every later render reuses it.

- **Cache location:** `~/.cache/demoreel/piper/` (override the whole cache root with the
  `DEMOREEL_CACHE` environment variable). `demoreel doctor` prints the active cache dir and
  tells you whether the default voice is already there (`default piper voice ready ✓`).
- **Want to skip the download entirely?** On macOS, render with the built-in system voice —
  zero install, instant, robotic but fine for iteration:

  ```bash
  uv run demoreel render my-demo.yaml --engine say
  ```

- **Air-gapped / download blocked?** Point `voice.model` at a local `.onnx` file you've placed
  yourself, or pick a different engine. A failed download raises a clear `failed to download
  …` error telling you both options.

A download that stalls is capped at a 60-second network timeout so it fails loudly instead of
hanging the render forever.

---

## Voices & narration

### No TTS available / the wrong voice came out / render is silent

The engine never aborts a render over audio. It tries `voice.engine`, then each entry in
`voice.fallback`, and if **everything** fails it writes **silence** sized to the text so pacing
stays intact. So a silent or unexpectedly-voiced render means the preferred engine wasn't
available, not that rendering broke. Watch the progress log for:

```
⚠ voice 'piper' unavailable; rendered with fallback 'say'
⚠ no voice engine produced audio (…); using silence
```

To diagnose and fix:

1. `uv run demoreel voices` — lists every engine with `✓` (ready on this machine) or `–`
   (unavailable), plus the available macOS `say` voices and example voice names.
2. `uv run demoreel doctor` — shows which voice packages/binaries and which API keys are
   present.
3. Install the engine you actually want, or set a `fallback` chain so an unavailable primary
   degrades to a real voice instead of silence:

   ```yaml
   voice:
     engine: piper
     fallback: [say, espeak]   # tried in order if piper isn't available
   ```

Engine cheat-sheet:

| Engine | How to get it | Notes |
|--------|---------------|-------|
| `piper` | `uv sync --extra piper` | Default. Local neural TTS, auto-downloads voices. |
| `kokoro` | `uv sync --extra kokoro` | Higher quality, local, experimental. May need `KOKORO_MODEL_PATH` + `KOKORO_VOICES_PATH`. |
| `say` | built-in on macOS | Zero install, fast, robotic. Great for iteration. |
| `espeak` | `brew install espeak-ng` / `apt install espeak-ng` | Cross-platform robotic fallback (the Linux/Windows `say`). |
| `openai` | `uv sync --extra cloud` + `OPENAI_API_KEY` | Cloud. Set `voice.base_url` for any OpenAI-compatible endpoint. |
| `elevenlabs` | `ELEVENLABS_API_KEY` (no package needed) | Cloud via REST. Experimental. |

**Changing narration and nothing re-synthesizes?** TTS is content-addressed cached (keyed by
engine + voice + rate + the exact text) under `~/.cache/demoreel/tts/`. Identical narration is
served from cache, which makes re-renders instant and cloud engines free. If you suspect a
stale cache, clear that directory (or the whole `DEMOREEL_CACHE` root).

### `OPENAI_API_KEY is not set` / `ELEVENLABS_API_KEY is not set`

Cloud engines check credentials at synthesis time (not at startup). Export the key for the
engine you chose:

```bash
export OPENAI_API_KEY=sk-…          # for voice.engine: openai
export ELEVENLABS_API_KEY=…         # for voice.engine: elevenlabs
```

`demoreel doctor` shows a `✓`/`–` for each key. For OpenAI-compatible local/proxy servers
(LocalAI, Azure, an internal gateway) set `voice.base_url` — when `base_url` is set the OpenAI
engine doesn't require `OPENAI_API_KEY`. If a key is missing the engine raises a `TTSError`,
which (per the fallback behavior above) drops you to the next engine or to silence — so check
the progress log if cloud audio quietly didn't appear.

### `say` works but the WAV is wrong on a non-standard macOS

`say` produces AIFF, which the engine converts to WAV with `afconvert` (built into macOS) and
falls back to `ffmpeg` if `afconvert` is somehow absent. Doctor notes this as
`macOS say (afconvert missing → ffmpeg fallback)`. Both paths produce valid audio; the note is
just informational.

### Karaoke captions don't animate word-by-word

Word-level (karaoke) captions need Whisper alignment, which is an optional extra:

```bash
uv sync --extra align
```

Doctor's captions section shows `✓ faster-whisper (karaoke)` when it's installed, or a `–`
with the reminder that **`pill` and `lower_third` captions work without it**. If `--extra
align` isn't installed, set `captions.style` to `pill` or `lower_third` and captions still
render — you just lose the per-word highlight.

---

## Visual & framing

### My app flashes white at the start / the window looks washed out

**This is fixed — it just works now.** Two related issues used to bite dark or glassy apps:

- A **white flash** during the blank lead-in and on each navigation, before the app's own CSS
  painted. The engine now paints the theme's base color (a near-black `#101016` on dark
  backdrops, `#fcfcfe` on light) onto the document at `document_start`, **before** the app's CSS
  loads, via an inline style that outranks non-`!important` app rules. No more white frame.
- A **washed-out / bleeding-through** window for apps with a **transparent `<body>`**. The
  window panel is now opaque, so a glassy or dark app records *on the theme base* instead of
  letting the gradient backdrop show through and wash the content out.

You don't need to do anything. A transparent-bodied app now records on the correct base color
automatically. If you still see a flash, you're likely on an older build — pull latest.

### Aspect / letterbox warning during `validate`

```
⚠ viewport 1600×900 and output 1080×1920 differ in aspect — the window will be letterboxed.
```

This warning **only** appears for `frame.style: full_bleed`. In `full_bleed`, the recording
fills the whole frame, so a viewport whose aspect ratio doesn't match the output gets black
bars. Fix by matching `viewport` to the output aspect.

For the default `studio` framing (and mobile `device` frames), this is **not** a problem and no
warning fires — the recording deliberately floats as a window on a gradient backdrop, so a
narrow phone capture inside a wide output is the intended look. Don't try to "fix" an aspect
mismatch in studio mode; it's by design.

### Camera zoom didn't happen on a scene

The log shows `⚠ scene N: focus target not found, zoom skipped: <selector>`. Causes:

- The focus selector matches nothing — fix the selector (run `check`, see below).
- The element exists but isn't visible/laid-out when probed.

Note the engine already handles the trickiest case: a **click that swaps the view** (reveals a
panel, advances a step) removes its own target before the post-action probe runs. The engine
probes the focus rect **before** the click and uses that as a fallback, so reveal-style clicks
still zoom. If a zoom is still skipped, it's a genuinely missing/invisible target — point
`focus:` at an element that survives the action, or set an explicit `zoom:`.

### Annotation (highlight / spotlight / callout / arrow) didn't show

Overlays are drawn in-page and **fail silently** by design. To catch typos, the engine logs a
per-scene warning when an annotation selector matches nothing:

```
⚠ scene N: highlight selector matched nothing: <selector>
```

Fix the selector. These selectors are validated by `demoreel check` too.

---

## Selectors, navigation & `check`

### `check` reports a selector missing, but it works at render time

`demoreel check` opens the page and verifies each selector resolves **at that moment**. A
selector that's only revealed by an **earlier scene's click** (a panel that opens, a tab that
switches, a step that advances) legitimately won't exist when `check` probes the initial page,
so it reports `✗`. That's expected for conditionally-visible targets — at render time the prior
scenes run first and reveal them.

Triage:

- If the selector is behind an interaction, the `✗` is a false alarm; the real render will hit
  it after the preceding click. Confirm by running `render --headed` and watching.
- If it's a genuine typo or a selector for an element that *should* be on the initial page, fix
  it. Prefer `text=` / `role=` selectors — they survive redesigns far better than brittle CSS
  paths.

Run `check` early and often; it's the cheapest way to catch broken selectors before a full
render.

### `goto: /` (or a bare path) against a `file://` page fails

For file-based demos there's **no base URL to join a relative path onto**, so `goto: /`
resolves to nothing useful. Use the **full `file://` URL** in `goto`:

```yaml
scenes:
  - goto: "file:///abs/path/to/index.html"   # full URL, not "/"
```

Absolute URLs (`http://`, `https://`, `about:`, `file:`) are used as-is. Relative paths are
only joined when you've set a top-level `url:` base — which file demos typically don't have.
(Also note: the first scene **must** `goto` a URL, or you must set a top-level `url:`.)

### `the first scene must goto a URL`

Every demo has to start by navigating somewhere. Either give the first scene a `goto:`, or set
a top-level `url:` that the first scene navigates to implicitly.

---

## Templating & parameterization

### `${VAR}` came through literally / `--set expects KEY=VALUE`

Specs support `${VAR}` and `${VAR:-default}` templating, filled from `--set KEY=VALUE` (repeat
the flag per variable) and from the environment. Two gotchas:

- `--set` must be `KEY=VALUE`; `--set FOO` alone errors with `--set expects KEY=VALUE, got
  'FOO'`.
- `--set` also works on `validate` and `check`, so you can preview the resolved plan before
  rendering:

  ```bash
  uv run demoreel validate parameterized.yaml --set ENV=staging --set USER=alex
  uv run demoreel render   parameterized.yaml --set ENV=staging --set USER=alex
  ```

If a variable has no `--set`, no env value, and no `${VAR:-default}`, it won't substitute —
add a default in the spec or pass it on the command line.

---

## Live data, auth & multi-tab

### Real customer names / numbers / emails are visible in the recording

Use **live-data redaction** to scrub selector text before it's recorded:

```yaml
prelude:
  redact: [".customer-name", ".invoice-total", ".email"]
  redact_mode: scramble   # scramble (default) | block | label
```

`scramble` keeps shape but garbles content, `block` masks it out, `label` replaces it with a
placeholder. Redaction re-arms on every navigation and watches for late-rendering data, so it
covers content that loads after the page does. For whole elements you'd rather hide or blur
entirely, use `prelude.hide: [sel]` or `prelude.mask: [sel]`.

### Pre-authenticated demos

Capture a Playwright storage state once, then point the spec at it:

```bash
uv run playwright open --save-storage=auth.json https://your-app.example.com
# log in, close the window
```

```yaml
storage_state: auth.json
```

### A click opens a new tab and the demo loses it

By default Playwright opens the new tab separately and the recording stays on the original
page. To keep the flow in one continuous video, mark the scene:

```yaml
scenes:
  - click: "a[target=_blank]"
    follow_new_tab: true
```

The engine waits for the popup, grabs its URL, and continues that URL in the **same** recorded
page. If no tab opens it logs `⚠ scene: follow_new_tab opened no new tab (…)` and carries on
rather than crashing.

---

## Determinism & flaky pages

A page that animates, shows spinners, or renders content asynchronously can make a render look
different each time. Tools, in `prelude`:

- `freeze_anim: true` — kills looping CSS animations (spinners) while leaving transitions
  intact so the cursor still eases.
- `hide: [sel]` / `mask: [sel]` — remove or blur noisy/irrelevant chrome.
- `inject_css` / `inject_js` — force a deterministic state (e.g. pin a clock, disable a
  carousel) at `document_start`.

Per-scene, use `wait_for: <selector>` to hold the scene until an element is visible (handy for
async content); if it never appears you'll see `⚠ scene N: wait_for never became visible`. Use
`pause:` for a silent beat before an action and `hold:` to dwell after.

---

## Tests & development

The default `uv run pytest` run is **fast and dependency-light**: it excludes the `browser`
(needs a real Chromium) and `slow` (full render through moviepy + ffmpeg) markers via
`addopts = "-m 'not browser and not slow' --strict-markers"`. To run the heavier suites
explicitly:

```bash
uv run pytest                       # fast unit suite (default)
uv run pytest -m "browser or slow"  # the browser + render tests
uv run pytest -m browser            # just the Chromium-backed tests
```

Other dev commands (a `justfile` with `ci`/`check`/`fix`/`test` targets may also exist):

```bash
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pyright           # type-check
```

`--strict-markers` means a typo'd marker fails the run instead of silently selecting nothing —
if you add a new marker, register it in `pyproject.toml`.

---

## FAQ quick reference

| Symptom | Fix |
|---------|-----|
| Doctor flags a required dep | `uv sync --all-extras --group dev` (or `uv sync --extra piper`) |
| `playwright: chromium not installed` | `uv run playwright install chromium` |
| First render pulls ~60MB | One-time Piper voice download to `~/.cache/demoreel/piper/`; or `--engine say` on macOS |
| Render is silent / wrong voice | Engine fell back; `demoreel voices` + `doctor`, install the engine or set `voice.fallback` |
| `OPENAI_API_KEY` / `ELEVENLABS_API_KEY` not set | Export the key; for OpenAI-compatible servers set `voice.base_url` |
| Karaoke captions flat | `uv sync --extra align`; or use `pill`/`lower_third` |
| White flash / washed-out window | Fixed — opaque panel + base-color paint. Pull latest if you still see it |
| Letterbox warning | Only `full_bleed`; match `viewport` to output aspect. Harmless in `studio` |
| `check` says a selector is missing | Conditionally-visible? Revealed by an earlier scene's click — confirm with `render --headed` |
| `goto: /` on a `file://` page fails | Use the full `file:///…` URL |
| `${VAR}` literal in output | Pass `--set KEY=VALUE` (repeatable) or add `${VAR:-default}` |
| Real data on screen | `prelude.redact` + `redact_mode`; or `prelude.hide` / `prelude.mask` |
| New tab lost mid-demo | `follow_new_tab: true` on the click scene |
| Unreadable one-line error | `--debug` (or `DEMOREEL_DEBUG=1`) for the full traceback |
| Need to see what's happening | `--headed` on `render` / `check` |

---

*demoreel is MIT-licensed (Alex Nodeland), built by the Our Nature studio ·
[repo](https://github.com/our-nature/demoreel) · [landing](https://our-nature.github.io/demoreel/)*
