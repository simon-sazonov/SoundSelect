"""Spelled pitches and intervals.

A pitch keeps its spelling, so C# and Db stay different, just as they look different on the
staff. The text form is plain ASCII: a letter, then ``#``/``##`` or ``b``/``bb``, then an
optional octave in scientific pitch notation (middle C is ``C4``): ``"C"``, ``"Bb"``,
``"F#4"``, ``"Ebb3"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LETTERS = "CDEFGAB"
NATURAL_SEMITONES = (0, 2, 4, 5, 7, 9, 11)
# Position of each natural letter on the line of fifths (C = 0, G = 1, F = -1, ...).
LETTER_FIFTHS = {"F": -1, "C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5}

_PITCH_RE = re.compile(r"^([A-Ga-g])(##|bb|#|b|x|♯♯|♭♭|♯|♭|𝄪|𝄫)?(-?\d+)?$")
_ALTER_TEXT = {"#": 1, "##": 2, "x": 2, "b": -1, "bb": -2}
_ALTER_TEXT.update({"♯": 1, "♯♯": 2, "𝄪": 2, "♭": -1, "♭♭": -2, "𝄫": -2})


def accidental_text(alter: int, *, unicode: bool = False) -> str:
    """The accidental for an alteration: ``#``/``b`` in ASCII, ``♯``/``♭``/``𝄪`` in unicode."""
    if unicode:
        if alter == 2:
            return "𝄪"
        if alter == -2:
            return "𝄫"
        return "♯" * alter if alter > 0 else "♭" * -alter
    return "#" * alter if alter > 0 else "b" * -alter


@dataclass(frozen=True, slots=True)
class Pitch:
    """A spelled pitch. Without an octave it stands for a pitch class with a spelling."""

    letter: str
    alter: int = 0
    octave: int | None = None

    def __post_init__(self) -> None:
        if self.letter not in LETTERS:
            raise ValueError(f"not a note letter: {self.letter!r}")

    @classmethod
    def parse(cls, text: str) -> Pitch:
        m = _PITCH_RE.match(text.strip())
        if not m:
            raise ValueError(f"not a pitch: {text!r}")
        letter, acc, octave = m.groups()
        return cls(letter.upper(), _ALTER_TEXT.get(acc or "", 0), int(octave) if octave else None)

    def __str__(self) -> str:
        octave = "" if self.octave is None else str(self.octave)
        return f"{self.letter}{accidental_text(self.alter)}{octave}"

    def __repr__(self) -> str:
        return f"Pitch({str(self)!r})"

    def display(self, *, octave: bool = False) -> str:
        """Letter name with unicode accidentals, e.g. ``B♭``."""
        oct_text = str(self.octave) if octave and self.octave is not None else ""
        return f"{self.letter}{accidental_text(self.alter, unicode=True)}{oct_text}"

    @property
    def step(self) -> int:
        """Index of the letter, C = 0 ... B = 6."""
        return LETTERS.index(self.letter)

    @property
    def pc(self) -> int:
        """Pitch class, 0-11 (C = 0)."""
        return (NATURAL_SEMITONES[self.step] + self.alter) % 12

    @property
    def fifths(self) -> int:
        """Position on the line of fifths: C = 0, G = 1, F# = 6, Bb = -2."""
        return LETTER_FIFTHS[self.letter] + 7 * self.alter

    @property
    def midi(self) -> int:
        """MIDI note number (C4 = 60). Needs an octave."""
        if self.octave is None:
            raise ValueError(f"{self} has no octave")
        return 12 * (self.octave + 1) + NATURAL_SEMITONES[self.step] + self.alter

    @property
    def diatonic_index(self) -> int:
        """Letter steps counted from C0, for comparing staff positions."""
        if self.octave is None:
            raise ValueError(f"{self} has no octave")
        return 7 * self.octave + self.step

    def pitch_class(self) -> Pitch:
        """The same spelling without an octave."""
        return Pitch(self.letter, self.alter)

    def at_octave(self, octave: int) -> Pitch:
        return Pitch(self.letter, self.alter, octave)

    def transpose(self, interval: Interval) -> Pitch:
        """Move by an interval, keeping correct spelling (Bb up a major sixth is G, not F##)."""
        total = self.step + interval.steps
        letter = LETTERS[total % 7]
        natural = NATURAL_SEMITONES[total % 7]
        if self.octave is None:
            alter = (self.pc + interval.semitones - natural + 6) % 12 - 6
            return Pitch(letter, alter)
        octave = self.octave + total // 7
        alter = self.midi + interval.semitones - (12 * (octave + 1) + natural)
        return Pitch(letter, alter, octave)

    def same_class(self, other: Pitch) -> bool:
        """True when both sound the same pitch class (C# and Db do)."""
        return self.pc == other.pc


