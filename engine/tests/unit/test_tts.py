"""Unit tests for ``demoreel.tts``.

No real TTS engines or network are touched: piper/kokoro/openai/elevenlabs are never
imported, voice URLs are derived purely from string parsing, and synthesis goes through
fake providers injected into the ``PROVIDERS`` registry. The ``_AUDIO_CACHE`` module global
is monkeypatched to a tmp dir so the user's real cache is never read or written.
"""

from __future__ import annotations

import wave

import numpy as np
import pytest

from demoreel import tts
from demoreel.spec import VoiceConfig
from demoreel.tts import (
    PROVIDERS,
    TTSError,
    TTSProvider,
    _cache_key,
    _normalize_text,
    _pcm_to_wav,
    _piper_voice_urls,
    _samples_to_wav,
    _synthesize_with_fallback,
    _write_silence,
    provider_names,
    synthesize,
    wav_duration,
)

# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def restore_providers():
    """Snapshot PROVIDERS and restore it after the test, even if it mutated entries."""
    snapshot = dict(PROVIDERS)
    try:
        yield PROVIDERS
    finally:
        PROVIDERS.clear()
        PROVIDERS.update(snapshot)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect the content-addressed audio cache into a throwaway tmp dir."""
    d = tmp_path / "tts-cache"
    monkeypatch.setattr(tts, "_AUDIO_CACHE", d)
    return d


def _tiny_wav(path, *, rate: int = 44100, frames: int = 100) -> None:
    """Write a minimal valid 16-bit mono WAV."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * frames)


class _CountingProvider(TTSProvider):
    """A fake provider that records calls and writes a tiny readable WAV."""

    def __init__(self, name: str, *, frames: int = 100):
        self.name = name
        self.calls = 0
        self.frames = frames

    def available(self) -> bool:
        return True

    def synthesize(self, text, out_wav, voice) -> None:
        self.calls += 1
        _tiny_wav(out_wav, frames=self.frames)


class _FailingProvider(TTSProvider):
    """A fake provider that always raises TTSError."""

    def __init__(self, name: str):
        self.name = name
        self.calls = 0

    def available(self) -> bool:
        return False

    def synthesize(self, text, out_wav, voice) -> None:
        self.calls += 1
        raise TTSError(f"{self.name} intentionally unavailable")


# --------------------------------------------------------------------- _normalize_text


def test_normalize_collapses_whitespace():
    assert _normalize_text("hello   world\n\tagain") == "hello world again."


def test_normalize_appends_period_when_no_terminal_punct():
    assert _normalize_text("hello world") == "hello world."


@pytest.mark.parametrize("ending", [".", "!", "?", ":", ";", ",", "—", "-"])
def test_normalize_keeps_existing_terminal_punctuation(ending):
    text = f"already done{ending}"
    assert _normalize_text(text) == text


def test_normalize_empty_stays_empty():
    assert _normalize_text("") == ""
    # whitespace-only collapses to empty and stays empty (no spurious period)
    assert _normalize_text("   \n\t ") == ""


# -------------------------------------------------------------------- _piper_voice_urls


def test_piper_voice_urls_exact():
    onnx, cfg = _piper_voice_urls("en_US-lessac-medium")
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
    expected_stem = f"{base}/en/en_US/lessac/medium/en_US-lessac-medium"
    assert onnx == f"{expected_stem}.onnx"
    assert cfg == f"{expected_stem}.onnx.json"


def test_piper_voice_urls_uses_module_hf_base():
    # The URL prefix must track the module constant, not a hard-coded literal.
    onnx, _cfg = _piper_voice_urls("en_US-lessac-medium")
    assert onnx.startswith(tts._HF_BASE + "/")


@pytest.mark.parametrize("bad", ["lessac", "en_US-lessac", "a-b-c-d", "noseps"])
def test_piper_voice_urls_bad_name_raises(bad):
    with pytest.raises(TTSError):
        _piper_voice_urls(bad)


# ------------------------------------------------------ wav round-trips & duration


def test_wav_duration_known_length(wav_factory):
    rate = 16000
    seconds = 0.5
    path = wav_factory(seconds=seconds, rate=rate)
    n = int(seconds * rate)
    # duration == n / rate, accurate to within one frame
    assert wav_duration(path) == pytest.approx(n / rate, abs=1.0 / rate)


def test_pcm_to_wav_roundtrip(tmp_path):
    rate = 8000
    n = 1234
    pcm = b"\x00\x01" * n  # n 16-bit frames
    out = tmp_path / "pcm.wav"
    _pcm_to_wav(pcm, out, rate=rate)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == rate
        assert w.getnframes() == n
    assert wav_duration(out) == pytest.approx(n / rate, abs=1.0 / rate)


