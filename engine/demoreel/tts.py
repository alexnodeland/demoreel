"""Text-to-speech backends.

Every backend produces a mono/stereo PCM **WAV** so compose can read durations with the
stdlib ``wave`` module and mux without an extra decode step. Backends are registered in
``PROVIDERS`` keyed by engine name, so adding one is a single registration — the spec
``voice.engine`` field, the CLI, and ``demoreel doctor`` all read the registry.

Synthesis is content-addressed cached (keyed by engine + voice + rate + text) under the
cache dir, so re-rendering a demo whose narration didn't change is instant and, for cloud
engines, free. A configurable fallback chain (``voice.fallback``) keeps a render alive when
the preferred engine is unavailable; if every engine fails it degrades to silence rather
than aborting the whole render.

Engines:
  - piper     : local OSS neural TTS (default). Auto-downloads voices from HuggingFace.
  - kokoro    : local OSS neural TTS (Apache-2.0), higher quality than piper. Experimental.
  - say       : macOS ``say`` (+ ``afconvert``). Zero install, robotic, fast to iterate.
  - espeak    : espeak-ng — cross-platform robotic fallback (the Linux/Windows ``say``).
  - openai    : cloud TTS (gpt-4o-mini-tts), or any OpenAI-compatible endpoint via base_url.
  - elevenlabs: cloud TTS via REST (PCM). Needs ELEVENLABS_API_KEY, no package. Experimental.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import urllib.request
import wave
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path

from .spec import VoiceConfig

CACHE_DIR = Path(os.environ.get("DEMOREEL_CACHE", Path.home() / ".cache" / "demoreel"))
PIPER_DIR = CACHE_DIR / "piper"
_AUDIO_CACHE = CACHE_DIR / "tts"
DEFAULT_PIPER_VOICE = "en_US-lessac-medium"
DEFAULT_KOKORO_VOICE = "af_sarah"
_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
_NET_TIMEOUT = 60  # seconds — fail a stalled download/request instead of hanging the render


class TTSError(RuntimeError):
    pass


def _normalize_text(text: str) -> str:
    """Collapse whitespace and ensure terminal punctuation.

    Clean, sentence-terminated text gives every TTS engine better prosody and avoids the
    dropped/garbled words you get from stray whitespace or run-on input.
    """
    text = " ".join(text.split())
    if text and text[-1] not in ".!?:;,—-":
        text += "."
    return text


def wav_duration(path: str | Path) -> float:
    with wave.open(str(path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
    return frames / float(rate) if rate else 0.0


# --------------------------------------------------------------------------- top-level


def synthesize(
    text: str,
    out_wav: str | Path,
    voice: VoiceConfig,
    log: Callable[[str], None] | None = None,
) -> float:
    """Render ``text`` to ``out_wav`` and return its duration in seconds.

    Cached by content; falls back across ``voice.fallback`` then to silence so a render is
    never aborted by a single unavailable engine.
    """
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    text = _normalize_text(text or "")
    if not text:
        _write_silence(out_wav, 0.3)
        return wav_duration(out_wav)

    key = _cache_key(text, voice)
    cached = _AUDIO_CACHE / f"{key}.wav"
    if cached.exists():
        shutil.copyfile(cached, out_wav)
        return wav_duration(out_wav)

    used = _synthesize_with_fallback(text, out_wav, voice, log)
    if used == voice.engine:  # only cache the preferred engine's output
        try:
            _AUDIO_CACHE.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out_wav, cached)
        except OSError:
            pass
    return wav_duration(out_wav)


def _cache_key(text: str, voice: VoiceConfig) -> str:
    parts = "\x1f".join(
        str(x)
        for x in (
            voice.engine,
            voice.model,
            voice.tts_model,
            voice.base_url,
            round(voice.rate, 4),
            text,
        )
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:32]


def _synthesize_with_fallback(
    text: str, out_wav: Path, voice: VoiceConfig, log: Callable[[str], None] | None
) -> str | None:
    _log = log or (lambda *_a: None)
    errors: list[str] = []
    for name in [voice.engine, *voice.fallback]:
        prov = PROVIDERS.get(name)
        if prov is None:
            errors.append(f"{name}: unknown engine")
            continue
        try:
            prov.synthesize(text, out_wav, voice)
            if name != voice.engine:
                _log(f"  ⚠ voice '{voice.engine}' unavailable; rendered with fallback '{name}'")
            return name
        except TTSError as exc:
            errors.append(f"{name}: {exc}")
    # last resort: silence sized to the text, so pacing stays sane and the render survives.
    _log("  ⚠ no voice engine produced audio (" + "; ".join(errors) + "); using silence")
    _write_silence(out_wav, max(1.0, len(text.split()) / 2.6))
    return None


# --------------------------------------------------------------------------- piper


def _piper_voice_urls(name: str) -> tuple[str, str]:
    """Derive the HuggingFace download URLs for a piper voice name.

    ``en_US-lessac-medium`` -> ``.../en/en_US/lessac/medium/en_US-lessac-medium.onnx``
    """
    try:
        locale, speaker, quality = name.split("-")
        lang = locale.split("_")[0]
    except ValueError as exc:
        raise TTSError(
            f"cannot parse piper voice name {name!r}; expected '<locale>-<speaker>-<quality>' "
            "(e.g. en_US-lessac-medium) or a path to a .onnx file"
        ) from exc
    stem = f"{_HF_BASE}/{lang}/{locale}/{speaker}/{quality}/{name}"
    return f"{stem}.onnx", f"{stem}.onnx.json"


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=_NET_TIMEOUT) as resp, tmp.open("wb") as f:  # noqa: S310
            shutil.copyfileobj(resp, f)
        tmp.replace(dest)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise TTSError(
            f"failed to download {url}: {exc}. Pass voice.model as a path to a local .onnx "
            "instead, or pick another engine."
        ) from exc


def _ensure_piper_model(model: str) -> Path:
    """Resolve a piper voice to a local .onnx path, downloading if needed."""
    p = Path(model)
    if p.suffix == ".onnx" and p.exists():
        return p
    name = p.name if p.suffix == ".onnx" else model
    name = name[:-5] if name.endswith(".onnx") else name
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    onnx = PIPER_DIR / f"{name}.onnx"
    cfg = PIPER_DIR / f"{name}.onnx.json"
    if onnx.exists() and cfg.exists():
        return onnx
    onnx_url, cfg_url = _piper_voice_urls(name)
    for url, dest in ((onnx_url, onnx), (cfg_url, cfg)):
        if not dest.exists():
            _download(url, dest)
    return onnx


def _piper(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    try:
        from piper import PiperVoice  # type: ignore
    except ImportError as exc:
        raise TTSError(
            "piper is not installed. Install it with `pip install piper-tts` "
            "(or `uv sync --extra piper`), or choose voice.engine: say."
        ) from exc

    model = _ensure_piper_model(voice.model or DEFAULT_PIPER_VOICE)
    pv = PiperVoice.load(str(model))
    length_scale = 1.0 / max(voice.rate, 0.1)  # piper: smaller = faster

    # piper-tts >= 1.3 replaced ``synthesize(text, wav_file)`` with
    # ``synthesize_wav(text, wav_file, syn_config=...)``; the old call against the new build
    # silently writes nothing, leaving the wave header unset ("# channels not specified").
    # Prefer the new API, fall back to the old one.
    syn_config = None
    try:  # length_scale moved into SynthesisConfig on the new API
        try:
            from piper import SynthesisConfig  # type: ignore
        except ImportError:
            from piper.config import SynthesisConfig  # type: ignore
        syn_config = SynthesisConfig(length_scale=length_scale)
    except Exception:  # noqa: BLE001 - older piper has no SynthesisConfig; fine
        syn_config = None

    with wave.open(str(out_wav), "wb") as wf:
        if hasattr(pv, "synthesize_wav"):
            try:
                pv.synthesize_wav(text, wf, syn_config=syn_config)
            except TypeError:
                pv.synthesize_wav(text, wf)
        else:  # legacy piper API (pre-1.3); pyright sees only the new signature
            try:
                pv.synthesize(text, wf, length_scale=length_scale)  # type: ignore[call-arg]
            except TypeError:
                pv.synthesize(text, wf)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- kokoro


def _kokoro(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    try:
        from kokoro_onnx import Kokoro  # type: ignore
    except ImportError as exc:
        raise TTSError("kokoro is not installed. `uv sync --extra kokoro` (kokoro-onnx).") from exc
    model_path = os.environ.get("KOKORO_MODEL_PATH")
    voices_path = os.environ.get("KOKORO_VOICES_PATH")
    try:
        if model_path and voices_path:
            k = Kokoro(model_path, voices_path)
        elif hasattr(Kokoro, "from_pretrained"):
            k = Kokoro.from_pretrained()
        else:
            raise TTSError(
                "kokoro needs model files: set KOKORO_MODEL_PATH and KOKORO_VOICES_PATH "
                "(download kokoro-v*.onnx and voices-*.bin from the kokoro-onnx releases)."
            )
        samples, sample_rate = k.create(
            text,
            voice=voice.model or DEFAULT_KOKORO_VOICE,
            speed=max(voice.rate, 0.1),
            lang="en-us",
        )
    except TTSError:
        raise
    except Exception as exc:
        raise TTSError(f"kokoro synthesis failed: {exc}") from exc
    _samples_to_wav(samples, out_wav, int(sample_rate))


# ----------------------------------------------------------------------- macos say


def _macos_say(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    if not shutil.which("say"):
        raise TTSError("`say` is only available on macOS. Choose voice.engine: piper.")
    aiff = out_wav.with_suffix(".aiff")
    wpm = str(int(175 * max(voice.rate, 0.1)))
    cmd = ["say", "-r", wpm, "-o", str(aiff)]
    if voice.model:
        cmd += ["-v", voice.model]
    cmd += [text]
    subprocess.run(cmd, check=True)
    # Convert AIFF -> 16-bit PCM WAV. Prefer afconvert (built-in); fall back to ffmpeg.
    if shutil.which("afconvert"):
        subprocess.run(
            ["afconvert", str(aiff), str(out_wav), "-f", "WAVE", "-d", "LEI16@44100"],
            check=True,
        )
    else:  # pragma: no cover
        _ffmpeg_to_wav(aiff, out_wav)
    aiff.unlink(missing_ok=True)


# --------------------------------------------------------------------------- espeak


def _espeak(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise TTSError(
            "espeak-ng is not installed (`apt install espeak-ng` / `brew install espeak-ng`)."
        )
    wpm = str(int(175 * max(voice.rate, 0.1)))
    cmd = [exe, "-w", str(out_wav), "-s", wpm]
    if voice.model:
        cmd += ["-v", voice.model]
    cmd += [text]
    subprocess.run(cmd, check=True)


# -------------------------------------------------------------------------- openai


def _openai(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise TTSError(
            "openai is not installed. `pip install openai` (or `uv sync --extra cloud`)."
        ) from exc
    kwargs: dict = {"timeout": _NET_TIMEOUT}
    if voice.base_url:
        kwargs["base_url"] = voice.base_url  # OpenAI-compatible endpoint (LocalAI, Azure, …)
    elif not os.environ.get("OPENAI_API_KEY"):
        raise TTSError("OPENAI_API_KEY is not set.")
    client = OpenAI(**kwargs)
    model = voice.tts_model or "gpt-4o-mini-tts"
    with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice.model or "alloy",
        input=text,
        response_format="wav",
    ) as resp:
        resp.stream_to_file(str(out_wav))


# ---------------------------------------------------------------------- elevenlabs


def _elevenlabs(text: str, out_wav: Path, voice: VoiceConfig) -> None:
    import json

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise TTSError("ELEVENLABS_API_KEY is not set.")
    voice_id = voice.model or "21m00Tcm4TlvDq8ikWAM"  # "Rachel" default
    model_id = voice.tts_model or "eleven_turbo_v2"
    rate = 22050
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_{rate}"
    body = json.dumps({"text": text, "model_id": model_id}).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 - trusted API host
        url,
        data=body,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/pcm",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_NET_TIMEOUT) as resp:  # noqa: S310
            pcm = resp.read()
    except Exception as exc:
        raise TTSError(f"elevenlabs request failed: {exc}") from exc
    _pcm_to_wav(pcm, out_wav, rate=rate)


# --------------------------------------------------------------------------- registry


class TTSProvider:
    """A voice engine. Subclasses set ``name`` and implement ``available`` + ``synthesize``."""

    name: str = ""

    def available(self) -> bool:
        """True if the engine's dependency/binary is present (credentials checked at synth)."""
        return True

    def synthesize(self, text: str, out_wav: Path, voice: VoiceConfig) -> None:
        raise NotImplementedError