@dataclass(frozen=True, slots=True)
class Interval:
    """An interval as letter steps plus semitones: a major sixth is 5 steps and 9 semitones."""

    steps: int
    semitones: int

    _PERFECT = frozenset({0, 3, 4})
    _BASE = (0, 2, 4, 5, 7, 9, 11)

    @classmethod
    def parse(cls, name: str) -> Interval:
        """Read names like ``M6``, ``m3``, ``P5``, ``A4``, ``d7``; a leading ``-`` means down."""
        m = re.match(r"^(-)?(P|M|m|A|d|AA|dd)(\d+)$", name.strip())
        if not m:
            raise ValueError(f"not an interval: {name!r}")
        down, quality, number = m.group(1), m.group(2), int(m.group(3))
        if number < 1:
            raise ValueError(f"not an interval: {name!r}")
        steps = number - 1
        simple = steps % 7
        base = cls._BASE[simple] + 12 * (steps // 7)
        if simple in cls._PERFECT:
            offsets = {"P": 0, "A": 1, "AA": 2, "d": -1, "dd": -2}
        else:
            offsets = {"M": 0, "m": -1, "A": 1, "AA": 2, "d": -2, "dd": -3}
        if quality not in offsets:
            raise ValueError(f"not an interval: {name!r}")
        iv = cls(steps, base + offsets[quality])
        return -iv if down else iv

    @classmethod
    def between(cls, low: Pitch, high: Pitch) -> Interval:
        """The interval from one pitch to another (both need octaves)."""
        return cls(high.diatonic_index - low.diatonic_index, high.midi - low.midi)

    def __add__(self, other: Interval) -> Interval:
        return Interval(self.steps + other.steps, self.semitones + other.semitones)

    def __sub__(self, other: Interval) -> Interval:
        return Interval(self.steps - other.steps, self.semitones - other.semitones)

    def __neg__(self) -> Interval:
        return Interval(-self.steps, -self.semitones)

    @property
    def name(self) -> str:
        """``M6``, ``d7``, ``P8``; downward intervals get a leading ``-``."""
        if self.steps < 0 or (self.steps == 0 and self.semitones < 0):
            return "-" + (-self).name
        simple = self.steps % 7
        base = self._BASE[simple] + 12 * (self.steps // 7)
        diff = self.semitones - base
        if simple in self._PERFECT:
            quality = {0: "P", 1: "A", 2: "AA", -1: "d", -2: "dd"}.get(diff)
        else:
            quality = {0: "M", -1: "m", 1: "A", 2: "AA", -2: "d", -3: "dd"}.get(diff)
        if quality is None:
            return f"({self.steps},{self.semitones})"
        return f"{quality}{self.steps + 1}"

    def __str__(self) -> str:
        return self.name


def iv(name: str) -> Interval:
    """Shorthand for :meth:`Interval.parse`."""
    return Interval.parse(name)


def p(text: str) -> Pitch:
    """Shorthand for :meth:`Pitch.parse`."""
    return Pitch.parse(text)
