import pytest

from soundselect.core.chords import chord
from soundselect.core.keys import Key
from soundselect.core.pitch import p
from soundselect.core.scales import Scale, chord_scales, clashes, song_scales


def notes(scale: Scale) -> list[str]:
    return [str(n) for n in scale.notes]


# The plan's table: the scale offered over each kind of chord.
@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("C", ["C", "D", "E", "G", "A"]),
        ("Am", ["A", "C", "D", "E", "G"]),
        ("G7", ["G", "A", "B", "D", "E"]),
        ("Bm7b5", ["D", "F", "G", "A", "C"]),
        ("Bdim", ["B", "D", "F"]),
        ("Csus4", ["F", "G", "A", "C", "D"]),
        ("C7sus4", ["Bb", "C", "D", "F", "G"]),
        ("Csus2", ["C", "D", "E", "G", "A"]),
        ("Caug", ["C", "E", "G#"]),
    ],
)
def test_chord_scale(symbol, expected):
    assert notes(chord_scales(chord(symbol))[0].scale) == expected


def test_dominant_gets_blues_as_the_alternative():
    choices = chord_scales(chord("G7"))
    assert [c.role for c in choices] == ["chord", "alternative"]
    assert notes(choices[1].scale) == ["G", "Bb", "C", "Db", "D", "F"]


def test_power_chord_follows_the_key():
    assert chord_scales(chord("A5"), Key.parse("C"))[0].scale.kind == "minor_pentatonic"
    assert chord_scales(chord("A5"), Key.parse("A"))[0].scale.kind == "major_pentatonic"


def test_major_key_scales():
    choices = song_scales(Key.parse("G"))
    assert [(c.role, c.scale.label) for c in choices] == [
        ("headline", "G major pentatonic"),
        ("song", "E minor pentatonic"),
        ("song", "E blues scale"),
    ]


def test_minor_key_scales():
    choices = song_scales(Key.parse("Am"))
    assert [(c.role, c.scale.label) for c in choices] == [
        ("headline", "A minor pentatonic"),
        ("song", "A blues scale"),
    ]


def test_bluesy_major_key_adds_its_own_blues_scale():
    labels = [c.scale.label for c in song_scales(Key.parse("A"), bluesy=True)]
    assert labels[-1] == "A blues scale"


def test_clashes():
    g_pentatonic = Scale.build("major_pentatonic", p("G")).notes
    assert [str(n) for n in clashes(chord("D"), g_pentatonic)] == ["G"]  # a half step above F#
    assert [str(n) for n in clashes(chord("G"), g_pentatonic)] == []
    assert [str(n) for n in clashes(chord("C"), [p("F")])] == ["F"]
    assert [str(n) for n in clashes(chord("E"), [p("G")])] == ["G"]  # minor third over major
    a_minor = Scale.build("minor_pentatonic", p("A")).notes
    assert clashes(chord("Am"), a_minor) == []
