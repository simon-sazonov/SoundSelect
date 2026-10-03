import pytest

from soundselect.core.chords import chord
from soundselect.core.keys import Key
from soundselect.core.names import chord_root_hint, german_name, key_name, note_name, scale_name
from soundselect.core.pitch import p


@pytest.mark.parametrize(
    ("pitch", "system", "expected"),
    [
        ("Bb", "letters", "B♭"),
        ("Bb", "russian", "си♭"),
        ("Bb", "solfege", "si♭"),
        ("Bb", "german", "B"),
        ("Bb", "both", "B♭ си♭"),
        ("Bb", "none", ""),
        ("G", "russian", "соль"),
        ("F#", "russian", "фа♯"),
        ("C", "solfege", "do"),
        ("A", "russian", "ля"),
    ],
)
def test_note_names(pitch, system, expected):
    assert note_name(p(pitch), system) == expected


def test_long_russian_names():
    assert note_name(p("Bb"), "russian", long=True) == "си-бемоль"
    assert note_name(p("C#"), "russian", long=True) == "до-диез"
    assert note_name(p("C##"), "russian", long=True) == "до-дубль-диез"


@pytest.mark.parametrize(
    ("pitch", "expected"),
    [("B", "H"), ("Bb", "B"), ("Eb", "Es"), ("Ab", "As"), ("Db", "Des"), ("C#", "Cis"),
     ("F##", "Fisis"), ("Bbb", "Heses")],
)  # fmt: skip
def test_german_names(pitch, expected):
    assert german_name(p(pitch)) == expected


def test_key_names():
    assert key_name(Key.parse("Bb"), "russian") == "си-бемоль мажор"
    assert key_name(Key.parse("D"), "russian") == "ре мажор"
    assert key_name(Key.parse("Bb"), "letters") == "B♭ major"
    assert key_name(Key.parse("Bb"), "german") == "B-Dur"
    assert key_name(Key.parse("Bm"), "german") == "h-Moll"
    assert key_name(Key.parse("D"), "both") == "D major · ре мажор"


def test_scale_names():
    assert scale_name("major pentatonic", p("D"), "letters") == "D major pentatonic"
    assert scale_name("major pentatonic", p("D"), "russian") == "Major pentatonic on ре"


def test_chord_root_hint():
    assert chord_root_hint(chord("Am"), "russian") == "ля"
    assert chord_root_hint(chord("Bb7"), "russian") == "си♭"
    assert chord_root_hint(chord("Am"), "letters") is None
