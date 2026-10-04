"""Finding the beat and the bar lines of a recording.

Onset strength (how much the sound gets louder, band by band), then the most likely tempo from
its rhythm, then the beat times by dynamic programming: the best chain of beats that fall on
strong onsets and stay close to the tempo, so the beats can follow a band that speeds up or
slows down. This is the classic method (Ellis 2007) that librosa uses too, in numpy only.
Bars: the beat in each group of four (or three) where the bass and drums hit hardest.
"""

from __future__ import annotations

import numpy as np

from .model import Beats

RATE = 22050
N_FFT = 2048
HOP = 512
FPS = RATE / HOP
N_MELS = 64
TIGHTNESS = 100.0


def _mel_filters(n_mels: int = N_MELS, fmin: float = 30.0, fmax: float = 8000.0) -> np.ndarray:
    def hz_to_mel(f: np.ndarray | float) -> np.ndarray:
        return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)

    def mel_to_hz(m: np.ndarray) -> np.ndarray:
        return 700.0 * (10 ** (m / 2595.0) - 1.0)

    bins = np.fft.rfftfreq(N_FFT, 1 / RATE)
    edges = mel_to_hz(np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2))
    filters = np.zeros((n_mels, len(bins)), dtype=np.float32)
    for i in range(n_mels):
        lo, mid, hi = edges[i : i + 3]
        up = (bins - lo) / (mid - lo)
        down = (hi - bins) / (hi - mid)
        filters[i] = np.maximum(0, np.minimum(up, down))
    return filters


