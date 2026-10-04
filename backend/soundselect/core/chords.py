"""Chord symbols: reading them, their notes and their type.

A chord is a root, a quality suffix (``m7``, ``maj7``, ``sus4``, ...) and an optional bass
note for slash chords such as ``C/E``. The quality is normalized (``min7``, ``-7`` and ``mi7``
all become ``m7``; ``Δ7`` becomes ``maj7``; ``ø`` becomes ``m7b5``), and the chord knows its
notes as degrees above the root, which decide its family and so the scale offered over it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from .keys import Key
from .pitch import Interval, Pitch, iv

ChordFamily = Literal[
    "major",
    "minor",
    "dominant",
    "half_diminished",
    "diminished",
    "augmented",
    "suspended",
    "power",
]

DEGREES: dict[str, Interval] = {
    d: iv(name)
    for d, name in {
        "1": "P1",
        "2": "M2",
        "b3": "m3",
        "3": "M3",
        "4": "P4",
        "b5": "d5",
        "5": "P5",
        "#5": "A5",
        "6": "M6",
        "bb7": "d7",
        "b7": "m7",
        "7": "M7",
        "b9": "m9",
        "9": "M9",
        "#9": "A9",
        "11": "P11",
        "#11": "A11",
        "b13": "m13",
        "13": "M13",
    }.items()
}

# Cyrillic letters that look like chord letters, as text recognition or a mixed keyboard
# layout can produce them.
_LOOKALIKES = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "м": "m"})

_CHORD_RE = re.compile(r"^([A-H])(#|b)?(.*?)(?:/([A-H])(#|b)?)?$")
_QUALITY_RE = re.compile(
    r"^(?P<tri>m(?!aj)|dim|aug)?(?P<maj>maj)?(?P<ext>69|6|7|9|11|13|5|2|4)?"
    r"(?P<mods>(?:sus[24]|add(?:2|4|6|9|11|13)|[b#](?:5|9|11|13)|alt|no[35])*)$"
)
_MOD_RE = re.compile(r"sus[24]|add\d+|[b#]\d+|alt|no[35]")


@dataclass(frozen=True, slots=True)
class Chord:
    """A chord symbol with its root, normalized quality, bass note and chord tones."""

    root: Pitch
    quality: str = ""
    bass: Pitch | None = None
    degrees: tuple[str, ...] = ("1", "3", "5")
    family: ChordFamily = "major"

    @property
    def symbol(self) -> str:
        """ASCII symbol, e.g. ``Bb/D`` or ``F#m7b5``."""
        bass = f"/{self.bass}" if self.bass else ""
        return f"{self.root}{self.quality}{bass}"

    def __str__(self) -> str:
        return self.symbol

    def display(self) -> str:
        """Symbol with unicode accidentals, e.g. ``B♭/D`` or ``F♯m7♭5``."""
        bass = f"/{self.bass.display()}" if self.bass else ""
        return f"{self.root.display()}{quality_display(self.quality)}{bass}"

    @property
    def tones(self) -> list[Pitch]:
        """Chord notes from the root up, spelled from the root (E7: E G# B D)."""
        return [self.root.transpose(DEGREES[d]) for d in self.degrees]

    @property
    def pitch_classes(self) -> set[int]:
        pcs = {t.pc for t in self.tones}
        if self.bass is not None:
            pcs.add(self.bass.pc)
        return pcs

    def has(self, degree: str) -> bool:
        return degree in self.degrees

    def transpose(self, interval: Interval) -> Chord:
        bass = self.bass.transpose(interval) if self.bass else None
        return replace(self, root=self.root.transpose(interval), bass=bass)

    def respell(self, key: Key) -> Chord:
        """Respell a root or bass that is far outside the key (A# in F major becomes Bb).

        A bass that is one of the chord's own notes takes that note's spelling (E/G#).
        """
        root = key.respell(self.root)
        chord = replace(self, root=root)
        if self.bass is None:
            return chord
        for tone in chord.tones:
            if tone.pc == self.bass.pc:
                return replace(chord, bass=tone)
        return replace(chord, bass=key.respell(self.bass))


