"""Note names, applied only when something is shown.

The staff is always the main display; names are an optional hint under the notes, in the
system the player picks. Data always keeps spelled pitches, so switching names never changes it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from .chords import Chord
from .keys import Key
from .pitch import Pitch, accidental_text

NameSystem = Literal["letters", "russian", "solfege", "german", "both", "none"]
NAME_SYSTEMS: tuple[str, ...] = ("letters", "russian", "solfege", "german", "both", "none")
DEFAULT_NAMES: NameSystem = "russian"

RUSSIAN = {"C": "до", "D": "ре", "E": "ми", "F": "фа", "G": "соль", "A": "ля", "B": "си"}
SOLFEGE = {"C": "do", "D": "re", "E": "mi", "F": "fa", "G": "sol", "A": "la", "B": "si"}
_RUSSIAN_ACCIDENTALS = {1: "диез", 2: "дубль-диез", -1: "бемоль", -2: "дубль-бемоль"}


def german_name(p: Pitch) -> str:
    """German letters: H is B natural, B is B♭; sharps add -is, flats add -es (Es, As)."""
    if p.alter > 0:
        return ("H" if p.letter == "B" else p.letter) + "is" * p.alter
    if p.alter < 0:
        n = -p.alter
        if p.letter == "B":
            return "B" if n == 1 else "Heses"
        if p.letter in ("E", "A"):
            return p.letter + "s" + "es" * (n - 1)
        return p.letter + "es" * n
    return "H" if p.letter == "B" else p.letter


def note_name(p: Pitch, system: NameSystem = "letters", *, long: bool = False) -> str:
    """One note's name: ``B♭``, ``си♭`` (``си-бемоль`` with ``long``), ``si♭``, ``B`` (German)."""
    if system == "none":
        return ""
    if system == "letters":
        return p.display()
    if system == "russian":
        base = RUSSIAN[p.letter]
        if p.alter == 0:
            return base
        if long:
            return f"{base}-{_RUSSIAN_ACCIDENTALS[p.alter]}"
        return base + accidental_text(p.alter, unicode=True)
    if system == "solfege":
        return SOLFEGE[p.letter] + accidental_text(p.alter, unicode=True)
    if system == "german":
        return german_name(p)
    if system == "both":
        return f"{p.display()} {note_name(p, 'russian')}"
    raise ValueError(f"unknown name system {system!r}")


def names_table(pitches: Iterable[Pitch], system: NameSystem) -> dict[str, str]:
    """Display names keyed by the pitch's text without octave, e.g. ``{"Bb": "си♭"}``."""
    return {str(p.pitch_class()): note_name(p.pitch_class(), system) for p in pitches}


def chord_root_hint(chord: Chord, system: NameSystem) -> str | None:
    """The root's name as a hint next to a chord symbol (Am, ля); None for letter systems."""
    if system in ("russian", "solfege", "both"):
        return note_name(chord.root, "solfege" if system == "solfege" else "russian")
    return None


_RUSSIAN_MODES = {"major": "мажор", "minor": "минор"}


def key_name(key: Key, system: NameSystem = "letters") -> str:
    """A key in the chosen system: ``B♭ major``, ``си-бемоль мажор``, ``B-Dur``, ``h-Moll``."""
    if system == "russian":
        return f"{note_name(key.tonic, 'russian', long=True)} {_RUSSIAN_MODES[key.mode]}"
    if system == "solfege":
        return f"{note_name(key.tonic, 'solfege')} {key.mode}"
    if system == "german":
        name = german_name(key.tonic)
        return f"{name}-Dur" if key.mode == "major" else f"{name.lower()}-Moll"
    if system == "both":
        return f"{key.display()} · {key_name(key, 'russian')}"
    return key.display()


def scale_name(label: str, root: Pitch, system: NameSystem = "letters") -> str:
    """A scale's name: ``D major pentatonic``, or ``Major pentatonic on ре`` with Russian names."""
    if system in ("letters", "none"):
        return f"{root.display()} {label}"
    if system == "german":
        return f"{german_name(root)} {label}"
    if system == "both":
        return f"{root.display()} {label} ({note_name(root, 'russian')})"
    return f"{label[:1].upper()}{label[1:]} on {note_name(root, system)}"
