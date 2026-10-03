import pytest

from soundselect.core.instruments import INSTRUMENTS, Transposition, get_instrument
from soundselect.core.keys import ALL_KEYS, Key

# Concert key -> key written for alto sax. Up a major sixth, except where that would need more
# than six sharps, which is written one letter lower (a diminished seventh) instead.
ALTO = {
    "C": "A", "Db": "Bb", "D": "B", "Eb": "C", "E": "Db", "F": "D", "F#": "Eb", "G": "E",
    "Ab": "F", "A": "F#", "Bb": "G", "B": "Ab",
    "Cm": "Am", "C#m": "Bbm", "Dm": "Bm", "D#m": "Cm", "Em": "C#m", "Fm": "Dm", "F#m": "D#m",
    "Gm": "Em", "G#m": "Fm", "Am": "F#m", "Bbm": "Gm", "Bm": "G#m",
}  # fmt: skip


@pytest.mark.parametrize(("concert", "written"), ALTO.items())
def test_alto_sax_keys(concert, written):
    tr = Transposition.for_key(get_instrument("alto_sax"), Key.parse(concert))
    assert tr.written_key == Key.parse(written)


@pytest.mark.parametrize("instrument", INSTRUMENTS)
def test_every_written_key_has_at_most_six_sharps_or_flats(instrument):
    inst = get_instrument(instrument)
    for key in ALL_KEYS:
        tr = Transposition.for_key(inst, key)
        assert abs(tr.written_key.fifths) <= 6, (instrument, key)
        # the written key still sounds as the concert key
        assert (tr.written_key.tonic.pc - tr.interval.semitones - key.tonic.pc) % 12 == 0


@pytest.mark.parametrize(
    ("instrument", "concert", "written"),
    [
        ("tenor_sax", "Bb", "C"),
        ("soprano_sax", "Bb", "C"),
        ("baritone_sax", "Eb", "C"),
        ("concert", "Eb", "Eb"),
    ],
)
def test_other_instruments(instrument, concert, written):
    tr = Transposition.for_key(get_instrument(instrument), Key.parse(concert))
    assert tr.written_key == Key.parse(written)


def test_unknown_instrument():
    with pytest.raises(ValueError, match="unknown instrument"):
        get_instrument("tuba")
