"""Building a song's parts as MusicXML: the key's pentatonic, whole-song scales, a scale for each
chord and each chord's notes, written for the instrument or in concert pitch."""

from __future__ import annotations

from typing import Literal

from ..core.chords import parse_chord
from ..core.names import NameSystem
from ..core.pitch import Interval, Pitch
from ..core.ranges import place_ascending
from ..core.song import ChordInfo, ScaleInfo, Song
from .musicxml import MeasureSpec, NoteSpec, names_for, scale_measure, score_xml

Part = Literal["headline", "scales", "chord_scales", "chord_notes", "all"]
PARTS: tuple[str, ...] = ("headline", "scales", "chord_scales", "chord_notes", "all")
PitchView = Literal["written", "concert"]


def _key_fifths(song: Song, view: PitchView) -> int:
    if view == "written" and song.view and song.view.written_key:
        return song.view.written_key.fifths
    return song.key.concert.fifths if song.key else 0


def _staff(scale: ScaleInfo, view: PitchView) -> list[str]:
    spelling = scale.written if view == "written" and scale.written else scale.concert
    return spelling.staff


def _interval(song: Song) -> Interval:
    return Interval.parse(song.view.interval) if song.view else Interval(0, 0)


def scale_measures(
    song: Song, scales: list[ScaleInfo], names: NameSystem, view: PitchView
) -> list[MeasureSpec]:
    return [scale_measure(_staff(s, view), names) for s in scales]


def chord_scale_measure(
    info: ChordInfo, names: NameSystem, view: PitchView, *, symbol: bool = True
) -> MeasureSpec | None:
    """The scale offered over one chord, with the chord symbol above it."""
    if not info.scales:
        return None
    spelling = info.written if view == "written" and info.written else info.concert
    harmony = parse_chord(spelling.symbol) if symbol else None
    return scale_measure(_staff(info.scales[0], view), names, harmony=harmony)


def chord_note_measure(
    song: Song, info: ChordInfo, names: NameSystem, view: PitchView
) -> MeasureSpec:
    """One chord's notes as a rising arpeggio from its root, in the comfortable range."""
    low = Pitch.parse(song.view.comfortable_low) if song.view else Pitch.parse("C4")
    high = Pitch.parse(song.view.comfortable_high) if song.view else Pitch.parse("C6")
    written = info.written or info.concert
    tones = [Pitch.parse(t) for t in written.tones]
    staff = place_ascending(tones, low, high, add_octave=False)
    if view == "concert":
        interval = _interval(song)
        staff = [p.transpose(-interval) for p in staff]
    spelling = info.written if view == "written" and info.written else info.concert
    notes = [NoteSpec(p, "quarter", names_for(p, names)) for p in staff]
    return MeasureSpec(notes, harmony=parse_chord(spelling.symbol))


def chord_scale_measures(song: Song, names: NameSystem, view: PitchView) -> list[MeasureSpec]:
    measures = [chord_scale_measure(info, names, view) for info in song.chords]
    return [m for m in measures if m is not None]


def chord_note_measures(song: Song, names: NameSystem, view: PitchView) -> list[MeasureSpec]:
    return [chord_note_measure(song, info, names, view) for info in song.chords]


def chord_score(
    song: Song, info: ChordInfo, *, names: NameSystem = "letters", view: PitchView = "written"
) -> str:
    """One chord on its own: its notes, then the scale to play over it."""
    measures = [chord_note_measure(song, info, names, view)]
    scale = chord_scale_measure(info, names, view, symbol=False)
    if scale is not None:
        measures.append(scale)
    return score_xml(measures, key_fifths=_key_fifths(song, view))


def song_score(
    song: Song, part: Part = "all", *, names: NameSystem = "letters", view: PitchView = "written"
) -> str | None:
    """One part of the song as MusicXML, or None when the song has nothing for it."""
    fifths = _key_fifths(song, view)
    headline = [s for s in song.scales if s.role == "headline"]
    others = [s for s in song.scales if s.role != "headline"]
    if part == "headline":
        measures = scale_measures(song, headline, names, view)
    elif part == "scales":
        measures = scale_measures(song, headline + others, names, view)
    elif part == "chord_scales":
        measures = chord_scale_measures(song, names, view)
    elif part == "chord_notes":
        measures = chord_note_measures(song, names, view)
    else:
        measures = scale_measures(song, headline + others, names, view) + chord_scale_measures(
            song, names, view
        )
    if not measures:
        return None
    title = song.identity.title if part == "all" else None
    instrument = song.view.name if (song.view and view == "written") else "Concert pitch"
    return score_xml(
        measures, key_fifths=fifths, title=title, part_name=instrument if part == "all" else ""
    )


def single_scale_score(
    song: Song, scale: ScaleInfo, *, names: NameSystem, view: PitchView = "written"
) -> str:
    return score_xml(
        [scale_measure(_staff(scale, view), names)], key_fifths=_key_fifths(song, view)
    )
