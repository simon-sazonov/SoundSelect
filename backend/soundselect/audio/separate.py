"""Separating the voice from the band with an MDX-Net model, run with onnxruntime.

MDX-Net (from the Ultimate Vocal Remover project) predicts the voice's spectrogram from the
song's; the rest of the band is what's left. It needs no PyTorch, so it installs on every
laptop the app supports, Intel Macs included. The windowing and spectrogram settings follow
the model's published parameters (n_fft 7680, hop 1024, 3072 frequency bins, 256 frames).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache

import numpy as np

from .files import VOICE_MODEL, model_path

RATE = 44100
N_FFT = 7680
HOP = 1024
DIM_F = 3072
DIM_T = 256
COMPENSATE = 1.021  # the model's published level correction
CHUNK = HOP * (DIM_T - 1)  # samples per model run, about 5.9 seconds
TRIM = N_FFT // 2
OVERLAP = 0.25


@cache
def _session():  # pragma: no cover - needs the downloaded model
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(
        str(model_path(VOICE_MODEL)), options, providers=["CPUExecutionProvider"]
    )


_WINDOW = np.hanning(N_FFT + 1)[:-1].astype(np.float32)  # periodic Hann, as the model was trained


def stft(chunk: np.ndarray) -> np.ndarray:
    """(2, CHUNK) stereo samples -> (4, DIM_F, DIM_T): left real, left imaginary, right..."""
    padded = np.pad(chunk, ((0, 0), (N_FFT // 2, N_FFT // 2)), mode="reflect")
    starts = np.arange(DIM_T) * HOP
    index = starts[:, None] + np.arange(N_FFT)[None, :]
    frames = padded[:, index] * _WINDOW  # (2, T, N_FFT)
    spec = np.fft.rfft(frames, axis=-1)[:, :, :DIM_F]  # (2, T, F)
    spec = spec.transpose(0, 2, 1)  # (2, F, T)
    out = np.empty((4, DIM_F, DIM_T), dtype=np.float32)
    out[0], out[1] = spec[0].real, spec[0].imag
    out[2], out[3] = spec[1].real, spec[1].imag
    return out


def istft(spec: np.ndarray) -> np.ndarray:
    """The inverse of ``stft``: (4, DIM_F, DIM_T) -> (2, CHUNK)."""
    bins = N_FFT // 2 + 1
    full = np.zeros((2, bins, DIM_T), dtype=np.complex64)
    full[0, :DIM_F] = spec[0] + 1j * spec[1]
    full[1, :DIM_F] = spec[2] + 1j * spec[3]
    frames = np.fft.irfft(full.transpose(0, 2, 1), n=N_FFT, axis=-1) * _WINDOW  # (2, T, N_FFT)
    length = N_FFT + HOP * (DIM_T - 1)
    out = np.zeros((2, length), dtype=np.float32)
    norm = np.zeros(length, dtype=np.float32)
    for t in range(DIM_T):
        out[:, t * HOP : t * HOP + N_FFT] += frames[:, t]
        norm[t * HOP : t * HOP + N_FFT] += _WINDOW**2
    out /= np.maximum(norm, 1e-8)
    return out[:, N_FFT // 2 : N_FFT // 2 + CHUNK]


def _run_model(chunk: np.ndarray, model: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    spec = stft(chunk)
    spec[:, :3, :] = 0  # the lowest bins carry nothing the model can use
    return istft(model(spec))


def _onnx_model(spec: np.ndarray) -> np.ndarray:  # pragma: no cover - needs the model
    session = _session()
    return session.run(None, {session.get_inputs()[0].name: spec[None]})[0][0]


def separate_voice(
    mix: np.ndarray,
    *,
    model: Callable[[np.ndarray], np.ndarray] | None = None,
    progress: Callable[[float], None] | None = None,
) -> np.ndarray:
    """The voice from a stereo (2, samples) mix at 44.1 kHz, the same shape."""
    model = model or _onnx_model
    n = mix.shape[-1]
    peak = float(np.abs(mix).max()) or 1.0
    scale = 0.9 / peak if peak > 0.9 else 1.0  # the model expects a mix that doesn't clip
    gen = CHUNK - 2 * TRIM
    pad = gen + TRIM - (n % gen)
    padded = np.concatenate(
        (np.zeros((2, TRIM), np.float32), mix * scale, np.zeros((2, pad), np.float32)), axis=1
    )
    total = padded.shape[-1]
    result = np.zeros((2, total), dtype=np.float32)
    divider = np.zeros(total, dtype=np.float32)
    step = int((1 - OVERLAP) * CHUNK)
    starts = list(range(0, total, step))
    for done, start in enumerate(starts):
        end = min(start + CHUNK, total)
        part = padded[:, start:end]
        if part.shape[-1] < CHUNK:
            part = np.pad(part, ((0, 0), (0, CHUNK - part.shape[-1])))
        window = np.hanning(end - start).astype(np.float32)
        out = _run_model(part, model)[:, : end - start] * window
        result[:, start:end] += out
        divider[start:end] += window
        if progress:
            progress((done + 1) / len(starts))
    voice = result / np.maximum(divider, 1e-8)
    return voice[:, TRIM : TRIM + n] * (COMPENSATE / scale)
