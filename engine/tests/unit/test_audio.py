"""Unit tests for demoreel.audio — numpy-only paths (wav io, normalize, sfx synth, duck env).

These avoid moviepy entirely: build_content_audio / _music_clip / AudioArrayClip are not
touched. We exercise _read_wav / _write_wav / normalize_wav / synth_click / synth_key
directly, and probe the closed-over ducking envelope through a tiny fake clip that captures
the transform callback _duck installs.
"""

from __future__ import annotations

import numpy as np
import pytest

from demoreel import audio

_RATE = 44100


# --------------------------------------------------------------------------- _read_wav


def test_read_wav_16bit_mono_roundtrips_to_unit_floats(wav_factory):
    path = wav_factory(seconds=0.1, rate=_RATE, freq=220.0, sampwidth=2, channels=1)
    data, rate, ch = audio._read_wav(str(path))

    assert rate == _RATE
    assert ch == 1
    assert data.ndim == 1
    assert data.dtype == np.float32
    # factory writes a sine at int(v*30000) over int16; everything stays inside [-1, 1].
    assert float(data.max()) <= 1.0
    assert float(data.min()) >= -1.0
    # A real tone has meaningful amplitude (peak ~ 30000/32767 ~ 0.915), not silence.
    assert float(np.max(np.abs(data))) == pytest.approx(30000 / 32767, abs=1e-3)
    # Sine centered at zero -> near-zero DC offset.
    assert float(data.mean()) == pytest.approx(0.0, abs=1e-2)


def test_read_wav_8bit_unsigned_silence_decodes_near_zero_mean(wav_factory):
    """The bug fix: 8-bit WAV is UNSIGNED (midpoint 128). A constant-128 file is silence and
    must read as ~0.0, not a huge DC offset / inverted waveform."""
    # freq=0 -> sin term is 0 for every sample -> every byte is exactly 128 (silence).
    path = wav_factory(seconds=0.1, rate=_RATE, freq=0.0, sampwidth=1, channels=1)
    data, rate, ch = audio._read_wav(str(path))

    assert rate == _RATE
    assert ch == 1
    assert data.dtype == np.float32
    # Centered & scaled: (128 - 128) / 128 == 0.0 for every sample.
    assert float(data.mean()) == pytest.approx(0.0, abs=1e-6)
    assert float(np.max(np.abs(data))) == pytest.approx(0.0, abs=1e-6)
    # Guard against the old signed-int8 misread, which would have produced a ~-1.0 DC offset
    # (128 reinterpreted as int8 == -128 -> -128/128 == -1.0).
    assert float(data.mean()) > -0.5


def test_read_wav_8bit_unsigned_tone_stays_in_unit_range(wav_factory):
    path = wav_factory(seconds=0.05, rate=_RATE, freq=220.0, sampwidth=1, channels=1)
    data, _, _ = audio._read_wav(str(path))

    # Tone written as int(v*120)+128 -> bytes span ~[8, 248] -> floats span ~[-0.94, 0.94].
    assert float(data.max()) <= 1.0
    assert float(data.min()) >= -1.0
    assert float(np.max(np.abs(data))) > 0.5  # a real tone, not flattened
    assert float(data.mean()) == pytest.approx(0.0, abs=5e-2)


def test_read_wav_stereo_downmixes_to_mono(wav_factory):
    seconds, rate = 0.05, _RATE
    n = int(seconds * rate)
    path = wav_factory(seconds=seconds, rate=rate, freq=220.0, sampwidth=2, channels=2)
    data, out_rate, ch = audio._read_wav(str(path))

    assert ch == 2
    assert out_rate == rate
    # Downmixed to a single mono channel of length n (one value per frame).
    assert data.ndim == 1
    assert data.size == n


# --------------------------------------------------------------------------- _write_wav


