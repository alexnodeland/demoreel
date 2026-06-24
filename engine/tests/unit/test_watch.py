"""Unit tests for ``demoreel.watch`` — path collection + the pure polling loop.

All pure: ``collect_watch_paths`` runs against a duck-typed SimpleNamespace spec, and
``watch_loop`` is driven with injected ``sleep_fn`` / ``render_fn`` / ``paths_fn`` so there is
no real sleeping and no real rendering.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from demoreel.watch import changed, collect_watch_paths, snapshot, watch_loop

# --------------------------------------------------------------------------- helpers


def _touch(tmp_path: Path, name: str, body: str = "x") -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


def _spec(**kw: object) -> SimpleNamespace:
    """Build a duck-typed spec; sections default to empty namespaces so getattr works."""
    audio = SimpleNamespace(music=kw.get("music"))
    brand = SimpleNamespace(logo=kw.get("logo"), brand_kit=kw.get("brand_kit"))
    prelude = SimpleNamespace(
        inject_css=kw.get("inject_css"),
        inject_js=kw.get("inject_js"),
    )
    return SimpleNamespace(audio=audio, brand=brand, prelude=prelude, url=kw.get("url"))


# ------------------------------------------------------------------- collect_watch_paths


def test_collect_includes_spec_file(tmp_path: Path):
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec())
    assert spec_file.resolve() in paths


def test_collect_file_url_resolved(tmp_path: Path):
    page = _touch(tmp_path, "page.html")
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec(url=f"file://{page}"))
    assert page.resolve() in paths


def test_collect_http_url_skipped(tmp_path: Path):
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec(url="https://example.com/app"))
    assert paths == [spec_file.resolve()]


def test_collect_music_and_logo_present(tmp_path: Path):
    music = _touch(tmp_path, "track.mp3")
    logo = _touch(tmp_path, "logo.png")
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec(music=str(music), logo=str(logo)))
    assert music.resolve() in paths
    assert logo.resolve() in paths


def test_collect_none_values_dropped(tmp_path: Path):
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec(music=None, logo=None))
    assert paths == [spec_file.resolve()]


def test_collect_missing_file_dropped(tmp_path: Path):
    spec_file = _touch(tmp_path, "demo.yaml")
    ghost = tmp_path / "gone.mp3"
    paths = collect_watch_paths(spec_file, _spec(music=str(ghost)))
    assert ghost.resolve() not in paths


def test_collect_brand_kit_path(tmp_path: Path):
    kit = _touch(tmp_path, "kit.json")
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec(brand_kit=str(kit)))
    assert kit.resolve() in paths


def test_collect_inject_css_js(tmp_path: Path):
    css = _touch(tmp_path, "inject.css")
    js = _touch(tmp_path, "inject.js")
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec(inject_css=str(css), inject_js=str(js)))
    assert css.resolve() in paths
    assert js.resolve() in paths


def test_collect_dedupes(tmp_path: Path):
    shared = _touch(tmp_path, "shared.png")
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(spec_file, _spec(logo=str(shared), brand_kit=str(shared)))
    assert paths.count(shared.resolve()) == 1


def test_collect_handles_missing_sections(tmp_path: Path):
    spec_file = _touch(tmp_path, "demo.yaml")
    # bare object: no audio/brand/prelude/url attributes at all
    paths = collect_watch_paths(spec_file, object())
    assert paths == [spec_file.resolve()]


def test_collect_returns_absolute(tmp_path: Path):
    spec_file = _touch(tmp_path, "demo.yaml")
    paths = collect_watch_paths(str(spec_file), _spec())
    assert all(p.is_absolute() for p in paths)


# --------------------------------------------------------------------- snapshot / changed


def test_snapshot_maps_mtimes(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    snap = snapshot([a])
    assert snap[str(a)] == os.path.getmtime(a)


def test_snapshot_skips_vanished(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    ghost = tmp_path / "ghost.txt"
    snap = snapshot([a, ghost])
    assert str(a) in snap
    assert str(ghost) not in snap


def test_changed_false_when_identical(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    snap = snapshot([a])
    assert changed(snap, snapshot([a])) is False


def test_changed_true_on_mtime_bump(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    prev = snapshot([a])
    new_mtime = prev[str(a)] + 100
    os.utime(a, (new_mtime, new_mtime))
    assert changed(prev, snapshot([a])) is True


def test_changed_true_on_added_key(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    b = _touch(tmp_path, "b.txt")
    assert changed(snapshot([a]), snapshot([a, b])) is True


def test_changed_true_on_removed_key(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    b = _touch(tmp_path, "b.txt")
    assert changed(snapshot([a, b]), snapshot([a])) is True


# ------------------------------------------------------------------------- watch_loop


class _FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, interval: float) -> None:
        self.calls.append(interval)


def test_loop_initial_render_only(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    renders = []
    sleep = _FakeSleep()
    watch_loop(
        lambda: [a],
        lambda: renders.append(1),
        sleep_fn=sleep,
        max_iterations=3,
    )
    # no change across ticks → only the initial render
    assert len(renders) == 1
    assert sleep.calls == [1.0, 1.0, 1.0]


def test_loop_rerenders_on_change(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    renders: list[int] = []
    sleep = _FakeSleep()

    def render() -> None:
        renders.append(1)

    def sleeper(_interval: float) -> None:
        # mutate mtime on the second tick to trigger exactly one re-render
        sleep.calls.append(_interval)
        if len(sleep.calls) == 1:
            m = os.path.getmtime(a) + 50
            os.utime(a, (m, m))

    watch_loop(lambda: [a], render, sleep_fn=sleeper, max_iterations=3)
    # initial render + one change-triggered render
    assert len(renders) == 2


def test_loop_max_iterations_caps(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    sleep = _FakeSleep()
    watch_loop(lambda: [a], lambda: None, sleep_fn=sleep, max_iterations=5)
    assert len(sleep.calls) == 5


def test_loop_render_failure_keeps_watching(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    logs: list[str] = []
    attempts: list[int] = []

    def render() -> None:
        attempts.append(1)
        raise RuntimeError("boom")

    def sleeper(_interval: float) -> None:
        m = os.path.getmtime(a) + len(attempts) * 10
        os.utime(a, (m, m))

    rc = watch_loop(
        lambda: [a],
        render,
        sleep_fn=sleeper,
        max_iterations=2,
        log=logs.append,
    )
    assert rc == 0
    # initial + 2 change-triggered attempts, all failed but loop survived
    assert len(attempts) == 3
    assert any("render failed: boom" in line for line in logs)


def test_loop_keyboard_interrupt_returns_zero():
    def sleeper(_interval: float) -> None:
        raise KeyboardInterrupt

    rc = watch_loop(
        lambda: [],
        lambda: None,
        sleep_fn=sleeper,
        max_iterations=None,
    )
    assert rc == 0


def test_loop_logs_watch_count(tmp_path: Path):
    a = _touch(tmp_path, "a.txt")
    logs: list[str] = []
    watch_loop(
        lambda: [a],
        lambda: None,
        sleep_fn=_FakeSleep(),
        max_iterations=1,
        log=logs.append,
    )
    assert any("watching 1 files" in line for line in logs)


@pytest.mark.parametrize("interval", [0.5, 2.0])
def test_loop_passes_interval_to_sleep(tmp_path: Path, interval: float):
    a = _touch(tmp_path, "a.txt")
    sleep = _FakeSleep()
    watch_loop(lambda: [a], lambda: None, sleep_fn=sleep, interval=interval, max_iterations=2)
    assert sleep.calls == [interval, interval]
