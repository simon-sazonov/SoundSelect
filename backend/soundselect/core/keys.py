"""Keys, key signatures and spelling notes to fit a key."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .pitch import LETTER_FIFTHS, Interval, Pitch, iv

Mode = Literal["major", "minor"]

MAJOR_STEPS = ("P1", "M2", "M3", "P4", "P5", "M6", "M7")
MINOR_STEPS = ("P1", "M2", "m3", "P4", "P5", "m6", "m7")

_KEY_RE = re.compile(
    r"^\s*([A-Ha-h](?:##|bb|#|b|♯|♭)?)\s*(m|min|minor|moll|maj|major|dur|-)?\s*$", re.IGNORECASE
)
# German names with Dur/moll: Es-Dur, fis-moll, B-Dur (B♭), H-Dur (B)
_GERMAN_KEY_RE = re.compile(r"^\s*([A-Ha-h])(isis|eses|is|es|s)?\s*-?\s*(dur|moll)\s*$", re.I)
# Russian and Latin syllables: ля минор, си-бемоль мажор, фа-диез минор, sol major
_SYLLABLES = {
    "до": "C", "ре": "D", "ми": "E", "фа": "F", "соль": "G", "ля": "A", "си": "B",
    "do": "C", "re": "D", "mi": "E", "fa": "F", "sol": "G", "la": "A", "si": "B",
}  # fmt: skip
_ACCIDENTAL_WORDS = {
    "дубль-диез": "##", "дубль-бемоль": "bb", "диез": "#", "бемоль": "b", "sharp": "#",
    "flat": "b", "##": "##", "bb": "bb", "#": "#", "b": "b", "♯": "#", "♭": "b",
}  # fmt: skip
_SYLLABLE_KEY_RE = re.compile(
    r"^\s*("
    + "|".join(_SYLLABLES)
    + r")\s*-?\s*("
    + "|".join(re.escape(a) for a in _ACCIDENTAL_WORDS)
    + r")?\s*(мажор|минор|major|minor|maj|min|m)?\s*$",
    re.IGNORECASE,
)


def pitch_from_fifths(fifths: int) -> Pitch:
    """The pitch class at a position on the line of fifths (0 = C, -2 = Bb, 6 = F#)."""
    letter_fifths = (fifths + 1) % 7 - 1  # -1..5, the natural letter on this column
    alter = (fifths - letter_fifths) // 7
    letter = next(k for k, v in LETTER_FIFTHS.items() if v == letter_fifths)
    return Pitch(letter, alter)


@dataclass(frozen=True, slots=True)
class Key:
    """A major or minor key with a spelled tonic (no octave)."""

    tonic: Pitch
    mode: Mode

    def __post_init__(self) -> None:
        if self.tonic.octave is not None:
            object.__setattr__(self, "tonic", self.tonic.pitch_class())

    @classmethod
    def parse(cls, text: str) -> Key:
        """Read a key name: ``Bb major``, ``Bb``, ``Am``, ``F# minor``, ``c-moll``, ``Es-Dur``,
        ``ля минор``, ``си-бемоль мажор``. A lone lowercase letter means minor (German style)."""
        key = _parse_german(text) or _parse_syllables(text)
        if key is not None:
            return key
        m = _KEY_RE.match(re.sub(r"-(moll|dur)\b", r" \1", text, flags=re.IGNORECASE))
        if not m:
            raise ValueError(f"not a key: {text!r}")
        tonic_text, mode_text = m.groups()
        letter = tonic_text[0].upper()
        if mode_text:
            minor = mode_text.lower() in ("m", "min", "minor", "moll", "-")
        else:
            minor = tonic_text[0].islower()  # German style: a lowercase letter means minor
        if letter == "H":  # German and Russian: H is B natural
            letter = "B"
        tonic = Pitch.parse(letter + tonic_text[1:])
        return cls(tonic, "minor" if minor else "major")

    def __str__(self) -> str:
        return f"{self.tonic} {self.mode}"

    def display(self) -> str:
        """``B♭ major``."""
        return f"{self.tonic.display()} {self.mode}"

    @property
    def fifths(self) -> int:
        """The key signature: sharps as positive numbers, flats as negative."""
        return self.tonic.fifths - (3 if self.mode == "minor" else 0)

    def signature_text(self) -> str:
        n = self.fifths
        if n == 0:
            return "no sharps or flats"
        word = "sharp" if n > 0 else "flat"
        return f"{abs(n)} {word}{'s' if abs(n) > 1 else ''}"

    @property
    def relative(self) -> Key:
        if self.mode == "major":
            return Key(self.tonic.transpose(iv("M6")), "minor")
        return Key(self.tonic.transpose(iv("m3")), "major")

    @property
    def scale(self) -> list[Pitch]:
        """The seven notes of the key (natural minor for minor keys)."""
        steps = MAJOR_STEPS if self.mode == "major" else MINOR_STEPS
        return [self.tonic.transpose(iv(s)) for s in steps]

    def transpose(self, interval: Interval) -> Key:
        return Key(self.tonic.transpose(interval), self.mode)

    def contains(self, pitch: Pitch) -> bool:
        """True when the pitch class belongs to the key's scale."""
        return pitch.pc in {n.pc for n in self.scale}

    def spelling_window(self) -> tuple[int, int]:
        """Line-of-fifths range where a chord root reads naturally in this key.

        A root spelled outside it is respelled (A# in F major becomes Bb), while spellings a
        sheet chose on purpose inside it (G#dim in C major) are kept.
        """
        k = self.fifths
        return (k - 6, k + 8) if self.mode == "major" else (k - 5, k + 9)

    def respell(self, pitch: Pitch) -> Pitch:
        """Respell a pitch only if its spelling is far outside this key."""
        lo, hi = self.spelling_window()
        if lo <= pitch.fifths <= hi:
            return pitch
        return self.spell(pitch.pc, octave=pitch.octave)

    def spell(self, pc: int, octave: int | None = None) -> Pitch:
        """The usual spelling of a pitch class in this key (C major: Db, Eb, F#, Ab, Bb)."""
        k = self.fifths
        lo = k - 5 if self.mode == "major" else k - 3
        for f in range(lo, lo + 12):
            candidate = pitch_from_fifths(f)
            if candidate.pc == pc % 12:
                if abs(candidate.alter) > 1:  # far keys: prefer D over Ebb
                    candidate = pitch_from_fifths(f + 12 if candidate.alter < 0 else f - 12)
                if octave is None:
                    return candidate
                return _with_octave_for_pc(candidate, pc, octave)
        raise AssertionError("unreachable")

    @classmethod
    def from_pc(cls, pc: int, mode: Mode, prefer: Pitch | None = None) -> Key:
        """A key on a pitch class with a normal signature (at most six sharps or flats).

        ``prefer`` is the sheet's own spelling of the tonic, used when both spellings work
        (F# or Gb major).
        """
        shift = 3 if mode == "minor" else 0
        options = []
        for f in range(-6 + shift, 7 + shift):
            t = pitch_from_fifths(f)
            if t.pc == pc % 12:
                options.append(t)
        if prefer is not None:
            for t in options:
                if t == prefer.pitch_class():
                    return cls(t, mode)
        options.sort(key=lambda t: (abs(t.fifths - shift), -t.fifths))
        return cls(options[0], mode)

    def normalized(self) -> Key:
        """The same key with a signature of at most six sharps or flats (A# major -> Bb major)."""
        if -6 <= self.fifths <= 6:
            return self
        return Key.from_pc(self.tonic.pc, self.mode)


def _with_octave_for_pc(spelled: Pitch, pc: int, octave: int) -> Pitch:
    """Give a respelled pitch the octave that keeps the same sound (B#3 sounds as C4)."""
    target = 12 * (octave + 1) + pc % 12
    for o in (octave - 1, octave, octave + 1):
        cand = spelled.at_octave(o)
        if cand.midi == target:
            return cand
    return spelled.at_octave(octave)


ALL_KEYS: tuple[Key, ...] = tuple(
    Key.from_pc(pc, mode) for mode in ("major", "minor") for pc in range(12)
)
"""The 24 major and minor keys, each with its usual spelling."""


def _parse_german(text: str) -> Key | None:
    m = _GERMAN_KEY_RE.match(text)
    if not m:
        return None
    letter, suffix, mode = m.group(1), (m.group(2) or "").lower(), m.group(3).lower()
    upper = letter.upper()
    if upper == "H":
        tonic = Pitch("B", {"": 0, "is": 1, "isis": 2, "es": -1, "eses": -2}.get(suffix, 0))
    elif upper == "B" and not suffix:
        tonic = Pitch("B", -1)  # German B is B♭
    else:
        alter = {"": 0, "is": 1, "isis": 2, "es": -1, "s": -1, "eses": -2}[suffix]
        tonic = Pitch(upper, alter)
    return Key(tonic, "major" if mode == "dur" else "minor")


def _parse_syllables(text: str) -> Key | None:
    m = _SYLLABLE_KEY_RE.match(text)
    if not m:
        return None
    letter = _SYLLABLES[m.group(1).lower()]
    accidental = _ACCIDENTAL_WORDS[m.group(2).lower()] if m.group(2) else ""
    mode = (m.group(3) or "major").lower()
    minor = mode in ("минор", "minor", "min", "m")
    return Key(Pitch.parse(letter + accidental), "minor" if minor else "major")
