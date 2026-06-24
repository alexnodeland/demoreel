---
name: demo
description: "Produce a studio-quality demo video walkthrough — drives a web app with Playwright and renders an mp4 with auto zoom-to-click, a macOS browser-window frame on a gradient backdrop, animated cursor + keycast, annotations (highlight/spotlight/callout/arrow/chapter), voiceover, captions (incl. karaoke), music, SFX, and brand cards. Authored from a declarative YAML spec. Use when the user wants a screen-recorded product walkthrough, feature demo, or release video."
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, mcp__plugin_playwright_playwright__browser_navigate, mcp__plugin_playwright_playwright__browser_snapshot, mcp__plugin_playwright_playwright__browser_take_screenshot, mcp__plugin_playwright_playwright__browser_click, mcp__plugin_playwright_playwright__browser_type, mcp__plugin_playwright_playwright__browser_evaluate, mcp__plugin_playwright_playwright__browser_wait_for
argument-hint: "[what to demo, e.g. 'the onboarding flow on localhost:3000' or 'render demos/tour.yaml']"
---

# Demo: Studio-Quality Video Walkthroughs

Make a demo video **programmatically** — but make it *good*. The `demoreel` engine (in the
`engine/` folder beside this file) handles the mechanics: Playwright drives the app, and
compose produces a studio-framed mp4 with auto zoom-to-click, animated cursor, voiceover,
captions, annotations, and brand cards. **Your job is the craft** — scouting the real app,
storyboarding a tight narrative, and reviewing your own output until it's sharp.

> Paths below assume the skill is installed at `.claude/skills/demo/` (so the engine is at
> `.claude/skills/demo/engine/`). Adjust if you mounted it elsewhere.

**Request:**

---
$ARGUMENTS
---

Full schema/flags: `engine/README.md`.

## The bar — what "above and beyond" means here

A throwaway demo records some clicks. A great one tells a story. **Every** demo you produce
should clear this bar, without being asked:

- **Scouted, not guessed** — selectors verified against the live DOM (never invented).
- **A narrative arc** — hook → context → 2–4 key actions → payoff → outro, not a flat tour.
- **Money moments framed** — the one or two beats that matter get a `spotlight`/`callout`
  and a deliberate zoom; everything else stays calm.
- **Tight voiceover** — one idea per scene, benefit-led, ~12–18 words, conversational.
- **Audience-tuned** — preset, voice, and pace chosen for who's watching.
- **Self-reviewed** — render a preview, *look at the frames*, and fix what's off before
  the final cut.
- **Clean** — cookie banners hidden, spinners frozen, intro + outro present, captions on.

## Project house style

If the consuming project defines a **demo house-style / context doc** (e.g. a
`demo-house-style.md` in its context/docs folder, or a pointer in its `CLAUDE.md`/`AGENTS.md`),
**read it first and apply it** — it carries the project's preset/branding, voice, audience
norms, default app URL + auth, and which flows matter. The guidance below is the generic
default when no house style is provided.

## Workflow

### 0 — Setup (once)

```bash
cd .claude/skills/demo/engine && uv run demoreel doctor
```
If anything's missing: `uv sync --extra piper && uv run playwright install chromium`
(add `--extra align` for karaoke captions, `--extra cloud` for OpenAI voices).

### 1 — Scope & audience

Decide (ask 1–2 quick questions only if genuinely ambiguous — URL, local vs deployed, auth):

| Audience | preset | voice | pace |
|----------|--------|-------|------|
| Engineers / internal | `studio` (or `dark`) | piper `en_US-ryan-high` | brisk, can show detail |
| Leadership / execs | `light` | openai (if key) or piper, warm | slower, benefit-framed, minimal jargon |
| Customers / release | `studio` or branded | openai / ElevenLabs | polished, confident, add brand kit |
| Quick teardown / bug repro | `minimal` | `say` (macOS) | fast, no fluff |

Default to `studio` + piper if unsure. For leadership, lean on `spotlight`/`callout` and
keep narration outcome-focused.

### 2 — Recon the live app (do not skip)

Wrong selectors are the #1 cause of bad demos. **Before writing any YAML**, scout the real
target with Playwright MCP:

1. `browser_navigate` to the start URL (start the app first if local; for authed apps,
   confirm you can reach the flow — capture a `storage_state` if not).
2. `browser_snapshot` at each state you'll demo to harvest **stable** selectors — prefer
   `text=`/`role=`/`aria` over brittle CSS. Walk the actual flow so you capture selectors
   for states that only appear after an action (results, modals).
3. `browser_take_screenshot` of the key screens — you'll use these to storyboard and to
   judge what deserves a zoom.