def spectrogram(samples: np.ndarray) -> np.ndarray:
    """Magnitude spectrogram, (frames, bins)."""
    if len(samples) < N_FFT:
        samples = np.pad(samples, (0, N_FFT - len(samples)))
    padded = np.pad(samples, (N_FFT // 2, N_FFT // 2))
    n = 1 + (len(padded) - N_FFT) // HOP
    window = np.hanning(N_FFT).astype(np.float32)
    out = np.empty((n, N_FFT // 2 + 1), dtype=np.float32)
    for start in range(0, n, 512):  # in blocks, to keep memory small
        idx = (np.arange(start, min(n, start + 512)) * HOP)[:, None] + np.arange(N_FFT)
        out[start : start + len(idx)] = np.abs(np.fft.rfft(padded[idx] * window, axis=1))
    return out


def onset_strength(spec: np.ndarray) -> np.ndarray:
    mel = np.log1p(10 * (spec @ _mel_filters().T))
    flux = np.maximum(0.0, np.diff(mel, axis=0, prepend=mel[:1])).mean(axis=1)
    # remove the slow rise and fall of loudness, keep the hits
    width = int(FPS)  # one second
    kernel = np.ones(width) / width
    flux = flux - np.convolve(flux, kernel, mode="same")
    flux = np.maximum(flux, 0)
    sd = flux.std()
    return flux / sd if sd > 0 else flux


def estimate_tempo(env: np.ndarray, *, start_bpm: float = 110.0) -> float:
    """The tempo with the strongest rhythm in the onset strength, leaning to ``start_bpm``."""
    n = len(env)
    if n < int(FPS * 2):
        return start_bpm
    x = env - env.mean()
    spectrum = np.fft.rfft(x, n=2 * n)
    ac = np.fft.irfft(np.abs(spectrum) ** 2)[:n]
    lags = np.arange(1, min(n, int(FPS * 60 / 40)))  # down to 40 bpm
    bpm = 60.0 * FPS / lags
    keep = (bpm >= 50) & (bpm <= 220)
    lags, bpm = lags[keep], bpm[keep]
    prior = np.exp(-0.5 * (np.log2(bpm / start_bpm) / 0.9) ** 2)
    # a lag also gets credit from its double (beats line up two bars apart, too)
    double = np.minimum(2 * lags, len(ac) - 1)
    score = (ac[lags] + 0.5 * ac[double]) * prior
    best = lags[int(np.argmax(score))]
    # refine between lags
    if 1 < best < len(ac) - 1:
        a, b, c = ac[best - 1], ac[best], ac[best + 1]
        denom = a - 2 * b + c
        best = best + (0.5 * (a - c) / denom if denom != 0 else 0.0)
    return float(60.0 * FPS / best)


def track_beats(env: np.ndarray, tempo: float) -> np.ndarray:
    """Beat frames by dynamic programming (Ellis 2007)."""
    period = 60.0 * FPS / tempo
    if len(env) < 2 * period:
        return np.array([], dtype=int)
    window = np.exp(-0.5 * (np.arange(-period, period + 1) * 32.0 / period) ** 2)
    local = np.convolve(env, window, mode="same")
    n = len(local)
    backlink = np.full(n, -1, dtype=int)
    score = local.copy()
    lo, hi = round(-2 * period), -round(period / 2)
    offsets = np.arange(lo, hi + 1)
    txwt = -TIGHTNESS * np.log(-offsets / period) ** 2
    first = True
    threshold = 0.01 * local.max()
    for i in range(n):
        candidates = i + offsets
        valid = candidates >= 0
        if not first and valid.any():
            prev = candidates[valid]
            vals = score[prev] + txwt[valid]
            j = int(np.argmax(vals))
            score[i] = local[i] + vals[j]
            backlink[i] = prev[j]
        if first and local[i] > threshold:
            first = False
    # the last beat: the best-scoring local peak near the end
    peaks = np.nonzero((score[1:-1] > score[:-2]) & (score[1:-1] >= score[2:]))[0] + 1
    if len(peaks) == 0:
        return np.array([], dtype=int)
    median = np.median(score[peaks])
    good = peaks[score[peaks] >= 0.5 * median]
    beat = int(good[-1]) if len(good) else int(peaks[-1])
    beats = [beat]
    while backlink[beats[-1]] >= 0:
        beats.append(int(backlink[beats[-1]]))
    beats = np.array(beats[::-1])
    # trim weak beats at both ends (silence before the music starts, a fade at the end)
    strength = local[beats]
    cut = 0.5 * np.sqrt(np.mean(strength**2))
    strong = np.nonzero(strength > cut)[0]
    if len(strong):
        beats = beats[strong[0] : strong[-1] + 1]
    return beats


def chroma(spec: np.ndarray) -> list[float]:
    """How strongly each pitch class (C first) sounds overall, summed and normalized."""
    bins = np.fft.rfftfreq(N_FFT, 1 / RATE)
    use = (bins >= 60) & (bins <= 5000)
    pcs = np.round(12 * np.log2(bins[use] / 440.0) + 69).astype(int) % 12
    energy = np.log1p(spec[:, use]).sum(axis=0)
    out = np.bincount(pcs, weights=energy, minlength=12)
    total = out.sum()
    return [round(float(v / total), 5) if total > 0 else 0.0 for v in out]


def _low_band(spec: np.ndarray) -> np.ndarray:
    """Onset strength of the bass and kick drum alone, where bars are usually marked."""
    bins = np.fft.rfftfreq(N_FFT, 1 / RATE)
    low = np.log1p(10 * spec[:, bins < 200].sum(axis=1))
    return np.maximum(0.0, np.diff(low, prepend=low[:1]))


def downbeats(beats: np.ndarray, spec: np.ndarray, env: np.ndarray) -> tuple[int, int]:
    """(beats per bar, index of the first downbeat among the beats)."""
    if len(beats) < 8:
        return 4, 0
    low = _low_band(spec)
    accent = 0.6 * low[beats] / (low[beats].std() + 1e-9) + 0.4 * env[beats]
    best = (-np.inf, 4, 0)
    for per_bar in (4, 3):
        for phase in range(per_bar):
            on = accent[phase::per_bar].mean()
            off = np.delete(accent, np.arange(phase, len(accent), per_bar)).mean()
            contrast = on - off
            if per_bar == 3:
                contrast -= 0.35  # 3/4 must be clearly better: most songs are in four
            if contrast > best[0]:
                best = (contrast, per_bar, phase)
    return best[1], best[2]


def find_beats(samples: np.ndarray) -> Beats:
    """Beats, bars, tempo and pitch-class strengths for mono samples at 22.05 kHz."""
    spec = spectrogram(samples)
    env = onset_strength(spec)
    tempo = estimate_tempo(env)
    frames = track_beats(env, tempo)
    colors = chroma(spec)
    if len(frames) < 4:
        return Beats(tempo=None, chroma=colors)
    times = frames / FPS
    per_bar, phase = downbeats(frames, spec, env)
    intervals = np.diff(times)
    local_tempo = 60.0 / float(np.median(intervals))
    return Beats(
        tempo=round(local_tempo, 1),
        beat_times=[round(float(t), 4) for t in times],
        downbeats=[round(float(t), 4) for t in times[phase::per_bar]],
        beats_per_bar=per_bar,
        chroma=colors,
    )
