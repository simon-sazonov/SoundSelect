"""MusicXML for what a song page shows on the staff: scales, chord scales, chord notes.

Names go under the notes as lyrics (two lines in the "both" mode), chord symbols above the
staff. Accidentals are written out against the key signature, measure by measure, because the
drawing engine shows exactly the accidentals it is given.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from ..core.chords import Chord, musicxml_kind, parse_chord, quality_display
from ..core.names import NameSystem, note_name
from ..core.pitch import Pitch

DIVISIONS = 4  # per quarter note
DURATIONS = {"whole": 16, "half": 8, "quarter": 4, "eighth": 2, "16th": 1}
_SHARP_ORDER = "FCGDAEB"
_ACCIDENTALS = {2: "double-sharp", 1: "sharp", 0: "natural", -1: "flat", -2: "flat-flat"}


@dataclass
class NoteSpec:
    pitch: Pitch
    duration: str = "quarter"
    lyrics: list[str] = field(default_factory=list)


@dataclass
class MeasureSpec:
    notes: list[NoteSpec]
    harmony: Chord | None = None
    words: str | None = None


def key_alters(fifths: int) -> dict[str, int]:
    """The alteration the key signature gives each letter (2 flats: B and E are -1)."""
    alters = dict.fromkeys("CDEFGAB", 0)
    if fifths > 0:
        for letter in _SHARP_ORDER[:fifths]:
            alters[letter] = 1
    elif fifths < 0:
        for letter in _SHARP_ORDER[::-1][:-fifths]:
            alters[letter] = -1
    return alters


def names_for(p: Pitch, names: NameSystem) -> list[str]:
    if names == "none":
        return []
    if names == "both":
        return [note_name(p, "letters"), note_name(p, "russian")]
    return [note_name(p, names)]


def _harmony_xml(c: Chord) -> str:
    def step_alter(tag: str, p: Pitch) -> str:
        alter = f"<{tag}-alter>{p.alter}</{tag}-alter>" if p.alter else ""
        return f"<{tag}-step>{p.letter}</{tag}-step>{alter}"

    bass = f"<bass>{step_alter('bass', c.bass)}</bass>" if c.bass else ""
    text = escape(quality_display(c.quality), {'"': "&quot;"})
    return (
        f"<harmony><root>{step_alter('root', c.root)}</root>"
        f'<kind text="{text}">{musicxml_kind(c)}</kind>{bass}</harmony>'
    )


def _note_xml(n: NoteSpec, accidental: str | None) -> str:
    p = n.pitch
    alter = f"<alter>{p.alter}</alter>" if p.alter else ""
    acc = f"<accidental>{accidental}</accidental>" if accidental else ""
    lyrics = "".join(
        f'<lyric number="{i}"><syllabic>single</syllabic><text>{escape(text)}</text></lyric>'
        for i, text in enumerate(n.lyrics, start=1)
        if text
    )
    return (
        f"<note><pitch><step>{p.letter}</step>{alter}<octave>{p.octave}</octave></pitch>"
        f"<duration>{DURATIONS[n.duration]}</duration><type>{n.duration}</type>{acc}{lyrics}</note>"
    )


def score_xml(
    measures: Sequence[MeasureSpec],
    *,
    key_fifths: int = 0,
    title: str | None = None,
    part_name: str = "",
    clef: str = "G2",
    show_time: bool = False,
) -> str:
    """A one-part score. Measures can differ in length; the time signature is hidden."""
    sign, line = clef[0], clef[1:]
    body = []
    last_length = None
    for number, m in enumerate(measures, start=1):
        length = sum(DURATIONS[n.duration] for n in m.notes)
        attrs = []
        if number == 1:
            attrs += [
                f"<divisions>{DIVISIONS}</divisions>",
                f"<key><fifths>{key_fifths}</fifths></key>",
            ]
        if length != last_length:
            beats, beat_type = (length // 4, 4) if length % 4 == 0 else (length // 2, 8)
            hidden = "" if show_time else ' print-object="no"'
            attrs.append(
                f"<time{hidden}><beats>{max(beats, 1)}</beats>"
                f"<beat-type>{beat_type}</beat-type></time>"
            )
            last_length = length
        if number == 1:
            attrs.append(f"<clef><sign>{sign}</sign><line>{line}</line></clef>")
        parts = [f"<attributes>{''.join(attrs)}</attributes>"] if attrs else []
        if m.words:
            parts.append(
                '<direction placement="above"><direction-type>'
                f"<words>{escape(m.words)}</words></direction-type></direction>"
            )
        if m.harmony is not None:
            parts.append(_harmony_xml(m.harmony))
        signature = key_alters(key_fifths)
        current: dict[tuple[str, int], int] = {}
        for n in m.notes:
            key = (n.pitch.letter, n.pitch.octave or 0)
            shown = current.get(key, signature[n.pitch.letter])
            accidental = _ACCIDENTALS.get(n.pitch.alter) if n.pitch.alter != shown else None
            current[key] = n.pitch.alter
            parts.append(_note_xml(n, accidental))
        if number == len(measures):
            parts.append('<barline location="right"><bar-style>light-heavy</bar-style></barline>')
        body.append(f'<measure number="{number}">{"".join(parts)}</measure>')

    title_xml = f"<work><work-title>{escape(title)}</work-title></work>" if title else ""
    name_xml = (
        f"<part-name>{escape(part_name)}</part-name>"
        if part_name
        else '<part-name print-object="no"></part-name>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">\n'
        f'<score-partwise version="4.0">{title_xml}'
        "<identification><encoding><software>SoundSelect</software></encoding></identification>"
        f'<part-list><score-part id="P1">{name_xml}</score-part></part-list>'
        f'<part id="P1">{"".join(body)}</part></score-partwise>\n'
    )


def scale_measure(
    staff: Sequence[str],
    names: NameSystem,
    *,
    harmony: Chord | None = None,
    words: str | None = None,
) -> MeasureSpec:
    notes = [NoteSpec(Pitch.parse(s), "quarter", names_for(Pitch.parse(s), names)) for s in staff]
    return MeasureSpec(notes, harmony=harmony, words=words)


def chord_symbol(symbol: str | None) -> Chord | None:
    return parse_chord(symbol) if symbol else None
