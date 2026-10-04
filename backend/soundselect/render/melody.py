"""The melody on the staff, in bars of the song's time signature.

Gaps between notes are rests. A note that crosses a bar line, or a beat it shouldn't hide, is
split and tied, so every beat stays visible the way printed music shows it; eighths and
sixteenths are beamed beat by beat; runs of empty bars become one multi-bar rest; doubtful
notes are drawn in red so they get checked by ear. Names go under the first note of a tie.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core.names import NameSystem
from ..core.pitch import Pitch
from ..core.song import DOUBTFUL, MelodyNote, Song
from .musicxml import Beam, MeasureSpec, NoteSpec, names_for

DOUBTFUL_COLOR = "#C0392B"
# a length in sixteenths -> (note type, dots)
VALUES = {
    16: ("whole", 0),
    12: ("half", 1),
    8: ("half", 0),
    6: ("quarter", 1),
    4: ("quarter", 0),
    3: ("eighth", 1),
    2: ("eighth", 0),
    1: ("16th", 0),
}


@dataclass(frozen=True)
class Meter:
    beats: int = 4
    beat_type: int = 4

    @classmethod
    def parse(cls, text: str | None) -> Meter:
        try:
            beats, beat_type = (int(x) for x in (text or "").split("/"))
        except ValueError:
            return cls()
        if not 1 <= beats <= 12 or beat_type not in (2, 4, 8):
            return cls()
        return cls(beats, beat_type)

    @property
    def bar(self) -> int:
        """The bar's length in sixteenths."""
        return self.beats * 16 // self.beat_type

    @property
    def compound(self) -> bool:
        """6/8, 9/8, 12/8: beats of three eighths."""
        return self.beat_type == 8 and self.beats % 3 == 0 and self.beats > 3

    @property
    def beat(self) -> int:
        return 6 if self.compound else 16 // self.beat_type

    @property
    def half(self) -> int | None:
        """The middle of the bar, when the beats fall in two equal halves (4/4)."""
        half = self.bar // 2
        return half if self.bar % 2 == 0 and half > self.beat and half % self.beat == 0 else None

    def levels(self) -> list[int]:
        """Where a span is best split, strongest first: the middle of the bar, the beats,
        then halves and quarters of a beat."""
        below = [v for v in (4, 2, 1) if v < self.beat and self.beat % v == 0]
        return [*([self.half] if self.half else []), self.beat, *below]


Piece = tuple[int, int]  # start in the bar and length, in sixteenths
Fits = Callable[[Meter, int, int], bool]