class _Piper(TTSProvider):
    name = "piper"

    def available(self) -> bool:
        return find_spec("piper") is not None

    def synthesize(self, text, out_wav, voice):
        _piper(text, out_wav, voice)


class _Kokoro(TTSProvider):
    name = "kokoro"

    def available(self) -> bool:
        return find_spec("kokoro_onnx") is not None

    def synthesize(self, text, out_wav, voice):
        _kokoro(text, out_wav, voice)


class _Say(TTSProvider):
    name = "say"

    def available(self) -> bool:
        return shutil.which("say") is not None

    def synthesize(self, text, out_wav, voice):
        _macos_say(text, out_wav, voice)


class _Espeak(TTSProvider):
    name = "espeak"

    def available(self) -> bool:
        return bool(shutil.which("espeak-ng") or shutil.which("espeak"))

    def synthesize(self, text, out_wav, voice):
        _espeak(text, out_wav, voice)


class _OpenAI(TTSProvider):
    name = "openai"

    def available(self) -> bool:
        return find_spec("openai") is not None

    def synthesize(self, text, out_wav, voice):
        _openai(text, out_wav, voice)


class _ElevenLabs(TTSProvider):
    name = "elevenlabs"

    def available(self) -> bool:
        return True  # stdlib urllib only

    def synthesize(self, text, out_wav, voice):
        _elevenlabs(text, out_wav, voice)


PROVIDERS: dict[str, TTSProvider] = {
    p.name: p for p in (_Piper(), _Kokoro(), _Say(), _Espeak(), _OpenAI(), _ElevenLabs())
}


def provider_names() -> list[str]:
    return list(PROVIDERS)


# -------------------------------------------------------------------------- helpers


def _pcm_to_wav(pcm: bytes, out_wav: Path, rate: int, channels: int = 1) -> None:
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(rate)
        w.writeframes(pcm)


def _samples_to_wav(samples, out_wav: Path, rate: int, channels: int = 1) -> None:
    import numpy as np

    arr = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (arr * 32767.0).astype("<i2").tobytes()
    _pcm_to_wav(pcm, out_wav, rate=rate, channels=channels)


def _write_silence(out_wav: Path, seconds: float, rate: int = 44100) -> None:
    n = max(0, int(seconds * rate))
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)


def _ffmpeg_to_wav(src: Path, out_wav: Path) -> None:  # pragma: no cover
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-i", str(src), str(out_wav)], check=True)


def list_say_voices() -> list[str]:  # pragma: no cover - macOS only
    if not shutil.which("say"):
        return []
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return [line.split()[0] for line in out.splitlines() if line.strip()]