def test_pcm_to_wav_stereo_frame_count(tmp_path):
    rate = 8000
    n_frames = 500
    pcm = b"\x00\x01\x02\x03" * n_frames  # 4 bytes/frame at 2ch * 16-bit
    out = tmp_path / "stereo.wav"
    _pcm_to_wav(pcm, out, rate=rate, channels=2)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 2
        assert w.getnframes() == n_frames
    assert wav_duration(out) == pytest.approx(n_frames / rate, abs=1.0 / rate)


def test_write_silence_duration(tmp_path):
    out = tmp_path / "sil.wav"
    _write_silence(out, 0.3)
    assert wav_duration(out) == pytest.approx(0.3, abs=0.01)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 44100
        # silence is all-zero PCM
        assert set(w.readframes(w.getnframes())) <= {0}


def test_write_silence_zero_seconds(tmp_path):
    out = tmp_path / "sil0.wav"
    _write_silence(out, 0.0)
    assert wav_duration(out) == pytest.approx(0.0, abs=1e-9)


def test_samples_to_wav_from_numpy_float(tmp_path):
    rate = 22050
    n = 2000
    t = np.linspace(0, 1, n, endpoint=False, dtype=np.float32)
    samples = 0.5 * np.sin(2 * np.pi * 220.0 * t)
    out = tmp_path / "samples.wav"
    _samples_to_wav(samples, out, rate)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == rate
        assert w.getnframes() == n
    assert wav_duration(out) == pytest.approx(n / rate, abs=1.0 / rate)


def test_samples_to_wav_clips_out_of_range(tmp_path):
    # Values outside [-1, 1] must be clipped, not overflow.
    samples = np.array([5.0, -5.0, 0.0, 1.0, -1.0], dtype=np.float32)
    out = tmp_path / "clip.wav"
    _samples_to_wav(samples, out, 8000)
    with wave.open(str(out), "rb") as w:
        raw = w.readframes(w.getnframes())
    vals = np.frombuffer(raw, dtype="<i2")
    assert vals[0] == 32767  # +5 clipped to +1.0 -> 32767
    assert vals[1] == -32767  # -5 clipped to -1.0 -> -32767
    assert vals[2] == 0


# --------------------------------------------------------------------------- _cache_key


def _voice(**kw) -> VoiceConfig:
    base = {"engine": "piper"}
    base.update(kw)
    return VoiceConfig(**base)


def test_cache_key_deterministic():
    v1 = _voice(rate=1.0)
    v2 = _voice(rate=1.0)
    assert _cache_key("hello there.", v1) == _cache_key("hello there.", v2)
    # 32 hex chars (sha256 truncated)
    assert len(_cache_key("hello there.", v1)) == 32


def test_cache_key_changes_with_text():
    v = _voice()
    assert _cache_key("one.", v) != _cache_key("two.", v)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "af_sarah"),
        ("tts_model", "gpt-4o-mini-tts"),
        ("base_url", "http://localhost:9999"),
        ("rate", 1.5),
    ],
)
def test_cache_key_changes_with_voice_field(field, value):
    base = _voice()
    changed = _voice(**{field: value})
    assert _cache_key("same text.", base) != _cache_key("same text.", changed)


def test_cache_key_changes_with_engine(restore_providers):
    # registering a fake engine so VoiceConfig validation accepts it
    PROVIDERS["fakeeng"] = _CountingProvider("fakeeng")
    base = _voice(engine="piper")
    other = _voice(engine="fakeeng")
    assert _cache_key("same text.", base) != _cache_key("same text.", other)


def test_cache_key_rate_rounded_to_4_places():
    # rate is rounded to 4 decimals in the key, so a 5th-decimal difference is identical.
    v1 = _voice(rate=1.00001)
    v2 = _voice(rate=1.00002)
    assert _cache_key("text.", v1) == _cache_key("text.", v2)


# ----------------------------------------------------------------------- synthesize


def test_synthesize_empty_text_writes_silence_no_provider(cache_dir, restore_providers):
    prov = _CountingProvider("piper")
    PROVIDERS["piper"] = prov
    v = _voice(engine="piper")
    out = cache_dir.parent / "empty.wav"
    dur = synthesize("", out, v)
    assert prov.calls == 0
    assert dur == pytest.approx(0.3, abs=0.02)
    assert out.exists()


def test_synthesize_whitespace_only_treated_as_empty(cache_dir, restore_providers):
    prov = _CountingProvider("piper")
    PROVIDERS["piper"] = prov
    v = _voice(engine="piper")
    out = cache_dir.parent / "ws.wav"
    dur = synthesize("   \n  ", out, v)
    assert prov.calls == 0
    assert dur == pytest.approx(0.3, abs=0.02)


def test_synthesize_caches_then_hits(cache_dir, restore_providers, tmp_path):
    prov = _CountingProvider("piper", frames=321)
    PROVIDERS["piper"] = prov
    v = _voice(engine="piper")

    out1 = tmp_path / "a.wav"
    dur1 = synthesize("hello world", out1, v)
    assert prov.calls == 1
    assert out1.exists()
    assert dur1 > 0

    # the cache file landed under the redirected _AUDIO_CACHE
    cached_files = list(cache_dir.glob("*.wav"))
    assert len(cached_files) == 1

    # second identical call is a cache hit: no new synth, output reproduced
    out2 = tmp_path / "b.wav"
    dur2 = synthesize("hello world", out2, v)
    assert prov.calls == 1  # still 1 — served from cache
    assert out2.exists()
    assert dur2 == pytest.approx(dur1)
    assert out2.read_bytes() == out1.read_bytes()


