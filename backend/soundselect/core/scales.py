"""Scales to play: the key's pentatonic first, other whole-song scales, and one per chord."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from .chords import Chord
from .keys import Key
from .pitch import Interval, Pitch, iv

ScaleKind = Literal[
    "major_pentatonic", "minor_pentatonic", "blues", "major", "natural_minor", "arpeggio"
]
ScaleRole = Literal["headline", "song", "chord", "alternative"]

FORMULAS: dict[str, tuple[str, ...]] = {
    "major_pentatonic": ("P1", "M2", "M3", "P5", "M6"),
    "minor_pentatonic": ("P1", "m3", "P4", "P5", "m7"),
    "blues": ("P1", "m3", "P4", "d5", "P5", "m7"),
    "major": ("P1", "M2", "M3", "P4", "P5", "M6", "M7"),
    "natural_minor": ("P1", "M2", "m3", "P4", "P5", "m6", "m7"),
}

LABELS: dict[str, str] = {
    "major_pentatonic": "major pentatonic",
    "minor_pentatonic": "minor pentatonic",
    "blues": "blues scale",
    "major": "major scale",
    "natural_minor": "natural minor scale",
    "arpeggio": "chord notes",
}


@dataclass(frozen=True, slots=True)
class Scale:
    kind: ScaleKind
    root: Pitch
    notes: tuple[Pitch, ...]

    @classmethod
    def build(cls, kind: ScaleKind, root: Pitch) -> Scale:
        root = root.pitch_class()
        return cls(kind, root, tuple(root.transpose(iv(s)) for s in FORMULAS[kind]))

    @classmethod
    def arpeggio(cls, chord: Chord) -> Scale:
        return cls("arpeggio", chord.root, tuple(chord.tones))

    def transpose(self, interval: Interval) -> Scale:
        return Scale(
            self.kind,
            self.root.transpose(interval),
            tuple(n.transpose(interval) for n in self.notes),
        )

    @property
    def label(self) -> str:
        """``B♭ major pentatonic``."""
        return f"{self.root.display()} {LABELS[self.kind]}"

    @property
    def pitch_classes(self) -> set[int]:
        return {n.pc for n in self.notes}


@dataclass(frozen=True, slots=True)
class ScaleChoice:
    """A scale offered to the player, with its role and a short reason."""

    scale: Scale
    role: ScaleRole
    reason: str


def song_scales(key: Key, *, bluesy: bool = False) -> list[ScaleChoice]:
    """Whole-song scales, the key's pentatonic first.

    A major key gets its major pentatonic, the minor pentatonic of its relative minor (the same
    five notes from another starting note) and that minor's blues scale. A minor key gets its
    minor pentatonic and blues scale. ``bluesy`` (the major key's own chord is a seventh chord,
    as in a 12-bar blues) adds the blues scale on the key's own note.
    """
    if key.mode == "major":
        rel = key.relative.tonic
        choices = [
            ScaleChoice(
                Scale.build("major_pentatonic", key.tonic),
                "headline",
                "the pentatonic of the song's key",
            ),
            ScaleChoice(
                Scale.build("minor_pentatonic", rel),
                "song",
                "the same five notes starting from the relative minor",
            ),
            ScaleChoice(Scale.build("blues", rel), "song", "the relative minor's blues scale"),
        ]
        if bluesy:
            choices.append(
                ScaleChoice(
                    Scale.build("blues", key.tonic),
                    "song",
                    "the blues sound over the song's seventh chords",
                )
            )
        return choices
    return [
        ScaleChoice(
            Scale.build("minor_pentatonic", key.tonic),
            "headline",
            "the pentatonic of the song's key",
        ),
        ScaleChoice(Scale.build("blues", key.tonic), "song", "the key's blues scale"),
    ]


def chord_scales(chord: Chord, key: Key | None = None) -> list[ScaleChoice]:
    """The scale offered over one chord, followed by any alternatives.

    Major chords get the major pentatonic on the root, minor chords the minor pentatonic,
    dominant sevenths the major pentatonic with blues as the gritty option, half-diminished
    chords the minor pentatonic on their minor third. Sus4 chords get the major pentatonic on
    the fourth (Csus4: F G A C D; C7sus4: the one a whole step below, B♭ C D F G). Power chords
    take whichever pentatonic fits the song's key. Diminished, augmented and anything rarer get
    the chord's own notes, played as an arpeggio.
    """
    root = chord.root
    fam = chord.family
    if fam == "major":
        return [ScaleChoice(Scale.build("major_pentatonic", root), "chord", "major chord")]
    if fam == "minor":
        return [ScaleChoice(Scale.build("minor_pentatonic", root), "chord", "minor chord")]
    if fam == "dominant":
        return [
            ScaleChoice(Scale.build("major_pentatonic", root), "chord", "dominant seventh chord"),
            ScaleChoice(Scale.build("blues", root), "alternative", "the gritty option"),
        ]
    if fam == "half_diminished":
        return [
            ScaleChoice(
                Scale.build("minor_pentatonic", root.transpose(iv("m3"))),
                "chord",
                "minor pentatonic on the chord's minor third",
            )
        ]
    if fam == "suspended":
        if chord.has("4"):
            if chord.has("b7"):
                return [
                    ScaleChoice(
                        Scale.build("major_pentatonic", root.transpose(iv("m7"))),
                        "chord",
                        "major pentatonic a whole step below the root",
                    )
                ]
            return [
                ScaleChoice(
                    Scale.build("major_pentatonic", root.transpose(iv("P4"))),
                    "chord",
                    "major pentatonic on the chord's fourth",
                )
            ]
        return [ScaleChoice(Scale.build("major_pentatonic", root), "chord", "sus2 chord")]
    if fam == "power":
        minor = Scale.build("minor_pentatonic", root)
        major = Scale.build("major_pentatonic", root)
        if key is not None and _outside(major, key) < _outside(minor, key):
            return [ScaleChoice(major, "chord", "power chord; major fits the key")]
        return [ScaleChoice(minor, "chord", "power chord")]
    return [ScaleChoice(Scale.arpeggio(chord), "chord", f"{fam} chord: play its own notes")]


def _outside(scale: Scale, key: Key) -> int:
    key_pcs = {n.pc for n in key.scale}
    return sum(1 for n in scale.notes if n.pc not in key_pcs)


def clashes(chord: Chord, notes: Iterable[Pitch]) -> list[Pitch]:
    """Scale notes that rub against a chord.

    A note clashes when it is not a chord note and sits a half step above one (F over a C
    chord, C over E major), or when it is the minor third of a chord with a major third
    (G over E major).
    """
    pcs = chord.pitch_classes
    minor_third = (chord.root.pc + 3) % 12 if chord.has("3") else None
    out = []
    for n in notes:
        if n.pc in pcs:
            continue
        if any((n.pc - c) % 12 == 1 for c in pcs) or n.pc == minor_third:
            out.append(n)
    return out


def scale_notes_text(notes: Sequence[Pitch]) -> str:
    return " ".join(n.display() for n in notes)
