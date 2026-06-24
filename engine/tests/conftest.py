"""Shared pytest fixtures.

The whole pipeline is built so that every heavy dependency (Playwright, moviepy, cv2,
piper, faster-whisper, openai) is lazy-imported inside functions — so the unit suite below
runs with only the always-on deps (pydantic, numpy, PIL, pyyaml) and needs no browser,
no ffmpeg, and no network. Tests that DO need those are marked `browser` / `slow` and are
excluded from the default `pytest` run (see pyproject `addopts`).
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def page_url() -> str:
    """A file:// URL to the static fixture page (no network / live app needed)."""
    return (FIXTURES / "page.html").resolve().as_uri()


@pytest.fixture
def make_spec():
    """Factory: build a valid DemoSpec from kwargs without hand-rolling the nested model."""
    from demoreel.spec import DemoSpec

    def _make(**kw):
        base: dict = {"url": "https://example.com", "scenes": [{"goto": "/"}]}
        base.update(kw)
        return DemoSpec.model_validate(base)

    return _make


@pytest.fixture
def write_spec(tmp_path):
    """Write a spec dict to a YAML file and return its path (exercises load_spec)."""
    import yaml

    def _write(data: dict, name: str = "demo.yaml") -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(data))
        return path

    return _write


@pytest.fixture
def wav_factory(tmp_path):
    """Write a real PCM WAV (sine tone) and return its path.

    Supports 1/2/4-byte sample widths and mono/stereo so audio round-trip tests can cover
    the 8-bit-unsigned path specifically.
    """

    def _make(
        seconds: float = 0.5,
        rate: int = 44100,
        freq: float = 220.0,
        sampwidth: int = 2,
        channels: int = 1,
        name: str = "tone.wav",
    ) -> Path:
        path = tmp_path / name
        n = int(seconds * rate)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(sampwidth)
            w.setframerate(rate)
            frames = bytearray()
            for i in range(n):
                v = math.sin(2 * math.pi * freq * i / rate)
                for _ in range(channels):
                    if sampwidth == 1:  # WAV 8-bit is unsigned, midpoint 128
                        frames += struct.pack("B", max(0, min(255, int(v * 120) + 128)))
                    elif sampwidth == 4:
                        frames += struct.pack("<i", int(v * 2_000_000_000))
                    else:
                        frames += struct.pack("<h", int(v * 30000))
            w.writeframes(bytes(frames))
        return path

    return _make
