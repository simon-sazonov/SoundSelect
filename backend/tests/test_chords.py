import pytest

from soundselect.core.chords import chord, parse_chord
from soundselect.core.keys import Key
from soundselect.core.pitch import iv


@pytest.mark.parametrize(
    ("text", "symbol", "family"),
    [
        ("Am", "Am", "minor"),
        ("Amin", "Am", "minor"),
        ("A-", "Am", "minor"),
        ("Cmi7", "Cm7", "minor"),
        ("Cmaj7", "Cmaj7", "major"),
        ("CM7", "Cmaj7", "major"),
        ("CΔ7", "Cmaj7", "major"),
        ("G7", "G7", "dominant"),
        ("C9", "C9", "dominant"),
        ("F#m7b5", "F#m7b5", "half_diminished"),
        ("Bø", "Bm7b5", "half_diminished"),
        ("Cm7-5", "Cm7b5", "half_diminished"),
        ("B°", "Bdim", "diminished"),
        ("Bo7", "Bdim7", "diminished"),
        ("C+", "Caug", "augmented"),
        ("Csus", "Csus4", "suspended"),
        ("Csus2", "Csus2", "suspended"),
        ("C7sus4", "C7sus4", "suspended"),
        ("A5", "A5", "power"),
        ("Bb/D", "Bb/D", "major"),
        ("C69", "C6/9", "major"),
        ("C6/9", "C6/9", "major"),
        ("CmM7", "Cm(maj7)", "minor"),
        ("Hm", "Bm", "minor"),  # H is B natural
        ("H7", "B7", "dominant"),
        ("Ам", "Am", "minor"),  # Cyrillic letters that look like Latin ones
        ("E7/G#", "E7/G#", "dominant"),
    ],
)
def test_parse(text, symbol, family):
    c = parse_chord(text)
    assert c is not None
    assert c.symbol == symbol
    assert c.family == family


@pytest.mark.parametrize("text", ["Do", "Go", "And", "I", "Hello", "Am7xyz", "N.C.", ""])
def test_words_are_not_chords(text):
    assert parse_chord(text) is None


def test_b_means_b_flat_on_sheets_that_use_h():
    assert parse_chord("B", b_is_flat=True).symbol == "Bb"
    assert parse_chord("B").symbol == "B"


def test_display():
    assert chord("Bb/D").display() == "B♭/D"
    assert chord("F#m7b5").display() == "F♯m7♭5"


def test_tones_are_spelled_from_the_root():
    assert [str(t) for t in chord("E7").tones] == ["E", "G#", "B", "D"]
    assert [str(t) for t in chord("Bbm7").tones] == ["Bb", "Db", "F", "Ab"]
    assert [str(t) for t in chord("Bdim7").tones] == ["B", "D", "F", "Ab"]


@pytest.mark.parametrize(
    ("concert", "alto"),
    [("Bb", "G"), ("F/A", "D/F#"), ("Gm7", "Em7"), ("Eb", "C"), ("Cm7", "Am7"), ("Bb/D", "G/B")],
)
def test_transpose_for_alto(concert, alto):
    assert chord(concert).transpose(iv("M6")).symbol == alto


def test_respell_to_fit_the_key():
    assert chord("A#").respell(Key.parse("F")).symbol == "Bb"
    assert chord("Gb/Bb").respell(Key.parse("E")).symbol == "F#/A#"
    assert chord("C#m").respell(Key.parse("E")).symbol == "C#m"
