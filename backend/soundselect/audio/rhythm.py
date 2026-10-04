"""Snapping the melody to the beat: each note's start and length counted in beats.

Times become beats one beat at a time, along the beats actually found, not along one fixed
tempo: a single tempo is what made the rhythm drift in the research test. Starts and ends then
snap to the nearest sixteenth note.
"""

from __future__ import annotations

import numpy as np

from .model import Beats, NoteEvent, Rhythm, TimedNote

GRID = 0.25  # a sixteenth note, in beats
DEFAULT_TEMPO = 100.0


def beat_position(times: np.ndarray, beat_times: list[float]) -> np.ndarray:
    """Seconds -> beats along the found beats (beat 0 at the first one), extended before and
    after them at the nearest beats' pace."""
    beats = np.asarray(beat_times, dtype=float)
    index = np.arange(len(beats), dtype=float)
    pos = np.interp(times, beats, index)
    first = beats[1] - beats[0]
    last = beats[-1] - beats[-2]
    pos = np.where(times < beats[0], (times - beats[0]) / first, pos)
    return np.where(times > beats[-1], index[-1] + (times - beats[-1]) / last, pos)


def _grid(beats: Beats, seconds: float) -> tuple[list[float], int]:
    """Beat times to use and the index of the first downbeat among them; a steady grid at a
    default tempo when no beat was found (a voice memo with no band)."""
    if len(beats.beat_times) >= 4:
        times = beats.beat_times
        first = beats.downbeats[0] if beats.downbeats else times[0]
        return times, int(np.argmin(np.abs(np.asarray(times) - first)))
    tempo = beats.tempo or DEFAULT_TEMPO
    step = 60.0 / tempo
    return [i * step for i in range(int(seconds / step) + 2)], 0


def snap(x: float) -> float:
    return round(x / GRID) * GRID


def to_rhythm(melody: list[NoteEvent], beats: Beats, seconds: float) -> Rhythm:
    times, first_down = _grid(beats, seconds)
    per_bar = beats.beats_per_bar
    tempo = beats.tempo or round(60.0 / float(np.median(np.diff(times))), 1)
    if not melody:
        return Rhythm(tempo=tempo, time_signature=f"{per_bar}/4", first_bar=times[first_down])
    starts = beat_position(np.array([n.start for n in melody]), times) - first_down
    ends = beat_position(np.array([n.end for n in melody]), times) - first_down
    # bar 1 starts at the downbeat at or before the first note (a pickup gets its own bar)
    bar_shift = -np.floor(starts.min() / per_bar) * per_bar if starts.min() < 0 else 0.0
    first_bar_beat = first_down - bar_shift
    notes: list[TimedNote] = []
    for n, s, e in zip(melody, starts + bar_shift, ends + bar_shift, strict=True):
        start, end = snap(s), snap(e)
        if notes and start < notes[-1].start + notes[-1].length:
            prev = notes[-1]
            if start <= prev.start:  # two notes on one grid slot: keep the clearer one
                if n.strength > prev.confidence:
                    notes[-1] = TimedNote(
                        pitch=n.pitch,
                        start=prev.start,
                        length=max(GRID, end - prev.start),
                        confidence=round(n.strength, 3),
                    )
                continue
            notes[-1] = prev.model_copy(update={"length": start - prev.start})
        length = max(GRID, end - start)
        notes.append(
            TimedNote(pitch=n.pitch, start=start, length=length, confidence=round(n.strength, 3))
        )
    # close tiny gaps: a note held until the next one reads better than a sixteenth rest
    for i in range(len(notes) - 1):
        gap = notes[i + 1].start - (notes[i].start + notes[i].length)
        if 0 < gap <= GRID:
            notes[i] = notes[i].model_copy(update={"length": notes[i].length + gap})
    first_bar = float(np.interp(first_bar_beat, np.arange(len(times)), times))
    if first_bar_beat < 0:
        first_bar = times[0] + first_bar_beat * (times[1] - times[0])
    return Rhythm(
        notes=notes,
        tempo=tempo,
        time_signature=f"{per_bar}/4",
        first_bar=round(first_bar, 4),
    )
