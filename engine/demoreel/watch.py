"""`demoreel watch` core — re-render a fast preview whenever the spec or a local asset
it references changes.

Polling-based by design: no filesystem-watch dependency (watchdog/inotify). We snapshot
the mtimes of the spec file plus the local files it points at (music, logo, brand kit,
injected CSS/JS, a ``file://`` url), sleep, and re-snapshot. Any mtime delta — or a file
appearing/vanishing — triggers a re-render.

The loop core is deliberately I/O-free and clock-free: ``watch_loop`` takes injected
``sleep_fn`` / ``render_fn`` / ``paths_fn`` so it can be driven deterministically in tests
without real sleeping or rendering. ``cli.py`` owns the ``watch`` subcommand and builds the
render callback; this module is the polling engine and path collection it wires to.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from collections.abc import Callable


def _maybe_file(value: object) -> Path | None:
    """A string that plausibly names a local file → its Path, else None.

    Remote refs (http/https) and non-string / empty values are skipped. ``file://`` urls
    are resolved to their local path. Existence is filtered later, in collect_watch_paths.
    """
    if not isinstance(value, str) or not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    # bare path (no scheme) — or anything else we treat as a local path
    if parsed.scheme and parsed.scheme not in {"", "file"}:
        # some other uri scheme (data:, etc.) — not a local file
        return None
    return Path(value)


def collect_watch_paths(spec_path: str | Path, spec: object) -> list[Path]:
    """The spec file plus the local files whose edits should trigger a re-render.

    Duck-types ``spec`` (everything via ``getattr``) so it works even when whole sections are
    absent. Returns de-duped, existing, absolute Paths. Remote urls and None values are dropped.
    """
    candidates: list[Path] = [Path(spec_path)]

    audio = getattr(spec, "audio", None)
    candidates_raw: list[object] = [getattr(audio, "music", None)]

    brand = getattr(spec, "brand", None)
    candidates_raw.append(getattr(brand, "logo", None))
    candidates_raw.append(getattr(brand, "brand_kit", None))

    prelude = getattr(spec, "prelude", None)
    candidates_raw.append(getattr(prelude, "inject_css", None))
    candidates_raw.append(getattr(prelude, "inject_js", None))

    candidates_raw.append(getattr(spec, "url", None))

    for raw in candidates_raw:
        p = _maybe_file(raw)
        if p is not None:
            candidates.append(p)

    seen: set[str] = set()
    out: list[Path] = []
    for p in candidates:
        abs_p = p.resolve()
        key = str(abs_p)
        if key in seen:
            continue
        seen.add(key)
        if abs_p.exists():
            out.append(abs_p)
    return out


def snapshot(paths: list[Path]) -> dict[str, float]:
    """Map ``str(path) -> mtime`` for each path, skipping files that have vanished."""
    out: dict[str, float] = {}
    for p in paths:
        try:
            out[str(p)] = os.path.getmtime(p)
        except OSError:
            continue
    return out


def changed(prev: dict[str, float], curr: dict[str, float]) -> bool:
    """True when any tracked file's mtime moved or a key was added/removed."""
    if prev.keys() != curr.keys():
        return True
    return any(prev[k] != curr[k] for k in curr)


def watch_loop(
    paths_fn: Callable[[], list[Path]],
    render_fn: Callable[[], object],
    *,
    sleep_fn: Callable[[float], object],
    interval: float = 1.0,
    max_iterations: int | None = None,
    log: Callable[[str], object] | None = None,
) -> int:
    """Render once, then poll for changes and re-render on each detected change.

    ``paths_fn`` is re-evaluated every tick so newly-added asset references are picked up.
    ``max_iterations`` caps poll iterations (for tests); None loops until KeyboardInterrupt.
    A render that raises is caught and logged — the watcher keeps going so a broken edit can
    be fixed without restarting. Returns 0.
    """

    def _log(msg: str) -> None:
        if log is not None:
            log(msg)

    def _render() -> None:
        try:
            render_fn()
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001 - keep watching after a failed render
            _log(f"render failed: {e}")

    # initial render + baseline
    _render()
    baseline = snapshot(paths_fn())
    _log(f"watching {len(baseline)} files…")

    iterations = 0
    try:
        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            sleep_fn(interval)
            curr = snapshot(paths_fn())
            if changed(baseline, curr):
                _log("change detected → re-rendering")
                _render()
                baseline = curr
    except KeyboardInterrupt:
        return 0
    return 0
