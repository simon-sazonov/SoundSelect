"""The piece as notation: the notes homr read on each page joined into one score, the chord
names put back over their beats, the title and composer added, and everything brought to
concert pitch (a page already written for alto sax is moved down a major sixth first).

The concert-pitch MusicXML is what the library keeps; the score for an instrument is made from
it when asked for, with the same interval the music core chose for the song's key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..core.instruments import get_instrument
from ..core.pitch import Interval
from .models import ChordMark

MAX_FIFTHS = 6


def _m21() -> Any:
    import music21

    return music21


def parse(xml: str) -> Any:
    m21 = _m21()
    return m21.converter.parseData(xml, format="musicxml", forceSource=True)


def to_xml(score: Any) -> str:
    """MusicXML text, without the explicit 'natural' music21 leaves on moved chord names."""
    m21 = _m21()
    exporter = m21.musicxml.m21ToXml.GeneralObjectExporter(score)
    xml = exporter.parse().decode("utf-8")
    return re.sub(r"\s*<(root|bass)-alter>0</(root|bass)-alter>", "", xml)


def m21_interval(interval: Interval) -> Any:
    m21 = _m21()
    if interval.semitones == 0 and interval.steps == 0:
        return m21.interval.Interval("P1")
    if interval.name.startswith("-"):
        return m21.interval.Interval(interval.name[1:]).reverse()
    return m21.interval.Interval(interval.name)


def key_fifths(score: Any) -> int | None:
    m21 = _m21()
    sig = next(iter(score.recurse().getElementsByClass(m21.key.KeySignature)), None)
    return int(sig.sharps) if sig is not None else None


def transpose(score: Any, interval: Interval) -> Any:
    """The score moved by an interval, chord names included."""
    if interval.semitones == 0 and interval.steps == 0:
        return score
    return score.transpose(m21_interval(interval))


def _enharmonic(interval: Interval) -> Interval:
    """The same distance one letter further (M6 up and d7 up both sound 9 half steps)."""
    return Interval(interval.steps + (1 if interval.semitones >= 0 else -1), interval.semitones)


def to_concert(score: Any, page_instrument: str | None) -> tuple[Any, Interval]:
    """The score in concert pitch, and the interval it was moved by."""
    if page_instrument is None or page_instrument == "concert":
        return score, Interval(0, 0)
    down = -get_instrument(page_instrument).interval
    moved = transpose(score, down)
    fifths = key_fifths(moved)
    if fifths is not None and abs(fifths) > MAX_FIFTHS:
        down = _enharmonic(down)
        moved = transpose(score, down)
    return moved, down


def _measures(part: Any) -> list[Any]:
    m21 = _m21()
    return list(part.getElementsByClass(m21.stream.Measure))


def _top_staff(score: Any) -> Any:
    return score.parts[0]


def join_pages(pages: list[str]) -> Any:
    """One score from the MusicXML of every page, bars numbered on from page to page."""
    if not pages:
        raise ValueError("no pages")
    first = parse(pages[0])
    for xml in pages[1:]:
        more = parse(xml)
        for part, extra in zip(first.parts, more.parts, strict=False):
            for m in _measures(extra):
                part.append(m)
    for part in first.parts:
        for n, m in enumerate(_measures(part), start=1):
            m.number = n
    return first


def m21_chord_figure(text: str) -> str:
    """A chord name as music21 writes it: flats as '-' ('Bb7' -> 'B-7'), H as B natural."""
    text = re.sub(r"(^|/)H", r"\1B", text)
    return re.sub(r"(^|/)([A-G])b", r"\1\2-", text)


def chord_from_figure(figure: str) -> str:
    """music21's chord figure back to the ASCII symbol the Song uses ('B-7' -> 'Bb7')."""
    return re.sub(r"(^|/)([A-G])-", r"\1\2b", figure)


def add_chords(score: Any, chords: list[ChordMark]) -> list[float | None]:
    """Put the chord names over the score, each on the note nearest its place in its bar.
    Returns each chord's beat from the start (in quarter notes), or None when it found no bar."""
    m21 = _m21()
    measures = _measures(_top_staff(score))
    beats: list[float | None] = []
    for mark in chords:
        beats.append(None)
        if not 1 <= mark.measure <= len(measures):
            continue
        m = measures[mark.measure - 1]
        try:
            symbol = m21.harmony.ChordSymbol(m21_chord_figure(mark.text))
        except Exception:
            continue  # a name music21 can't read stays out of the notation
        length = float(m.barDuration.quarterLength) if m.barDuration else 4.0
        target = mark.position * length
        onsets = sorted({float(n.offset) for n in m.notesAndRests}) or [0.0]
        offset = min(onsets, key=lambda x: abs(x - target))
        symbol.writeAsChord = False
        m.insert(offset, symbol)
        beats[-1] = float(m.offset) + offset
    return beats


def set_title(score: Any, title: str | None, composer: str | None) -> None:
    m21 = _m21()
    score.metadata = m21.metadata.Metadata()
    if title:
        score.metadata.title = title
    if composer:
        score.metadata.composer = composer


def name_parts(score: Any, part_name: str) -> None:
    """Name every part, with no short name repeated on the following lines."""
    m21 = _m21()
    for part in score.parts:
        part.partName = part_name
        part.partAbbreviation = None
        for inst in part.recurse().getElementsByClass(m21.instrument.Instrument):
            inst.partName = part_name
            inst.partAbbreviation = None
            inst.instrumentName = part_name
            inst.instrumentAbbreviation = None


def set_metadata(score: Any, title: str | None, composer: str | None, part_name: str) -> None:
    set_title(score, title, composer)
    name_parts(score, part_name)


@dataclass
class Built:
    xml: str  # concert pitch
    moved: Interval  # how far the page was moved to reach concert pitch
    measures: int
    chord_beats: list[float | None]  # for each chord mark


def build(
    pages: list[str],
    chords: list[ChordMark],
    *,
    title: str | None,
    composer: str | None,
    page_instrument: str | None,
) -> Built:
    score = join_pages(pages)
    beats = add_chords(score, chords)
    score, moved = to_concert(score, page_instrument)
    set_metadata(score, title, composer, "Concert pitch")
    count = len(_measures(_top_staff(score)))
    return Built(to_xml(score), moved, count, beats)


def for_instrument(concert_xml: str, interval: Interval, part_name: str) -> str:
    """The concert score written for an instrument (moved by the song's own interval)."""
    score = transpose(parse(concert_xml), interval)
    name_parts(score, part_name)
    return to_xml(score)
