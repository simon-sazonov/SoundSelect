import pytest

from soundselect.core.chords import chord
from soundselect.core.keyfind import find_key
from soundselect.core.keys import Key

# Chord progressions and the key they are in; after "|", a key that is also acceptable
# (the relative major or minor, which has the same pentatonic notes).
CASES = [
    ("Bb F/A Gm Eb Bb F Gm7 Eb Bb F Eb Bb/D Cm7 F Bb", "Bb"),
    ("Am F C G", "Am|C"),
    ("C G Am F", "C|Am"),
    ("A7 A7 A7 A7 D7 D7 A7 A7 E7 D7 A7 E7", "A"),
    ("Am Dm E7 Am", "Am"),
    ("Em Hm C D", "Em|G"),
    ("C G Am F C G F C", "C"),
    ("E B C#m A", "E"),
    ("Bm F# A E G D Em F#", "Bm"),
    ("G D Em C", "G"),
    ("Am G F E", "Am"),
    ("Dm C Bb A7", "Dm"),
    ("Am C D F Am C E E", "Am"),
    ("C F G C", "C"),
    ("Gm Eb Bb F", "Gm|Bb"),
]


def chords(progression: str):
    return [chord(c) for c in progression.split()]


@pytest.mark.parametrize(("progression", "expected"), CASES)
def test_key_from_chords(progression, expected):
    found = find_key(chords(progression))
    assert found.key in [Key.parse(k) for k in expected.split("|")]


def test_confidence():
    whole_song = find_key(chords(CASES[0][0]))
    assert whole_song.confidence > 0.9
    loop = find_key(chords("Am F C G"))
    # A minor or C major is unsure, but the key signature (no sharps or flats) is clear
    assert loop.signature_confidence > loop.confidence
    assert loop.signature_confidence > 0.6


def test_stated_key_wins_when_the_chords_allow_it():
    found = find_key(chords("Am F C G"), stated=Key.parse("C"))
    assert found.key == Key.parse("C")


def test_no_chords():
    assert find_key([]) is None