def test_write_then_read_roundtrips_within_tolerance(tmp_path):
    rate = _RATE
    t = np.linspace(0, 0.05, int(rate * 0.05), endpoint=False)
    original = (0.5 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
    path = tmp_path / "rt.wav"

    audio._write_wav(str(path), original, rate)
    back, out_rate, ch = audio._read_wav(str(path))

    assert out_rate == rate
    assert ch == 1
    assert back.size == original.size
    # 16-bit quantization error is ~1/32767; allow a small absolute tolerance.
    assert back == pytest.approx(original, abs=1e-3)


def test_write_wav_clips_out_of_range_values(tmp_path):
    rate = _RATE
    loud = np.array([5.0, -5.0, 0.0, 2.0, -3.0, 0.25], dtype=np.float32)
    path = tmp_path / "clip.wav"

    audio._write_wav(str(path), loud, rate)
    back, _, _ = audio._read_wav(str(path))

    assert float(back.max()) <= 1.0
    assert float(back.min()) >= -1.0
    # +5.0 clipped to +1.0 (stored as 32767/32767 == 1.0).
    assert back[0] == pytest.approx(1.0, abs=1e-3)
    # -5.0 clipped to -1.0; int16 floor stores -32767/32767 == -1.0 (write uses *32767).
    assert back[1] == pytest.approx(-1.0, abs=1e-3)
    assert back[2] == pytest.approx(0.0, abs=1e-3)
    assert back[3] == pytest.approx(1.0, abs=1e-3)  # 2.0 -> 1.0
    assert back[4] == pytest.approx(-1.0, abs=1e-3)  # -3.0 -> -1.0
    assert back[5] == pytest.approx(0.25, abs=1e-3)  # in-range passes through


# --------------------------------------------------------------------------- normalize_wav


def test_normalize_wav_brings_quiet_sine_to_target_peak(tmp_path):
    rate = _RATE
    t = np.linspace(0, 0.2, int(rate * 0.2), endpoint=False)
    quiet = (0.05 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)  # ~ -26 dBFS
    path = tmp_path / "quiet.wav"
    audio._write_wav(str(path), quiet, rate)

    audio.normalize_wav(str(path), target_dbfs=-2.5, edge_ms=6.0)

    data, _, _ = audio._read_wav(str(path))
    target_peak = 10 ** (-2.5 / 20.0)
    # Peak after normalize lands on target. Edge fades zero the very ends but the body of a
    # 0.2s tone still reaches the normalized peak, so global max == target peak.
    assert float(np.max(np.abs(data))) == pytest.approx(target_peak, abs=2e-3)


def test_normalize_wav_applies_edge_fades(tmp_path):
    rate = _RATE
    # Constant non-zero signal so any near-zero endpoints come purely from the edge ramp.
    const = np.full(int(rate * 0.2), 0.4, dtype=np.float32)
    path = tmp_path / "const.wav"
    audio._write_wav(str(path), const, rate)

    audio.normalize_wav(str(path), target_dbfs=-2.5, edge_ms=6.0)

    data, _, _ = audio._read_wav(str(path))
    # First and last samples are ramped from 0 -> near zero.
    assert abs(float(data[0])) < 1e-2
    assert abs(float(data[-1])) < 1e-2
    # The interior is well away from zero (peak-normalized constant).
    mid = data.size // 2
    assert abs(float(data[mid])) > 0.1


def test_normalize_wav_empty_file_is_noop(tmp_path):
    rate = _RATE
    path = tmp_path / "empty.wav"
    audio._write_wav(str(path), np.array([], dtype=np.float32), rate)

    # Must not raise on a zero-length clip.
    audio.normalize_wav(str(path))

    data, _, _ = audio._read_wav(str(path))
    assert data.size == 0


def test_normalize_wav_all_zero_file_is_noop(tmp_path):
    rate = _RATE
    silence = np.zeros(int(rate * 0.1), dtype=np.float32)
    path = tmp_path / "silence.wav"
    audio._write_wav(str(path), silence, rate)

    # peak <= 1e-5 -> no scaling, no crash.
    audio.normalize_wav(str(path))

    data, _, _ = audio._read_wav(str(path))
    assert data.size == silence.size
    assert float(np.max(np.abs(data))) == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- sfx synth


def test_synth_click_shape_rate_and_amplitude():
    vol = 0.5
    arr = audio.synth_click(vol)

    expected_len = int(_RATE * 0.06)
    assert arr.shape == (expected_len, 2)
    assert arr.dtype == np.float32
    # Stereo == two identical channels.
    assert np.array_equal(arr[:, 0], arr[:, 1])

    # Amplitude scales linearly with the volume arg. tone*env peaks at sample 0
    # (env(0)==1, tone(0)==0... actually tone starts at 0). Compare against a known peak.
    half = audio.synth_click(vol)
    full = audio.synth_click(vol * 2)
    assert float(np.max(np.abs(full))) == pytest.approx(2 * float(np.max(np.abs(half))), rel=1e-5)
    # At zero volume the click is silent.
    assert float(np.max(np.abs(audio.synth_click(0.0)))) == pytest.approx(0.0, abs=1e-7)


def test_synth_key_shape_rate_and_amplitude():
    vol = 0.5
    arr = audio.synth_key(vol)

    expected_len = int(_RATE * 0.035)
    assert arr.shape == (expected_len, 2)
    assert arr.dtype == np.float32
    assert np.array_equal(arr[:, 0], arr[:, 1])

    # synth_key folds in an extra *0.7 factor and is still linear in volume.
    full = audio.synth_key(vol * 2)
    assert float(np.max(np.abs(full))) == pytest.approx(2 * float(np.max(np.abs(arr))), rel=1e-5)
    assert float(np.max(np.abs(audio.synth_key(0.0)))) == pytest.approx(0.0, abs=1e-7)


def test_synth_click_louder_than_key_for_same_volume():
    # Click has higher peak amplitude than the soft key tick (0.6+0.4 envelope vs *0.7).
    v = 1.0
    assert float(np.max(np.abs(audio.synth_click(v)))) > float(np.max(np.abs(audio.synth_key(v))))


# --------------------------------------------------------------------------- _duck env


class _FakeMusic:
    """Captures the transform callback _duck installs so we can probe the gain envelope.

    moviepy clips expose .transform(make) -> new clip; make(get_frame, t) returns the frame
    scaled by the ducking envelope. We don't have moviepy here, so we record `make` and
    invoke it ourselves with a constant unit frame to read the envelope at any time(s).
    """

    def __init__(self):
        self.make = None

    def transform(self, make):
        self.make = make
        return self  # _duck returns this; we just need `make`

    def gain_at(self, times):
        """Envelope gain at the given time(s): make() applied to a constant 1.0 frame."""
        t = np.asarray(times, dtype=np.float64)

        def get_frame(_t):
            # 1-D mono frame of ones, one per requested time.
            return np.ones_like(np.asarray(_t, dtype=np.float64))

        return self.make(get_frame, t)


def test_duck_drops_gain_inside_vo_interval_and_holds_outside():
    fake = _FakeMusic()
    intervals = [(2.0, 5.0)]
    duck_factor = 0.32

    returned = audio._duck(fake, intervals, duck_factor=duck_factor, ramp=0.18)
    assert returned is fake  # transform installed, clip returned
    assert fake.make is not None

    # Deep inside the VO interval the gain collapses toward duck_factor.
    inside = fake.gain_at([3.5])
    assert float(inside[0]) == pytest.approx(duck_factor, abs=1e-6)

    # Well outside (before and after) the interval the gain holds at ~1.0.
    outside = fake.gain_at([0.0, 1.0, 8.0, 20.0])
    assert np.allclose(outside, 1.0, atol=1e-6)


def test_duck_ramps_between_full_and_ducked():
    fake = _FakeMusic()
    intervals = [(2.0, 5.0)]
    audio._duck(fake, intervals, duck_factor=0.32, ramp=0.18)

    # At the ramp midpoint entering the interval (a - ramp/2 == 1.91), gain sits strictly
    # between the ducked floor and full volume.
    edge = fake.gain_at([1.91])
    assert 0.32 < float(edge[0]) < 1.0


def test_duck_multiple_intervals_take_the_minimum_gain():
    fake = _FakeMusic()
    intervals = [(1.0, 2.0), (4.0, 5.0)]
    duck_factor = 0.4
    audio._duck(fake, intervals, duck_factor=duck_factor, ramp=0.1)

    # Inside either interval -> ducked; in the gap between them -> full.
    g = fake.gain_at([1.5, 3.0, 4.5])
    assert float(g[0]) == pytest.approx(duck_factor, abs=1e-6)  # inside first
    assert float(g[1]) == pytest.approx(1.0, abs=1e-6)  # in the gap
    assert float(g[2]) == pytest.approx(duck_factor, abs=1e-6)  # inside second
