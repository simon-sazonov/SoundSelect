"""The melody on the staff, as MusicXML: bars in the song's time signature, rests in the gaps,
ties across bar lines, dotted values, and doubtful notes drawn in red so they get checked.

A handoff for the score builder in ``render/``, which takes this over (it adds rests, ties and
time signatures to ``render/musicxml.py``); until then it shows what the song tool's melody
needs from it.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..core.names import NameSystem
from ..core.pitch import Pitch
from ..core.song import Song
from ..render.musicxml import DIVISIONS, key_alters, names_for

# sixteenths -> (type, dots), largest first
_VALUES = [
    (16, "whole", 0),
    (12, "half", 1),
    (8, "half", 0),
    (6, "quarter", 1),
    (4, "quarter", 0),
    (3, "eighth", 1),
    (2, "eighth", 0),
    (1, "16th", 0),
]
_ACCIDENTALS = {2: "double-sharp", 1: "sharp", 0: "natural", -1: "flat", -2: "flat-flat"}
DOUBTFUL = 0.4
DOUBTFUL_COLOR = "#C0392B"


def _split(start: int, length: int, beat: int) -> list[int]:
    """Note values (in sixteenths) for a span inside one bar: the largest value that fits and
    starts where such a value may start (a half note on a half-bar, a quarter on a beat)."""
    out = []
    pos = start
    end = start + length
    while pos < end:
        for size, _, _ in _VALUES:
            align = min(size, beat) if size >= beat else 1
            if size <= end - pos and pos % align == 0:
                out.append(size)
                pos += size
                break
    return out


def _value(size: int) -> tuple[str, int]:
    return next((t, d) for s, t, d in _VALUES if s == size)


def melody_xml(
    song: Song, names: NameSystem = "none", view: str = "written", title: str | None = None
) -> str:
    """The song's melody as a one-part score, written for the instrument or in concert pitch."""
    melody = song.melody
    timing = song.timing
    per_bar = int((timing.time_signature or "4/4").split("/")[0]) if timing else 4
    bar = per_bar * 4  # sixteenths
    beat = 4
    if view == "written" and song.view and song.view.written_key:
        fifths = song.view.written_key.fifths
    else:
        fifths = song.key.concert.fifths if song.key else 0

    # (start, length, pitch or None for a rest, doubtful) in sixteenths
    events: list[tuple[int, int, Pitch | None, bool]] = []
    pos = 0
    for n in melody.notes if melody else []:
        text = n.written if view == "written" and n.written else n.concert
        start, length = round(n.start * 4), max(1, round(n.length * 4))
        if start < pos:
            continue
        if start > pos:
            events.append((pos, start - pos, None, False))
        pitch = Pitch.parse(text) if text else None
        events.append((start, length, pitch, (n.confidence or 0) < DOUBTFUL))
        pos = start + length
    total = max(bar, -(-pos // bar) * bar)
    if pos < total:
        events.append((pos, total - pos, None, False))

    measures: list[list[str]] = [[] for _ in range(total // bar)]
    signature = key_alters(fifths)
    shown: list[dict[tuple[str, int], int]] = [{} for _ in measures]
    for start, length, pitch, doubtful in events:
        pieces: list[tuple[int, int]] = []  # (bar index, size)
        p, end = start, start + length
        while p < end:
            b = p // bar
            span = min(end, (b + 1) * bar) - p
            for size in _split(p - b * bar, span, beat):
                pieces.append((b, size))
            p += span
        for i, (b, size) in enumerate(pieces):
            kind, dots = _value(size)
            dot_xml = "<dot/>" * dots
            if pitch is None:
                measures[b].append(
                    f"<note><rest/><duration>{size * DIVISIONS // 4}</duration>"
                    f"<type>{kind}</type>{dot_xml}</note>"
                )
                continue
            letter_key = (pitch.letter, pitch.octave or 0)
            current = shown[b].get(letter_key, signature[pitch.letter])
            acc = ""
            first_in_bar = i == 0 or pieces[i - 1][0] != b
            if first_in_bar and pitch.alter != current:
                acc = f"<accidental>{_ACCIDENTALS[pitch.alter]}</accidental>"
            shown[b][letter_key] = pitch.alter
            ties, tied = "", ""
            if i > 0:
                ties += '<tie type="stop"/>'
                tied += '<tied type="stop"/>'
            if i < len(pieces) - 1:
                ties += '<tie type="start"/>'
                tied += '<tied type="start"/>'
            color = f' color="{DOUBTFUL_COLOR}"' if doubtful else ""
            lyrics = ""
            if i == 0:
                lyrics = "".join(
                    f'<lyric number="{k}"><syllabic>single</syllabic>'
                    f"<text>{escape(t)}</text></lyric>"
                    for k, t in enumerate(names_for(pitch, names), start=1)
                    if t
                )
            alter = f"<alter>{pitch.alter}</alter>" if pitch.alter else ""
            measures[b].append(
                f"<note{color}><pitch><step>{pitch.letter}</step>{alter}"
                f"<octave>{pitch.octave}</octave></pitch>"
                f"<duration>{size * DIVISIONS // 4}</duration>{ties}<type>{kind}</type>{dot_xml}"
                f"{acc}{'<notations>' + tied + '</notations>' if tied else ''}{lyrics}</note>"
            )

    body = []
    for number, notes in enumerate(measures, start=1):
        head = ""
        if number == 1:
            tempo = ""
            if timing and timing.tempo:
                bpm = round(timing.tempo)
                tempo = (
                    '<direction placement="above"><direction-type><metronome>'
                    f"<beat-unit>quarter</beat-unit><per-minute>{bpm}</per-minute>"
                    f'</metronome></direction-type><sound tempo="{bpm}"/></direction>'
                )
            head = (
                f"<attributes><divisions>{DIVISIONS}</divisions>"
                f"<key><fifths>{fifths}</fifths></key>"
                f"<time><beats>{per_bar}</beats><beat-type>4</beat-type></time>"
                "<clef><sign>G</sign><line>2</line></clef></attributes>" + tempo
            )
        end = (
            '<barline location="right"><bar-style>light-heavy</bar-style></barline>'
            if number == len(measures)
            else ""
        )
        body.append(f'<measure number="{number}">{head}{"".join(notes)}{end}</measure>')
    title_xml = f"<work><work-title>{escape(title)}</work-title></work>" if title else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">\n'
        f'<score-partwise version="4.0">{title_xml}'
        "<identification><encoding><software>SoundSelect</software></encoding></identification>"
        '<part-list><score-part id="P1"><part-name print-object="no"></part-name></score-part>'
        f'</part-list><part id="P1">{"".join(body)}</part></score-partwise>\n'
    )
