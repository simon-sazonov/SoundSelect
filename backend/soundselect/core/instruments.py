"""Instrument profiles and transposition from concert pitch to what the player reads."""

from __future__ import annotations

from dataclasses import dataclass

from .keys import Key
from .pitch import Interval, Pitch, iv, p

MAX_SIGNATURE = 6  # more than six sharps or flats is written with the simpler enharmonic key


@dataclass(frozen=True, slots=True)
class Instrument:
    """How an instrument reads music: its written pitch compared with concert pitch, and ranges.

    Ranges are written pitches. Saxophones share one fingering range, B♭3 to F♯6 without
    altissimo, whatever their size.
    """

    id: str
    name: str
    pitch: str  # the instrument's own key, e.g. "Eb" for alto sax
    interval: Interval  # written = concert + interval
    lowest: Pitch
    highest: Pitch
    comfortable_low: Pitch
    comfortable_high: Pitch
    clef: str = "G2"

    @property
    def display_name(self) -> str:
        if self.pitch == "C":
            return self.name
        return f"{self.name} in {Pitch.parse(self.pitch).display()}"


_SAX_RANGE = {
    "lowest": p("Bb3"),
    "highest": p("F#6"),
    "comfortable_low": p("C4"),
    "comfortable_high": p("C6"),
}

INSTRUMENTS: dict[str, Instrument] = {
    i.id: i
    for i in (
        Instrument("alto_sax", "Alto sax", "Eb", iv("M6"), **_SAX_RANGE),
        Instrument("tenor_sax", "Tenor sax", "Bb", iv("M9"), **_SAX_RANGE),
        Instrument("soprano_sax", "Soprano sax", "Bb", iv("M2"), **_SAX_RANGE),
        Instrument("baritone_sax", "Baritone sax", "Eb", iv("M13"), **_SAX_RANGE),
        Instrument(
            "concert",
            "Concert pitch",
            "C",
            iv("P1"),
            lowest=p("A0"),
            highest=p("C8"),
            comfortable_low=p("C4"),
            comfortable_high=p("C6"),
        ),
    )
}
DEFAULT_INSTRUMENT = "alto_sax"


def get_instrument(instrument_id: str) -> Instrument:
    try:
        return INSTRUMENTS[instrument_id]
    except KeyError:
        known = ", ".join(INSTRUMENTS)
        raise ValueError(f"unknown instrument {instrument_id!r}; known: {known}") from None


@dataclass(frozen=True, slots=True)
class Transposition:
    """Concert pitch to written pitch for one instrument and one song key.

    The interval is the instrument's, adjusted by an enharmonic step when the written key would
    need more than six sharps or flats: concert E major is written for alto sax in D♭ major
    (5 flats) instead of C♯ major (7 sharps), so every note and chord moves by a diminished
    seventh instead of a major sixth.
    """

    instrument: Instrument
    interval: Interval
    concert_key: Key | None
    written_key: Key | None

    @property
    def respelled(self) -> bool:
        return self.interval != self.instrument.interval

    @classmethod
    def for_key(cls, instrument: Instrument, concert_key: Key | None) -> Transposition:
        interval = instrument.interval
        if concert_key is None:
            return cls(instrument, interval, None, None)
        written = concert_key.transpose(interval)
        if written.fifths > MAX_SIGNATURE:
            interval = Interval(interval.steps + 1, interval.semitones)
        elif written.fifths < -MAX_SIGNATURE:
            interval = Interval(interval.steps - 1, interval.semitones)
        return cls(instrument, interval, concert_key, concert_key.transpose(interval))

    def pitch(self, concert: Pitch) -> Pitch:
        return concert.transpose(self.interval)

    def to_concert(self, written: Pitch) -> Pitch:
        return written.transpose(-self.interval)
