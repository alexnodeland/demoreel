# Changelog

All notable changes to demoreel are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/our-nature/demoreel
