"""Opening any recording (MP3, M4A, WAV, FLAC, Opus from YouTube, a phone's voice memo) as
plain samples, through PyAV, which carries its own copy of ffmpeg."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from ..sheets.readers import UnsupportedInput

MAX_SECONDS = 15 * 60  # longer recordings are cut here: a song, not a concert


def decode(
    source: bytes | Path, *, rate: int, channels: int = 1, max_seconds: float = MAX_SECONDS
) -> np.ndarray:
    """The recording as float32 samples at ``rate``: shape (samples,) for mono, else
    (channels, samples)."""
    import av

    layout = "mono" if channels == 1 else "stereo"
    stream_source = io.BytesIO(source) if isinstance(source, bytes) else str(source)
    blocks: list[np.ndarray] = []
    limit = int(max_seconds * rate)
    total = 0
    try:
        with av.open(stream_source) as container:
            if not container.streams.audio:
                raise UnsupportedInput("This file has no sound in it.")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="fltp", layout=layout, rate=rate)
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    blocks.append(out.to_ndarray())
                    total += blocks[-1].shape[-1]
                if total >= limit:
                    break
            else:
                for out in resampler.resample(None):
                    blocks.append(out.to_ndarray())
    except av.FFmpegError as exc:
        raise UnsupportedInput(f"This file can't be opened as sound ({exc}).") from exc
    if not blocks:
        raise UnsupportedInput("This file has no sound in it.")
    samples = np.concatenate(blocks, axis=-1)[:, :limit].astype(np.float32)
    return samples[0] if channels == 1 else samples


def resample(samples: np.ndarray, rate: int, new_rate: float) -> np.ndarray:
    """Mono samples at another rate (linear interpolation after a gentle low-pass when
    lowering the rate: good enough for analysis, never for listening)."""
    if abs(new_rate - rate) < 1e-6:
        return samples
    n = round(len(samples) * new_rate / rate)
    if new_rate < rate:
        width = max(1, round(rate / new_rate))
        kernel = np.hanning(2 * width + 1)
        samples = np.convolve(samples, kernel / kernel.sum(), mode="same")
    x = np.arange(n) * (rate / new_rate)
    return np.interp(x, np.arange(len(samples)), samples).astype(np.float32)
