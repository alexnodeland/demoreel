# Changelog

All notable changes to demoreel are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-06-24

### Added

- Scene transitions library — `transition.type` now supports `cut`, `crossfade` (default), `dip`, `wipe`, `push`, and `zoom_blur`, with `transition.duration` (default `0.5`s) as the overlap length. `wipe` is a hard-edged left→right mask reveal, `push` slides the outgoing clip out left while the incoming slides in from the right, and `zoom_blur` is a crossfade with a fast 1.08→1.0 whip-zoom on the incoming clip. Applies at the intro→content→outro boundaries; `crossfade` / `wipe` / `push` / `zoom_blur` overlap adjacent segments by `duration`, while `cut` / `dip` do not (`transition: { type: push, duration: 0.4 }`).
- Brand kits — a reusable look bundle loaded via a top-level `brand_kit: path/to/kit.yaml` directive (resolved relative to the spec). Kit fields: `accent`, `background` (`[from, to]` hex gradient), `logo`, `font`, `name`, `title`, `watermark`, `watermark_position`, `watermark_opacity`. `accent` fans out to `brand.color`, `captions.accent`, and `cursor.color`; `background` maps to `frame.background.colors` (angle `135`). Merge precedence, highest wins: **spec > brand kit > preset** — the kit fills gaps under the spec and overrides the preset, and a sparse kit only fills the keys it sets.
- `demoreel init` template scaffolder — generates a ready-to-render spec from a `minimal`, `tour`, `social`, or `hero` template, each of which `demoreel validate` accepts. Flags: `--template`, `--title`, `--url`, `--preset`, `--resolution`, `--device`, `--voice-engine`, `--transition`, `-o/--output`, `-y/--yes`. Runs interactively (prompts with validated defaults) when stdin is a TTY and `--yes` was not passed, otherwise builds non-interactively from the template + flags. The output filename derives from a slug of the title unless `--output` is given (`demoreel init demo.yaml --template social --title "My App" --url https://myapp.com`).
- `demoreel watch` mode — `demoreel watch spec.yaml [--interval 1.0] [--engine ENGINE] [-o OUT] [--set K=V]` renders a fast `--preview` once on start, then re-renders whenever the spec or a referenced local asset changes (the spec file, music, logo, `brand_kit`, `inject_css` / `inject_js` paths, and a `file://` page URL). Polling-based with no new dependencies; remote `http(s)` URLs are not watched. A broken or mid-edit spec does not kill the watcher — it keeps watching until the spec parses again, and `Ctrl-C` stops gracefully.
- PR preview-render CI workflow — `.github/workflows/preview.yml` renders a fast offline example (`examples/showcase/acme-hero.yaml` against `examples/showcase/acme.html` via a `file://` URL, with `--preview --gif --player`) on every pull request, uploads `demo.mp4` / `demo.gif` / `demo.player.html` as the `demo-preview` artifact (7-day retention), and posts or updates a single sticky PR comment linking the run. Non-blocking (the render step is `continue-on-error`) and degrades gracefully on fork PRs.

### Changed

- `demoreel init` now scaffolds from templates (`minimal` / `tour` / `social` / `hero`) instead of copying `starter.yaml` verbatim.
- Transition caption-sync is centralized through `overlap_offset`, so `wipe`, `push`, and `zoom_blur` keep captions in sync the same way `crossfade` does.

### Fixed

- The `push` transition now composites a true positional slide — previously it degraded to a full-frame cover.

## [0.2.0] - 2026-06-24

### Added

- Social/vertical resolution presets — `9:16` (vertical), `1:1` (square), and `4:5` (portrait).
- Mobile device frames — wrap the capture in a phone or tablet shell via `frame.device`.
- Live-data redaction — `prelude.redact` with `redact_mode` (`scramble` / `block` / `label`) to hide sensitive on-screen values.
- Spec templating — `${VAR}` and `${VAR:-default}` substitution, driven by repeatable `--set KEY=VALUE`.
- GIF and WebP export from a render via `--gif` / `--webp`.
- Interactive HTML chapter player output via `--player`.
- Brand-from-logo theming — the `demoreel theme <logo>` command and `swatch` module derive an accent palette from a logo image.
- Multi-tab capture — `follow_new_tab` continues recording into a newly opened tab.
- TTS provider registry with a fallback chain and a content-addressed on-disk cache, adding `kokoro`, `espeak`, and OpenAI-compatible (`voice.base_url`) engines.
- Expanded `doctor` and `voices` diagnostics.
- CI (lint + pyright + pytest on Python 3.10–3.13), a release workflow (PyPI trusted publishing), Dependabot, and a full pytest suite.

### Changed

- Modernized `pyproject.toml` — dynamic version, install extras (`piper` / `kokoro` / `cloud` / `align` / `all`), a `dev` dependency group, and ruff/pyright/pytest configuration.
- The aspect-ratio mismatch warning now fires only for `full_bleed` framing.

### Fixed

- Opaque window panel so dark or glassy apps no longer bleed through the gradient backdrop.
- Theme base color is now painted before app CSS loads, killing the white flash and the transparent-body-renders-white case.
- Focus rect is probed before self-removing clicks, so reveal-clicks still trigger zoom-to-click.
- `demoreel init` now writes a real bundled starter spec.
- Quality normalization via a pydantic v2 `model_validator` (enforces even dimensions).
- 8-bit WAV read.
- Subtitle cue clamping and crossfade caption-offset sync.
- Chapter card is built with `textContent` (no markup injection).

[0.3.0]: https://github.com/our-nature/demoreel
[0.2.0]: https://github.com/our-nature/demoreel
