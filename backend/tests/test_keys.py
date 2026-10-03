import pytest

from soundselect.core.keys import Key


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bb", "B♭ major"),
        ("Bbm", "B♭ minor"),
        ("Bb major", "B♭ major"),
        ("F# minor", "F♯ minor"),
        ("Am", "A minor"),
        ("a", "A minor"),  # German style: lowercase is minor
        ("H", "B major"),  # H is B natural
        ("Hm", "B minor"),
        ("c-moll", "C minor"),
        ("C-Dur", "C major"),
        ("Es-Dur", "E♭ major"),
        ("B-Dur", "B♭ major"),  # German B is B flat
        ("fis-moll", "F♯ minor"),
        ("ля минор", "A minor"),
        ("си-бемоль мажор", "B♭ major"),
        ("фа-диез минор", "F♯ minor"),
        ("соль", "G major"),
    ],
)
def test_parse(text, expected):
    assert Key.parse(text).display() == expected


def test_not_a_key():
    with pytest.raises(ValueError):
        Key.parse("Xq")


@pytest.mark.parametrize(
    ("key", "fifths", "text"),
    [
        ("C", 0, "no sharps or flats"),
        ("G", 1, "1 sharp"),
        ("Bb", -2, "2 flats"),
        ("C#m", 4, "4 sharps"),
    ],
)
def test_signature(key, fifths, text):
    k = Key.parse(key)
    assert k.fifths == fifths
    assert k.signature_text() == text


def test_relative_and_scale():
    assert Key.parse("C").relative == Key.parse("Am")
    assert Key.parse("Am").relative == Key.parse("C")
    assert [str(n) for n in Key.parse("F").scale] == ["F", "G", "A", "Bb", "C", "D", "E"]


@pytest.mark.parametrize(
    ("pc", "mode", "expected"),
    [
        (1, "major", "D♭ major"),
        (6, "major", "F♯ major"),
        (8, "minor", "G♯ minor"),
        (10, "minor", "B♭ minor"),
    ],
)
def test_from_pitch_class(pc, mode, expected):
    assert Key.from_pc(pc, mode).display() == expected