4. Note anything that will dirty the recording: cookie/consent banners, autoplaying
   animations, live clocks, avatars → these become the `prelude` (`hide`/`freeze_anim`/`mask`).

If the app is genuinely unreachable, say so and ask how to proceed rather than guessing.

### 3 — Storyboard the narrative

Write the beats before the YAML. A demo is a story:

- **Hook** (intro card + 1 line): what this is and why it matters.
- **Context** (1 scene): land on the app, orient the viewer.
- **Key actions** (2–4 scenes): the actual flow. Each = one action + one sentence.
- **Payoff** (1 scene): the result/outcome — usually the biggest money moment (`spotlight`
  it, hold longer, zoom in).
- **Outro card**: takeaway + CTA.

Map each money moment to a device: `spotlight` to isolate, `callout` to label, `chapter` to
divide a multi-part flow, `arrow` to point. Don't decorate every scene — contrast is what
makes the highlighted beats land.

### 4 — Author the spec

**Scaffold first** — don't hand-write from a blank file. `demoreel init <slug>.yaml --template
<minimal|tour|social|hero> --title "…" --url <url>` writes a render-ready spec from a template
+ answers (also accepts `--preset --resolution --device --voice-engine --transition -o`; runs
interactively if you omit flags on a TTY). `social` = a 9:16 phone-frame cut; `hero` = a
studio reel for a README. Every template validates clean. Then edit it down.

Write to `demos/<slug>.yaml` (mp4 lands next to it). One action per scene. Apply the craft:

**Narration** — speak benefits, not mechanics. One idea per scene. Read it aloud in your
head; if it's a mouthful, cut it. The engine paces each scene to its audio automatically.

**Camera** — trust `auto_zoom` (element-aware). Add `no_zoom` for deliberately wide beats.
Reserve the tightest zooms for the payoff.

**Cleanliness** — set `prelude: { freeze_anim: true, hide: [<banners you found>] }`.

**Transitions** — per-scene `transition: { type, duration }` controls how each beat is
stitched onto the previous one. Types: `cut`, `crossfade` (default), `dip`, `wipe`, `push`,
`zoom_blur`; `duration` (default `0.5`s) is the overlap. `crossfade`/`wipe`/`push`/`zoom_blur`
overlap adjacent scenes; `cut`/`dip` don't. Use a `push` or `zoom_blur` to punch into the
payoff, `cut` for a brisk teardown. Applies to intro→content→outro boundaries too.

**Brand kit** — for a repeatable team look, set a top-level `brand_kit: path/to/kit.yaml`
(resolved relative to the spec). The kit's `accent` fans out to `brand.color`,
`captions.accent`, and `cursor.color`; `background: [from, to]` becomes the gradient backdrop;
plus `logo`, `font`, `name`, `title`, `watermark`. Precedence is **spec > kit > preset** — the
kit fills gaps and beats the preset, while any explicit spec field wins. See
`engine/examples/brand/acme.brand.yaml` (a kit) + `with-kit.yaml` (a spec overriding it).

```yaml
title: "Onboarding"
url: "http://localhost:3000"
viewport: [1600, 900]
output: "onboarding.mp4"
preset: studio
storage_state: "auth.json"            # if the app needs login
voice:   { engine: piper, model: en_US-ryan-high }
prelude: { freeze_anim: true, hide: [".cookie-banner"] }
intro: { title: "Onboarding", subtitle: "From zero to first value", seconds: 2.5, narrate: "Watch a new user get to value in under a minute." }
scenes:
  - { narrate: "Start on the dashboard.", goto: "/", hold: 1.0 }
  - { narrate: "Create your first project.", click: "text=New Project" }
  - { chapter: { title: "Configure" }, narrate: "Name it and pick a template.", type: { selector: "#name", text: "Acme launch" } }
  - { narrate: "One click to provision.", press: "Enter", wait_for: "text=Ready", hold: 2.5 }
  - { narrate: "Seconds later — you're live.", spotlight: "#status", callout: { text: "Provisioned", at: ".status-badge" }, hold: 3.0 }
