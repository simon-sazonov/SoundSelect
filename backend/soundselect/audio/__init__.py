"""Phase 4: songs from YouTube links or audio files.

Separate the voice, follow the melody, find the beats, then hand notes to the music core.

Its PipelineSpec is registered with ``pipeline.registry.register_pipeline``. Importing this
package must stay cheap and must not need the extras: heavy packages (homr, cv2, music21,
yt_dlp, onnxruntime, rapidocr) are imported inside functions.
"""

from __future__ import annotations

import importlib.util

from ..imports import InputRef
from ..pipeline.registry import PipelineSpec, ReadInput, register_pipeline
from .model import SongSource
from .pipeline import LABELS, SONG, analyze_song


def available() -> bool:
    """PyAV opens the recordings; onnxruntime runs the voice and note models."""
    return all(importlib.util.find_spec(m) is not None for m in ("av", "onnxruntime", "numpy"))


def song_source(inputs: list[InputRef], read: ReadInput) -> SongSource:
    if len(inputs) != 1:
        raise ValueError("a song is made from one recording")
    ref = inputs[0]
    if ref.kind == "link":
        if not ref.url:
            raise ValueError("a link input needs its url")
        return SongSource("link", url=ref.url)
    if ref.kind not in ("audio", "video"):
        raise ValueError(f"a song can't be made from {ref.kind} input")
    return SongSource("audio", read(ref), ref.name)


SONG_SPEC = register_pipeline(
    PipelineSpec(
        name="song",
        pipeline=SONG,
        labels=LABELS,
        source=song_source,
        identity=lambda source: source.fingerprint,
        make=analyze_song,
        available=available,
    )
)

__all__ = ["SONG_SPEC", "SongSource", "analyze_song", "available"]
