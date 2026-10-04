"""Taking the screenshots from a sheet music video: sample it twice a second, find the stretches
where the picture holds still (one view each), and make one clean picture per view.

A playback cursor or a highlighted note moves within a view, so the pixel median over the
view's samples leaves only the music. Fades and page turns change the picture a lot from one
sample to the next and are skipped.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

from .staves import Image, to_gray

FPS = 2.0
STILL = 4.0  # mean change (0-255) between samples that still counts as the same view
MIN_SAMPLES = 2  # a stretch shorter than this is a fade or a transition
MAX_SAMPLES = 7200  # one hour at two samples a second
MEDIAN_SAMPLES = 15  # samples per view that go into its clean picture


class VideoError(ValueError):
    """The video can't be opened or has no picture."""


def sample(path: str | os.PathLike[str], fps: float = FPS) -> list[Image]:
    """``fps`` frames a second from a video file, in order."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise VideoError("This video can't be opened. Try an MP4 file or a link.")
    try:
        rate = cap.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, round(rate / fps))
        frames: list[Image] = []
        index = 0
        while len(frames) < MAX_SAMPLES:
            if not cap.grab():
                break
            if index % step == 0:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    frames.append(frame)
            index += 1
    finally:
        cap.release()
    if not frames:
        raise VideoError("No pictures could be read from this video.")
    return frames


def sample_bytes(data: bytes, suffix: str = ".mp4", fps: float = FPS) -> list[Image]:
    """Like ``sample``, for a video held in memory (OpenCV reads only from files)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"video{suffix or '.mp4'}"
        path.write_bytes(data)
        return sample(path, fps)


def find_views(frames: list[Image], still: float = STILL) -> list[list[int]]:
    """Runs of near-identical samples, each one view, as lists of sample numbers."""
    if not frames:
        return []
    small = [
        cv2.resize(to_gray(f), (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)
        for f in frames
    ]
    runs, current = [], [0]
    for i in range(1, len(frames)):
        if np.abs(small[i] - small[i - 1]).mean() < still:
            current.append(i)
        else:
            runs.append(current)
            current = [i]
    runs.append(current)
    return [r for r in runs if len(r) >= MIN_SAMPLES]


def clean_view(frames: list[Image], samples: list[int]) -> Image:
    """The pixel median of a view's samples: whatever moves (a cursor) disappears."""
    if len(samples) > MEDIAN_SAMPLES:
        pick = np.linspace(0, len(samples) - 1, MEDIAN_SAMPLES).round().astype(int)
        samples = [samples[i] for i in pick]
    stack = np.stack([frames[i] for i in samples])
    return np.median(stack, axis=0).astype(np.uint8)


def views_of(frames: list[Image]) -> list[Image]:
    return [clean_view(frames, run) for run in find_views(frames)]