def test_synthesize_different_text_triggers_new_synth(cache_dir, restore_providers, tmp_path):
    prov = _CountingProvider("piper")
    PROVIDERS["piper"] = prov
    v = _voice(engine="piper")
    synthesize("first text", tmp_path / "1.wav", v)
    synthesize("second text", tmp_path / "2.wav", v)
    assert prov.calls == 2


# --------------------------------------------------------- _synthesize_with_fallback


def test_fallback_all_fail_returns_none_writes_silence_logs(cache_dir, restore_providers, tmp_path):
    fail = _FailingProvider("failer")
    PROVIDERS["failer"] = fail
    v = _voice(engine="failer", fallback=[])  # empty fallback

    logs: list[str] = []
    out = tmp_path / "fb.wav"
    used = _synthesize_with_fallback("a couple of words here", out, v, logs.append)

    assert used is None
    assert fail.calls == 1
    assert out.exists()
    # degraded to silence sized to the text (>= 1.0s floor)
    assert wav_duration(out) >= 1.0
    assert any("using silence" in m for m in logs)


def test_fallback_uses_working_engine_and_logs(cache_dir, restore_providers, tmp_path):
    fail = _FailingProvider("failer")
    ok = _CountingProvider("backup")
    PROVIDERS["failer"] = fail
    PROVIDERS["backup"] = ok
    v = _voice(engine="failer", fallback=["backup"])

    logs: list[str] = []
    out = tmp_path / "fb2.wav"
    used = _synthesize_with_fallback("hello", out, v, logs.append)

    assert used == "backup"
    assert fail.calls == 1
    assert ok.calls == 1
    assert out.exists()
    assert any("fallback 'backup'" in m for m in logs)


def test_fallback_unknown_engine_in_chain_is_skipped(cache_dir, restore_providers, tmp_path):
    ok = _CountingProvider("realok")
    PROVIDERS["realok"] = ok
    # construct via model_validate would reject an unknown engine; build the chain by hand
    # using a known engine then patching .fallback is not possible (frozen-ish), so register
    # a placeholder, build the voice, then remove the placeholder to simulate "unknown".
    PROVIDERS["ghost"] = _FailingProvider("ghost")
    v = _voice(engine="ghost", fallback=["realok"])
    del PROVIDERS["ghost"]  # now engine "ghost" is unknown at synth time

    logs: list[str] = []
    out = tmp_path / "fb3.wav"
    used = _synthesize_with_fallback("hi", out, v, logs.append)

    assert used == "realok"
    assert ok.calls == 1


def test_synthesize_with_fallback_no_log_callable(cache_dir, restore_providers, tmp_path):
    # log=None must not raise (internal no-op logger).
    fail = _FailingProvider("failer")
    PROVIDERS["failer"] = fail
    v = _voice(engine="failer", fallback=[])
    out = tmp_path / "nolog.wav"
    used = _synthesize_with_fallback("words", out, v, None)
    assert used is None
    assert out.exists()


def test_synthesize_only_caches_preferred_engine(cache_dir, restore_providers, tmp_path):
    # When the preferred engine fails and a fallback succeeds, nothing is cached
    # (only the preferred engine's output is cached).
    fail = _FailingProvider("failer")
    ok = _CountingProvider("backup")
    PROVIDERS["failer"] = fail
    PROVIDERS["backup"] = ok
    v = _voice(engine="failer", fallback=["backup"])

    synthesize("via fallback", tmp_path / "out.wav", v)
    assert ok.calls == 1
    # cache dir holds no entry because the fallback engine ran, not the preferred one
    assert list(cache_dir.glob("*.wav")) == []

    # a second call re-runs the fallback (no cache hit)
    synthesize("via fallback", tmp_path / "out2.wav", v)
    assert ok.calls == 2


# ---------------------------------------------------------------------- registry


def test_provider_names_lists_six_engines():
    names = provider_names()
    assert names == ["piper", "kokoro", "say", "espeak", "openai", "elevenlabs"]
    assert len(names) == 6


def test_providers_values_are_tts_provider_instances():
    for name, prov in PROVIDERS.items():
        assert isinstance(prov, TTSProvider)
        assert prov.name == name
        assert callable(prov.available)
        assert callable(prov.synthesize)
        # available() returns a bool without raising / network
        assert isinstance(prov.available(), bool)


def test_provider_base_class_synthesize_not_implemented(tmp_path):
    base = TTSProvider()
    assert base.available() is True
    with pytest.raises(NotImplementedError):
        base.synthesize("x", tmp_path / "x.wav", _voice())
