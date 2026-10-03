import pytest

from soundselect.core.pitch import Interval, Pitch, iv, p


@pytest.mark.parametrize(
    ("text", "letter", "alter", "octave"),
    [
        ("C4", "C", 0, 4),
        ("Bb3", "B", -1, 3),
        ("F#6", "F", 1, 6),
        ("Eb", "E", -1, None),
        ("C##4", "C", 2, 4),
        ("B♭4", "B", -1, 4),
    ],
)
def test_parse(text, letter, alter, octave):
    pitch = Pitch.parse(text)
    assert (pitch.letter, pitch.alter, pitch.octave) == (letter, alter, octave)


def test_text_forms():
    assert str(p("Bb4")) == "Bb4"
    assert p("Bb4").display() == "B♭"
    assert p("Bb4").display(octave=True) == "B♭4"
    assert p("F#").display() == "F♯"


def test_midi():
    assert p("C4").midi == 60
    assert p("A4").midi == 69
    assert p("Bb3").midi == 58


@pytest.mark.parametrize(
    ("start", "interval", "end"),
    [
        ("C4", "M6", "A4"),
        ("Bb3", "M6", "G4"),
        ("E4", "d7", "Db5"),
        ("F#4", "d7", "Eb5"),
        ("G4", "-M6", "Bb3"),
        ("C4", "P8", "C5"),
        ("B3", "m2", "C4"),
        ("Eb4", "M3", "G4"),
        ("F4", "A4", "B4"),
    ],
)
def test_transpose_keeps_spelling(start, interval, end):
    assert p(start).transpose(iv(interval)) == p(end)


def test_interval_between():
    assert Interval.between(p("C4"), p("A4")) == iv("M6")
    assert Interval.between(p("E4"), p("Db5")) == iv("d7")
    assert iv("M6").semitones == 9
    assert iv("d7").semitones == 9
    assert iv("M6") != iv("d7")


def test_bad_input():
    with pytest.raises(ValueError):
        Pitch.parse("X4")
    with pytest.raises(ValueError):
        iv("Q3")
