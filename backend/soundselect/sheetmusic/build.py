"""From the concert-pitch score to the Song result every tool shares: the key from the key
signature, the chords placed on their beats line by line, the melody (the top staff), the time
signature, the clean-copy pages and notes for the player.

The music core then writes it for the player's instrument, exactly as for a chord sheet.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..core.chords import Chord, parse_chord
from ..core.keyfind import score_key
from ..core.keys import Key, pitch_from_fifths
from ..core.pitch import Interval, Pitch
from ..core.song import (
    ChordInfo,
    ChordPlacement,
    Corrections,
    Identity,
    KeyCandidate,
    KeyName,
    KeyResult,
    Line,
    Melody,
    MelodyNote,
    Notice,
    Section,
    SheetMusicInfo,
    Song,
    SourceKind,
    SourcePage,
    SourceRef,
    Timing,
)
from ..core.view import chord_spelling
from . import score as scores
from .models import ChordMark, Clean, PageText, Read


def m21_pitch(p: Any) -> str:
    """A music21 pitch in the Song's spelling: 'B-4' -> 'Bb4'."""
    name = p.name.replace("-", "b")
    return f"{name}{p.octave if p.octave is not None else 4}"


def melody_of(score: Any) -> list[MelodyNote]:
    """The top staff's notes (the highest note of a chord), ties joined, in quarter-note beats."""
    import music21

    part = score.parts[0].stripTies()
    notes = []
    for n in part.flatten().notesAndRests:
        if isinstance(n, music21.harmony.ChordSymbol):
            continue
        start, length = float(n.offset), float(n.quarterLength)
        if length <= 0:
            continue  # grace notes
        if n.isRest:
            pitch = None
        elif n.isChord:
            pitch = m21_pitch(max(n.pitches, key=lambda x: x.ps))
        else:
            pitch = m21_pitch(n.pitch)
        notes.append(MelodyNote(concert=pitch, start=round(start, 4), length=round(length, 4)))
    return notes


def time_signature(score: Any) -> str | None:
    import music21

    ts = next(iter(score.recurse().getElementsByClass(music21.meter.TimeSignature)), None)
    return ts.ratioString if ts is not None else None


def tempo(score: Any) -> float | None:
    import music21

    mark = next(iter(score.recurse().getElementsByClass(music21.tempo.MetronomeMark)), None)
    return float(mark.number) if mark is not None and mark.number else None


def piece_key(
    fifths: int | None, chords: list[Chord], last_note: Pitch | None, corrected: str | None
) -> KeyResult | None:
    """The key from the key signature: its major key or the relative minor, whichever the
    chords and the last note point to."""
    if corrected:
        k = Key.parse(corrected).normalized()
        return KeyResult(
            concert=KeyName.of(k), confidence=1.0, signature_confidence=1.0, basis="correction"
        )
    if fifths is None:
        return None
    major = Key(pitch_from_fifths(fifths), "major")
    minor = major.relative
    scores = {}
    for k in (major, minor):
        s = score_key(chords, k.tonic.pc, k.mode) if chords else 0.0
        if last_note is not None and last_note.pc == k.tonic.pc:
            s += 1.5
        scores[k.mode] = s
    total = abs(scores["major"]) + abs(scores["minor"])
    best, other = (major, minor) if scores["major"] >= scores["minor"] else (minor, major)
    if total == 0:
        confidence = 0.5
    else:
        confidence = max(scores.values()) / total if min(scores.values()) >= 0 else 0.75
    confidence = round(min(1.0, max(0.5, confidence)), 3)
    return KeyResult(
        concert=KeyName.of(best),
        confidence=confidence,
        signature_confidence=1.0,
        runners_up=[KeyCandidate(key=KeyName.of(other), probability=round(1 - confidence, 3))],
        basis="signature",
    )


