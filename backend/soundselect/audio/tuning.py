"""How far a recording sits from A = 440 Hz. Older records often drift by a quarter tone or so,
and every note would then fall between two piano keys; measuring it first lets the notes be
judged against the record's own tuning."""

from __future__ import annotations

import numpy as np

from .model import Tuning

N_FFT = 4096
HOP = 2048


def estimate_tuning(samples: np.ndarray, rate: int) -> Tuning:
    """The tuning from the sharpest spectral peaks of mono samples, in cents (-50 to 50)."""
    if len(samples) < N_FFT:
        return Tuning(cents=0.0, confidence=0.0)
    window = np.hanning(N_FFT).astype(np.float32)
    starts = np.arange(0, len(samples) - N_FFT, HOP)
    if len(starts) > 1500:  # about a minute and a half at 44.1 kHz is plenty
        starts = starts[np.linspace(0, len(starts) - 1, 1500).astype(int)]
    frames = np.stack([samples[s : s + N_FFT] for s in starts]) * window
    mag = np.abs(np.fft.rfft(frames, axis=1))
    lo, hi = int(80 * N_FFT / rate), int(2000 * N_FFT / rate)  # where notes have clear peaks
    m = mag[:, lo - 1 : hi + 1]
    centre = m[:, 1:-1]
    is_peak = (centre > m[:, :-2]) & (centre > m[:, 2:])
    # only strong peaks: well above the frame's own median
    is_peak &= centre > 10 * np.median(centre, axis=1, keepdims=True)
    t, k = np.nonzero(is_peak)
    if len(t) < 50:
        return Tuning(cents=0.0, confidence=0.0)
    a, b, c = (np.log(m[t, k] + 1e-9), np.log(m[t, k + 1] + 1e-9), np.log(m[t, k + 2] + 1e-9))
    shift = 0.5 * (a - c) / np.where(np.abs(a - 2 * b + c) < 1e-9, 1e-9, a - 2 * b + c)
    freq = (lo + k + np.clip(shift, -0.5, 0.5)) * rate / N_FFT
    midi = 69 + 12 * np.log2(freq / 440.0)
    deviation = midi - np.round(midi)  # -0.5 to 0.5 semitones
    weight = b  # louder peaks count more
    weight = weight - weight.min() + 1e-3
    angle = 2 * np.pi * deviation
    x, y = np.sum(weight * np.cos(angle)), np.sum(weight * np.sin(angle))
    cents = float(np.arctan2(y, x) / (2 * np.pi) * 100)
    confidence = float(np.hypot(x, y) / np.sum(weight))
    return Tuning(cents=round(cents, 1), confidence=round(confidence, 3))