outro: { title: "That's onboarding", seconds: 2.2, cta: "Try it →" }
```

### 5 — Check & validate (cheap, before the slow render)

```bash
cd .claude/skills/demo/engine
uv run demoreel validate <spec>.yaml   # schema + scene plan + estimated runtime
uv run demoreel check    <spec>.yaml   # opens the page, verifies EVERY selector resolves
```
Fix every `✗` from `check` here — these are the failures that would waste a full render.

### 6 — Preview & SELF-REVIEW (the step that makes it great)

```bash
uv run demoreel render <spec>.yaml --preview --storyboard
```
Then **actually look at your output**: `Read` the generated `*.storyboard.png` (a 3×3
contact sheet) and the `*.transcript.md`, and critique like a director:

- Is each money moment framed and zoomed on the *right* element?
- Any scene where the page is mid-load, a banner shows, or the cursor is off-target?
- Is the narration tight, and does the arc land (hook → payoff → outro)?
- Pacing: any beat too rushed or too long? (`hold`, `pause`, narration length)

Edit the spec and re-preview until it's sharp. This loop is the difference between
"functional" and "above and beyond" — do at least one pass.

**Tighten the loop with `watch`:** `uv run demoreel watch <spec>.yaml [--interval 1.0] [--set
K=V]` renders a `--preview` once, then re-renders whenever the spec *or* a referenced **local**
asset changes (music, logo, brand kit, `inject_css`/`inject_js`, a `file://` page URL). Remote
URLs aren't watched. It's polling-based (no extra deps); a broken mid-edit spec is logged and
the watcher keeps running until it parses again. `Ctrl-C` stops cleanly.

### 7 — Final render

Full quality, then announce when done (render is long-running):

```bash
uv run demoreel render <spec>.yaml -o <output>.mp4 [--gif] [--webp] [--player]
```
Outputs land beside the mp4: `.srt`, `.vtt`, `.transcript.md`, plus `--gif`/`--webp` (a
looping clip for READMEs/social/chat) and `--player` (a self-contained HTML page with a
clickable chapter rail — great for sharing a walkthrough as one link).

**Pick the format to the channel:** a `vertical` (9:16) or `square` (1:1) cut inside a
`frame: { device: phone }` shell for social; a wide `studio` mp4 for docs; a `--gif` for a
README hero. Set `quality.resolution` to the target aspect and match the `viewport`.

### 8 — Deliver

Report the path + runtime; mention the `.srt`/transcript (accessibility, sharing) and any
`--gif`/`--player` you produced. Log/share per the consuming project's conventions. Don't
post anything externally without the OK.

## Quick spec cheatsheet

**Actions** (one/scene): `goto · click · hover · type{selector,text} · press · scroll{to|by} · wait`.
**Annotations** (combine freely): `highlight · spotlight · callout{text,at} · arrow{to,dir} · chapter{title,subtitle}`.
**Hints:** `zoom|no_zoom · focus · hold · pause · wait_for · narrate_after · persist · follow_new_tab`.
**Presets:** `studio`(default) · `dark` · `light` · `minimal`. **Captions:** `pill|lower_third|karaoke`.
**Transitions** (per-scene `transition: { type, duration }`): `cut · crossfade`(default)`· dip · wipe · push · zoom_blur`; `duration`(0.5s) = overlap.
**Resolutions:** `720p · 1080p · 1440p · 4k`, social `vertical`(9:16) · `square`(1:1) · `portrait`(4:5), or `[w,h]`.
**Frame shell:** `frame.device: phone|tablet|none` (a device bezel instead of the browser window).
**Clean/redact:** `prelude: { freeze_anim, hide, mask, redact: [sel], redact_mode: scramble|block|label }`.
**Templating:** `${VAR}` / `${VAR:-default}` anywhere in the YAML → `render … --set VAR=value` (per-tenant/per-release cuts).
**Scaffold:** `demoreel init <slug>.yaml --template minimal|tour|social|hero --title … --url …` (interactive if no flags).
**Watch:** `demoreel watch <spec>.yaml` re-previews on spec/local-asset change (`Ctrl-C` to stop).
**Brand kit:** top-level `brand_kit: kit.yaml` (`accent`/`background`/`logo`/`font`/`name`/`title`/`watermark`); precedence **spec > kit > preset**.
**Brand from a logo:** `demoreel theme path/to/logo.png` → prints a palette to paste into the spec.
**Match narration to the action** — say exactly what the scene's action does (a click that
*reveals* something still frames correctly; the camera probes the target before it acts).
Full schema → `engine/README.md` · `docs/spec-reference.md`.

## Troubleshooting

- **Selector timeout** → re-run `demoreel check`; you scouted the wrong state. Capture is
  best-effort, so a partial video still renders — but fix it.
- **Soft/blurry** → set `viewport` near the studio window width (~1600 for 1080p), or raise `quality.resolution`.
- **Robotic voice** → `voice.engine: openai`, or a better piper voice (`en_US-ryan-high`).
- **Busy/flaky page** → expand `prelude` (`freeze_anim`, `hide`, `mask`).
- **Slow iteration** → always `--preview` until the final cut.