def _mark_chord(mark: ChordMark, moved: Interval) -> Chord | None:
    c = parse_chord(mark.text)
    if c is None:
        return None
    return c.transpose(moved) if moved.steps or moved.semitones else c


def build_song(
    clean: Clean,
    text: PageText,
    read: Read,
    corrections: Corrections | None,
    *,
    source: SourceKind,
    source_name: str | None,
    fingerprint: str,
    fallback_title: str | None,
) -> Song:
    corrections = corrections or Corrections()
    score = scores.parse(read.xml)
    moved = Interval.parse(read.moved)

    melody = melody_of(score)
    last = next((n.concert for n in reversed(melody) if n.concert), None)
    marks = [(m, _mark_chord(m, moved)) for m in text.chords]
    chords = [c for _, c in marks if c is not None]
    key = piece_key(
        scores.key_fifths(score), chords, Pitch.parse(last) if last else None, corrections.key
    )
    key_obj = key.concert.to_key() if key else None

    spelled: dict[str, Chord] = {}
    counts: Counter[str] = Counter()
    order: list[str] = []
    lines = []
    for si in range(len(text.systems)):
        placements = []
        for (mark, c), beat in zip(marks, read.chord_beats, strict=False):
            if mark.system != si:
                continue
            symbol = None
            if c is not None:
                c = c.respell(key_obj) if key_obj else c
                symbol = c.symbol
                spelled.setdefault(symbol, c)
                if symbol not in counts:
                    order.append(symbol)
                counts[symbol] += 1
            placements.append(
                ChordPlacement(chord=symbol, text=mark.text, readable=c is not None, beat=beat)
            )
        box = clean.systems[si] if si < len(clean.systems) else None
        lines.append(
            Line(
                lyrics="",
                chords=placements,
                source=SourceRef(page=box.page, box=box.box) if box else None,
            )
        )
    chord_infos = [
        ChordInfo(
            symbol=s,
            family=spelled[s].family,
            count=counts[s],
            concert=chord_spelling(spelled[s]),
        )
        for s in order
    ]

    notes = [
        Notice(
            code="check_sheet",
            message="Read from the picture: check it against the original. Lyrics and 1st and "
            "2nd ending brackets aren't read yet, and a fermata or ornament may be added "
            "where there is none.",
        )
    ]
    if read.page_instrument != "concert":
        notes.append(
            Notice(
                code="page_transposed",
                message=f"The page reads '{read.part_name or read.page_instrument}', so it is "
                "taken as already written for that instrument and moved to concert pitch. "
                "Correct the page's instrument if that's wrong.",
            )
        )
    unread = [m.text for m, c in marks if c is None]
    if unread:
        notes.append(
            Notice(
                level="warning",
                code="chord_unreadable",
                message="Some chord names couldn't be read: " + ", ".join(unread[:6]) + ".",
            )
        )
    if key is None:
        notes.append(
            Notice(level="warning", code="no_key", message="No key signature could be read.")
        )
    if not any(n.concert for n in melody):
        notes.append(Notice(level="warning", code="no_notes", message="No notes could be read."))

    identity = Identity(
        title=corrections.title or text.title or fallback_title,
        artist=corrections.artist or text.composer,
        source=source,
        source_name=source_name,
        fingerprint=fingerprint,
    )
    return Song(
        identity=identity,
        key=key,
        form=[Section(kind="other", lines=lines)] if lines else [],
        chords=chord_infos,
        melody=Melody(notes=melody, source="sheet_music"),
        timing=Timing(tempo=tempo(score), time_signature=time_signature(score)),
        corrections=corrections,
        notes=notes,
        source_pages=[
            SourcePage(index=i, width=clean.width, height=clean.height)
            for i in range(len(clean.pages))
        ],
        sheet_music=SheetMusicInfo(
            page_instrument=read.page_instrument,
            part_name=read.part_name,
            systems=len(clean.systems),
            measures=read.measures,
            views=clean.views,
        ),
    )