def quality_display(quality: str) -> str:
    """``m7b5`` -> ``m7♭5``, ``7#9`` -> ``7♯9``."""
    return re.sub(r"b(?=\d)", "♭", quality).replace("#", "♯")


def _normalize_quality(q: str) -> str:
    q = q.replace("♯", "#").replace("♭", "b").replace("–", "-").replace("−", "-")
    q = q.replace("6/9", "69").replace("6-9", "69")
    q = re.sub(r"[()\[\],\s]", "", q)
    q = q.replace("ø7", "m7b5").replace("ø", "m7b5").replace("Ø", "m7b5")
    q = q.replace("°", "dim").replace("º", "dim").replace("Δ", "maj")
    q = re.sub(r"^o(?=7)", "dim", q)  # "Co7"; a lone "o" is left out so words like "Do" stay words
    q = re.sub(r"^(?:min|mi)(?=[^n]|$)", "m", q)
    q = re.sub(r"^(?:m|min|-)(?:/)?(?:maj|Maj|MAJ|M|ma|Ma|j|Δ)(?=7|9|11|13)", "mmaj", q)
    q = re.sub(r"^-(?=\d|$|add|sus)", "m", q)
    q = re.sub(r"^\+", "aug", q)
    q = re.sub(r"^(?:Maj|MAJ|Ma|ma|M|j)(?=\d|$|add)", "maj", q)
    q = re.sub(r"(?<=\d)-(?=5|9|11|13)", "b", q)
    q = re.sub(r"(?<=\d)\+(?=5|9|11)", "#", q)
    q = re.sub(r"(?<=\d)\+$", "#5", q)
    q = re.sub(r"sus(?![24])", "sus4", q)
    return q


def _degrees_for(match: re.Match[str]) -> tuple[tuple[str, ...], ChordFamily] | None:
    tri, maj, ext, mods = (
        match.group("tri"),
        match.group("maj"),
        match.group("ext"),
        match.group("mods"),
    )
    third: str | None = "3"
    fifth: str | None = "5"
    seventh: str | None = None
    extra: list[str] = []
    power = False
    if tri == "m":
        third = "b3"
    elif tri == "dim":
        third, fifth = "b3", "b5"
    elif tri == "aug":
        fifth = "#5"

    if ext == "5":
        if tri or maj:
            return None
        power, third = True, None
    elif ext == "2":
        extra.append("2")
    elif ext == "4":
        third = "4"
    elif ext == "6":
        extra.append("6")
    elif ext == "69":
        extra += ["6", "9"]
    elif ext in ("7", "9", "11", "13"):
        if maj:
            seventh = "7"
        elif tri == "dim" and ext == "7":
            seventh = "bb7"
        else:
            seventh = "b7"
        extra += {"7": [], "9": ["9"], "11": ["9", "11"], "13": ["9", "13"]}[ext]
    elif maj and tri == "m":
        return None  # "mmaj" without a number

    for mod in _MOD_RE.findall(mods or ""):
        if mod == "sus2":
            third = "2"
        elif mod == "sus4":
            third = "4"
        elif mod.startswith("add"):
            extra.append(mod[3:])
        elif mod in ("b5", "#5"):
            fifth = mod
        elif mod in ("b9", "#9"):
            extra = [d for d in extra if d != "9"] + [mod]
        elif mod == "#11":
            extra = [d for d in extra if d != "11"] + [mod]
        elif mod == "b13":
            extra = [d for d in extra if d != "13"] + [mod]
        elif mod == "alt":
            seventh, fifth = "b7", None
            extra = [d for d in extra if d not in ("9", "11", "13")] + ["b9", "#9", "#11", "b13"]
        elif mod == "no3":
            third = None
        elif mod == "no5":
            fifth = None
        else:
            return None

    degrees = ["1"] + [d for d in (third, fifth, seventh) if d] + extra
    unknown = [d for d in degrees if d not in DEGREES]
    if unknown:
        return None
    degrees = sorted(set(degrees), key=lambda d: DEGREES[d].semitones)

    if power or third is None:
        family: ChordFamily = "power"
    elif third in ("2", "4"):
        family = "suspended"
    elif third == "b3":
        if fifth == "b5":
            family = "half_diminished" if seventh == "b7" else "diminished"
        else:
            family = "minor"
    elif fifth == "#5":
        family = "augmented"
    elif seventh == "b7":
        family = "dominant"
    else:
        family = "major"
    return tuple(degrees), family


