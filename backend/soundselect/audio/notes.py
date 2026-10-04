"""Finding the notes in a recording with Basic Pitch, run from its ONNX model file.

Basic Pitch (Spotify, Apache-2.0) gives, for every 11.6 ms frame and each of the 88 piano keys,
how likely a note sounds there and how likely one starts. Turning that into notes follows the
library's own ``output_to_notes_polyphonic`` (v0.4.0), ported to numpy so that neither
TensorFlow nor the library's other dependencies have to be installed.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache

import numpy as np

from .files import NOTE_MODEL, model_path
from .model import NoteEvent

RATE = 22050
FFT_HOP = 256
WINDOW = RATE * 2 - FFT_HOP  # 43844 samples per model run
FRAMES = 172  # frames per model run (86 per second)
OVERLAP_FRAMES = 30
OVERLAP = OVERLAP_FRAMES * FFT_HOP
HOP = WINDOW - OVERLAP
MIDI_OFFSET = 21
MAX_FREQ_IDX = 87
FPS = RATE / FFT_HOP

ONSET_THRESHOLD = 0.5
FRAME_THRESHOLD = 0.3
MIN_NOTE_FRAMES = 11  # about 128 ms, the library's default
ENERGY_TOLERANCE = 11


@cache
def _session():  # pragma: no cover - needs the downloaded model
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(
        str(model_path(NOTE_MODEL)), options, providers=["CPUExecutionProvider"]
    )


def _onnx_model(windows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:  # pragma: no cover
    """(n, WINDOW, 1) audio windows -> note and onset activations, each (n, FRAMES, 88)."""
    session = _session()
    note, onset = session.run(
        ["StatefulPartitionedCall:1", "StatefulPartitionedCall:2"],
        {"serving_default_input_2:0": windows},
    )
    return note, onset


Model = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


def activations(
    samples: np.ndarray, *, model: Model | None = None, batch: int = 8
) -> tuple[np.ndarray, np.ndarray]:
    """Note and onset activations, (frames, 88) each, for mono samples at 22.05 kHz."""
    model = model or _onnx_model
    length = len(samples)
    audio = np.concatenate([np.zeros(OVERLAP // 2, np.float32), samples.astype(np.float32)])
    windows = []
    for start in range(0, len(audio), HOP):
        w = audio[start : start + WINDOW]
        if len(w) < WINDOW:
            w = np.pad(w, (0, WINDOW - len(w)))
        windows.append(w)
    notes, onsets = [], []
    for i in range(0, len(windows), batch):
        x = np.stack(windows[i : i + batch])[:, :, None]
        n, o = model(x)
        notes.append(n)
        onsets.append(o)
    n_frames = int(np.floor(length * FPS / RATE))

    def unwrap(parts: list[np.ndarray]) -> np.ndarray:
        out = np.concatenate(parts)
        half = OVERLAP_FRAMES // 2
        out = out[:, half:-half, :]
        return out.reshape(-1, out.shape[-1])[:n_frames]

    return unwrap(notes), unwrap(onsets)


def frame_times(n_frames: int) -> np.ndarray:
    """Seconds for each output frame, with the library's correction for window joins."""
    original = np.arange(n_frames) * FFT_HOP / RATE
    window_numbers = np.floor(np.arange(n_frames) / FRAMES)
    window_offset = (FFT_HOP / RATE) * (FRAMES - WINDOW / FFT_HOP) + 0.0018
    return original - window_offset * window_numbers


def _inferred_onsets(onsets: np.ndarray, frames: np.ndarray, n_diff: int = 2) -> np.ndarray:
    diffs = []
    for n in range(1, n_diff + 1):
        appended = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(appended[n:, :] - appended[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    top = np.max(frame_diff)
    if top > 0:
        frame_diff = np.max(onsets) * frame_diff / top
    return np.max([onsets, frame_diff], axis=0)


def _local_maxima(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Like scipy.signal.argrelmax along time: strictly above both neighbours."""
    inner = (x[1:-1] > x[:-2]) & (x[1:-1] > x[2:])
    t, f = np.nonzero(inner)
    return t + 1, f


def to_notes(
    frames: np.ndarray,
    onsets: np.ndarray,
    *,
    onset_threshold: float = ONSET_THRESHOLD,
    frame_threshold: float = FRAME_THRESHOLD,
    min_frames: int = MIN_NOTE_FRAMES,
    energy_tolerance: int = ENERGY_TOLERANCE,
) -> list[tuple[int, int, int, float]]:
    """Notes as (start frame, end frame, MIDI pitch, mean activation)."""
    n_frames = frames.shape[0]
    if n_frames < 3:
        return []
    onsets = _inferred_onsets(onsets, frames)
    peak = np.zeros(onsets.shape)
    t_idx, f_idx = _local_maxima(onsets)
    peak[t_idx, f_idx] = onsets[t_idx, f_idx]
    onset_t, onset_f = np.where(peak >= onset_threshold)
    remaining = frames.copy()
    events: list[tuple[int, int, int, float]] = []

    def clear(a: int, b: int, f: int) -> None:
        remaining[a:b, f] = 0
        if f < MAX_FREQ_IDX:
            remaining[a:b, f + 1] = 0
        if f > 0:
            remaining[a:b, f - 1] = 0

    for start, f in zip(onset_t[::-1], onset_f[::-1], strict=True):
        if start >= n_frames - 1:
            continue
        i, k = start + 1, 0
        while i < n_frames - 1 and k < energy_tolerance:
            k = k + 1 if remaining[i, f] < frame_threshold else 0
            i += 1
        i -= k
        if i - start <= min_frames:
            continue
        clear(start, i, f)
        events.append((int(start), int(i), int(f) + MIDI_OFFSET, float(frames[start:i, f].mean())))

    # the "melodia trick": notes without a clear onset, grown from the strongest frames left
    while np.max(remaining) > frame_threshold:
        mid, f = np.unravel_index(np.argmax(remaining), remaining.shape)
        remaining[mid, f] = 0
        i, k = mid + 1, 0
        while i < n_frames - 1 and k < energy_tolerance:
            k = k + 1 if remaining[i, f] < frame_threshold else 0
            clear(i, i + 1, f)
            i += 1
        end = i - 1 - k
        i, k = mid - 1, 0
        while i > 0 and k < energy_tolerance:
            k = k + 1 if remaining[i, f] < frame_threshold else 0
            clear(i, i + 1, f)
            i -= 1
        start = i + 1 + k
        if end - start <= min_frames:
            continue
        events.append(
            (int(start), int(end), int(f) + MIDI_OFFSET, float(frames[start:end, f].mean()))
        )
    return events


def find_notes(samples: np.ndarray, *, model: Model | None = None) -> list[NoteEvent]:
    """Every note heard in mono samples at 22.05 kHz, in time order."""
    frames, onsets = activations(samples, model=model)
    times = frame_times(frames.shape[0] + 1)
    events = [
        NoteEvent(
            start=round(float(times[a]), 4),
            end=round(float(times[min(b, len(times) - 1)]), 4),
            pitch=p,
            strength=round(amp, 4),
        )
        for a, b, p, amp in to_notes(frames, onsets)
    ]
    return sorted(events, key=lambda e: (e.start, e.pitch))
