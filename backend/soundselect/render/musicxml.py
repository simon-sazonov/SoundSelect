"""MusicXML for what a song page shows on the staff: scales, chord scales, chord notes and the
melody.

Names go under the notes as lyrics (two lines in the "both" mode), chord symbols above the
staff. Accidentals are written out against the key signature, measure by measure, because the
drawing engine shows exactly the accidentals it is given.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal
from xml.sax.saxutils import escape

from ..core.chords import Chord, musicxml_kind, parse_chord, quality_display
from ..core.names import NameSystem, note_name
from ..core.pitch import Pitch

DIVISIONS = 4  # per quarter note
DURATIONS = {"whole": 16, "half": 8, "quarter": 4, "eighth": 2, "16th": 1}
_SHARP_ORDER = "FCGDAEB"
_ACCIDENTALS = {2: "double-sharp", 1: "sharp", 0: "natural", -1: "flat", -2: "flat-flat"}

Beam = Literal["begin", "continue", "end", "forward hook", "backward hook"]


@dataclass
class NoteSpec:
    pitch: Pitch | None  # None for a rest
    duration: str = "quarter"
    lyrics: list[str] = field(default_factory=list)
    dots: int = 0
    tie_start: bool = False  # tied on to the next note
    tie_stop: bool = False  # tied from the note before: no accidental of its own
    beams: tuple[Beam, ...] = ()  # one per beam, the eighth beam first
    color: str | None = None
    whole_bar: bool = False  # a rest filling its bar, drawn as a whole rest in the middle

    @property
    def length(self) -> int:
        base = DURATIONS[self.duration]
        return base + sum(base >> d for d in range(1, self.dots + 1))


@dataclass
class MeasureSpec:
    notes: list[NoteSpec]
    harmony: Chord | None = None
    words: str | None = None
    time: tuple[int, int] | None = None  # a time signature to show; None: worked out, hidden
    tempo: int | None = None  # quarter notes a minute, marked above the bar
    rest_bars: int = 1  # more than one: this and the next empty bars as one multi-bar rest
    new_system: bool = False
    barline: str | None = None  # the bar line closing it, e.g. "light-light"


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


def _note_xml(n: NoteSpec, accidental: str | None, bar: int) -> str:
    dots = "<dot/>" * n.dots
    p = n.pitch
    if p is None:
        if n.whole_bar:
            return f'<note><rest measure="yes"/><duration>{bar}</duration></note>'
        return f"<note><rest/><duration>{n.length}</duration><type>{n.duration}</type>{dots}</note>"
    color = f' color="{n.color}"' if n.color else ""
    alter = f"<alter>{p.alter}</alter>" if p.alter else ""
    ties = ('<tie type="stop"/>' if n.tie_stop else "") + (
        '<tie type="start"/>' if n.tie_start else ""
    )
    tied = ties.replace("<tie ", "<tied ")
    acc = f"<accidental>{accidental}</accidental>" if accidental else ""
    beams = "".join(f'<beam number="{i}">{b}</beam>' for i, b in enumerate(n.beams, start=1))
    notations = f"<notations>{tied}</notations>" if tied else ""
    lyrics = "".join(
        f'<lyric number="{i}"><syllabic>single</syllabic><text>{escape(text)}</text></lyric>'
        for i, text in enumerate(n.lyrics, start=1)
        if text
    )
    return (
        f"<note{color}><pitch><step>{p.letter}</step>{alter}<octave>{p.octave}</octave></pitch>"
        f"<duration>{n.length}</duration>{ties}<type>{n.duration}</type>{dots}{acc}{beams}"
        f"{notations}{lyrics}</note>"
    )


def _tempo_xml(bpm: int) -> str:
    return (
        '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
        f'<per-minute>{bpm}</per-minute></metronome></direction-type><sound tempo="{bpm}"/>'
        "</direction>"
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
    """A one-part score. Measures with a time signature of their own show it; the others can
    differ in length, and their time signature is worked out and hidden."""
    sign, line = clef[0], clef[1:]
    signature = key_alters(key_fifths)
    body = []
    last_time = None
    for number, m in enumerate(measures, start=1):
        if m.time:
            time, shown = m.time, True
            bar = m.time[0] * DIVISIONS * 4 // m.time[1]
        else:
            bar = sum(n.length for n in m.notes)
            time = (bar // 4, 4) if bar % 4 == 0 else (bar // 2, 8)
            time, shown = (max(time[0], 1), time[1]), show_time
        attrs = []
        if number == 1:
            attrs += [
                f"<divisions>{DIVISIONS}</divisions>",
                f"<key><fifths>{key_fifths}</fifths></key>",
            ]
        if (time, shown) != last_time:
            hidden = "" if shown else ' print-object="no"'
            attrs.append(
                f"<time{hidden}><beats>{time[0]}</beats><beat-type>{time[1]}</beat-type></time>"
            )
            last_time = (time, shown)
        if number == 1:
            attrs.append(f"<clef><sign>{sign}</sign><line>{line}</line></clef>")
        parts = ['<print new-system="yes"/>'] if m.new_system else []
        if attrs:
            parts.append(f"<attributes>{''.join(attrs)}</attributes>")
        if m.rest_bars > 1:  # on its own: with the clef, the drawing engine draws a second clef
            parts.append(
                "<attributes><measure-style>"
                f"<multiple-rest>{m.rest_bars}</multiple-rest></measure-style></attributes>"
            )
        if m.tempo:
            parts.append(_tempo_xml(m.tempo))
        if m.words:
            parts.append(
                '<direction placement="above"><direction-type>'
                f"<words>{escape(m.words)}</words></direction-type></direction>"
            )
        if m.harmony is not None:
            parts.append(_harmony_xml(m.harmony))
        current: dict[tuple[str, int], int] = {}
        for n in m.notes:
            p, accidental = n.pitch, None
            if p is not None and not n.tie_stop:  # a tie carries its accidental over
                key = (p.letter, p.octave or 0)
                before = current.get(key, signature[p.letter])
                accidental = _ACCIDENTALS.get(p.alter) if p.alter != before else None
                current[key] = p.alter
            parts.append(_note_xml(n, accidental, bar))
        style = "light-heavy" if number == len(measures) else m.barline
        if style:
            parts.append(f'<barline location="right"><bar-style>{style}</bar-style></barline>')
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