def note_fits(m: Meter, pos: int, size: int) -> bool:
    """One note value can show this span: it starts on a beat, or (one beat long) on the
    half beat between two, or it stays inside its beat."""
    if size not in VALUES:
        return False
    if size >= m.beat:
        if m.compound:
            return size % m.beat == 0 and pos % m.beat == 0
        return pos % m.beat == 0 or (size == m.beat and pos % (m.beat // 2) == 0)
    return pos % m.beat + size <= m.beat


def rest_fits(m: Meter, pos: int, size: int) -> bool:
    """Rests are plainer: a beat or half a bar starting on its own grid, or a shorter
    undotted value inside its beat."""
    if size in (m.beat, m.half):
        return pos % size == 0
    return size in (4, 2, 1) and size < m.beat and pos % size == 0 and pos % m.beat + size <= m.beat


def split(m: Meter, start: int, end: int, fits: Fits) -> list[Piece]:
    """A span inside one bar as note values: split at the strongest beat inside it until each
    piece is one value."""
    if fits(m, start, end - start):
        return [(start, end - start)]
    for level in m.levels():
        cut = (start // level + 1) * level
        if cut < end:
            return split(m, start, cut, fits) + split(m, cut, end, fits)
    raise ValueError(f"no note value for {start}-{end}")  # a sixteenth always fits


@dataclass
class _Slot:
    pos: int
    size: int
    note: MelodyNote | None  # None for a rest
    first: bool = True  # the first piece of a tied note
    last: bool = True


def _events(notes: list[MelodyNote]) -> list[tuple[int, int, MelodyNote]]:
    """Notes on the sixteenth grid, in order; a note that overlaps the next one is cut short."""
    grid = sorted(
        (max(0, round(n.start * 4)), max(1, round(n.length * 4)), i, n)
        for i, n in enumerate(notes)
        if n.concert
    )
    out: list[tuple[int, int, MelodyNote]] = []
    for start, length, _, n in grid:
        if out and out[-1][0] + out[-1][1] > start:
            prev_start, _, prev = out.pop()
            if start > prev_start:
                out.append((prev_start, start - prev_start, prev))
        out.append((start, length, n))
    return out


def _beams(m: Meter, slots: list[_Slot]) -> list[tuple[Beam, ...]]:
    """Notes shorter than a quarter are beamed together inside their beat; sixteenths get a
    second beam, or a hook when they stand alone."""
    out: list[tuple[Beam, ...]] = [()] * len(slots)

    def beamable(s: _Slot) -> bool:
        return s.note is not None and s.size < 4

    i = 0
    while i < len(slots):
        if not beamable(slots[i]):
            i += 1
            continue
        beat = slots[i].pos // m.beat
        j = i + 1
        while j < len(slots) and beamable(slots[j]) and slots[j].pos // m.beat == beat:
            j += 1
        run = slots[i:j]
        if len(run) > 1:
            for k, s in enumerate(run):
                first: Beam = "begin" if k == 0 else "end" if k == len(run) - 1 else "continue"
                if s.size != 1:
                    out[i + k] = (first,)
                    continue
                before = k > 0 and run[k - 1].size == 1
                after = k < len(run) - 1 and run[k + 1].size == 1
                second: Beam
                if before and after:
                    second = "continue"
                elif after:
                    second = "begin"
                elif before:
                    second = "end"
                else:
                    second = "forward hook" if k == 0 else "backward hook"
                out[i + k] = (first, second)
        i = j
    return out


def melody_measures(
    song: Song, names: NameSystem = "none", *, written: bool = True
) -> list[MeasureSpec]:
    """The song's melody as bars, written for the instrument or in concert pitch; empty when
    the song has no melody."""
    events = _events(song.melody.notes) if song.melody else []
    if not events:
        return []
    timing = song.timing
    m = Meter.parse(timing.time_signature if timing else None)
    end = max(start + length for start, length, _ in events)
    bars: list[list[_Slot]] = [[] for _ in range(-(-end // m.bar))]

    def place(start: int, length: int, note: MelodyNote | None) -> None:
        pieces: list[tuple[int, Piece]] = []
        pos, stop = start, start + length
        while pos < stop:
            b = pos // m.bar
            cut = min(stop, (b + 1) * m.bar)
            fits = note_fits if note is not None else rest_fits
            pieces += [(b, p) for p in split(m, pos - b * m.bar, cut - b * m.bar, fits)]
            pos = cut
        for k, (b, (p, size)) in enumerate(pieces):
            bars[b].append(_Slot(p, size, note, k == 0, k == len(pieces) - 1))

    pos = 0
    for start, length, note in events:
        if start > pos:
            place(pos, start - pos, None)
        place(start, length, note)
        pos = start + length
    if pos < len(bars) * m.bar:
        place(pos, len(bars) * m.bar - pos, None)

    measures = []
    for slots in bars:
        if all(s.note is None for s in slots):
            measures.append(MeasureSpec([NoteSpec(None, "whole", whole_bar=True)]))
            continue
        notes = []
        for s, beams in zip(slots, _beams(m, slots), strict=True):
            kind, dots = VALUES[s.size]
            if s.note is None:
                notes.append(NoteSpec(None, kind, dots=dots))
                continue
            text = s.note.written if written and s.note.written else s.note.concert
            pitch = Pitch.parse(text or "")
            doubtful = s.note.confidence is not None and s.note.confidence < DOUBTFUL
            notes.append(
                NoteSpec(
                    pitch,
                    kind,
                    names_for(pitch, names) if s.first else [],
                    dots=dots,
                    tie_start=not s.last,
                    tie_stop=not s.first,
                    beams=beams,
                    color=DOUBTFUL_COLOR if doubtful else None,
                )
            )
        measures.append(MeasureSpec(notes))
    for measure in measures:
        measure.time = (m.beats, m.beat_type)
    i = 0
    while i < len(measures):  # runs of empty bars as one multi-bar rest
        j = i
        while j < len(measures) and measures[j].notes[0].whole_bar:
            j += 1
        if j - i > 1:
            measures[i].rest_bars = j - i
        i = max(i + 1, j)
    if timing and timing.tempo and not m.compound:
        measures[0].tempo = round(timing.tempo)
    return measures


def doubtful_count(song: Song) -> int:
    notes = song.melody.notes if song.melody else []
    return sum(
        1 for n in notes if n.concert and n.confidence is not None and n.confidence < DOUBTFUL
    )