def _canonical_quality(normalized: str, match: re.Match[str]) -> str:
    q = normalized
    if q == "maj":
        return ""
    if match.group("ext") == "4" and not match.group("tri") and not match.group("maj"):
        q = "sus4" + q[1:]
    q = re.sub(r"^mmaj(\d+)", r"m(maj\1)", q)
    return q.replace("69", "6/9")


def parse_quality(text: str) -> tuple[str, tuple[str, ...], ChordFamily] | None:
    """Read a chord quality suffix; returns (normalized quality, degrees, family) or None."""
    normalized = _normalize_quality(text)
    match = _QUALITY_RE.match(normalized)
    if not match:
        return None
    built = _degrees_for(match)
    if built is None:
        return None
    degrees, family = built
    return _canonical_quality(normalized, match), degrees, family


def _letter(letter: str, acc: str | None, b_is_flat: bool) -> Pitch:
    if letter == "H":
        return Pitch("B", {"#": 1, "b": -1}.get(acc or "", 0))
    if letter == "B" and b_is_flat and not acc:
        return Pitch("B", -1)
    return Pitch(letter, {"#": 1, "b": -1}.get(acc or "", 0))


def parse_chord(text: str, *, b_is_flat: bool = False) -> Chord | None:
    """Read a chord symbol such as ``Am7``, ``F#m7b5``, ``Bb/D``, ``Hm`` or ``Csus4``.

    ``H`` is always B natural, as on Russian and German sheets. ``b_is_flat`` makes a plain
    ``B`` mean B♭, for sheets that use both B and H. Returns None when the text is not a chord.
    """
    t = text.strip().translate(_LOOKALIKES).replace("♯", "#").replace("♭", "b")
    m = _CHORD_RE.match(t)
    if not m:
        return None
    letter, acc, quality, bass_letter, bass_acc = m.groups()
    parsed = parse_quality(quality)
    if parsed is None:
        return None
    canonical, degrees, family = parsed
    root = _letter(letter, acc, b_is_flat)
    bass = _letter(bass_letter, bass_acc, b_is_flat) if bass_letter else None
    if bass is not None and bass.pc == root.pc:
        bass = None  # "C/C" is just C
    return Chord(root, canonical, bass, degrees, family)


def chord(text: str) -> Chord:
    """Parse a chord symbol, raising ValueError when it is not one (handy in code and tests)."""
    c = parse_chord(text)
    if c is None:
        raise ValueError(f"not a chord: {text!r}")
    return c


_MUSICXML_KIND = {
    "major": "major",
    "minor": "minor",
    "dominant": "dominant",
    "half_diminished": "half-diminished",
    "diminished": "diminished",
    "augmented": "augmented",
    "suspended": "suspended-fourth",
    "power": "power",
}


def musicxml_kind(c: Chord) -> str:
    """The MusicXML ``<kind>`` value closest to the chord (its text is written separately)."""
    d = set(c.degrees)
    if c.family == "major":
        if "7" in d:
            return "major-13th" if "13" in d else "major-ninth" if "9" in d else "major-seventh"
        return "major-sixth" if "6" in d else "major"
    if c.family == "minor":
        if "7" in d:
            return "major-minor"
        if "b7" in d:
            if "13" in d:
                return "minor-13th"
            return "minor-11th" if "11" in d else "minor-ninth" if "9" in d else "minor-seventh"
        return "minor-sixth" if "6" in d else "minor"
    if c.family == "dominant":
        return (
            "dominant-13th"
            if "13" in d
            else "dominant-11th"
            if "11" in d
            else ("dominant-ninth" if "9" in d else "dominant")
        )
    if c.family == "diminished":
        return "diminished-seventh" if "bb7" in d else "diminished"
    if c.family == "augmented":
        return "augmented-seventh" if "b7" in d else "augmented"
    if c.family == "suspended":
        return "suspended-second" if "2" in d and "4" not in d else "suspended-fourth"
    return _MUSICXML_KIND[c.family]
