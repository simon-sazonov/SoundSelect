"""The Phase 0 gate: a chord sheet in, everything an alto player needs out."""

import xml.etree.ElementTree as ET

import pytest

from soundselect.core.song import Song
from soundselect.core.view import with_names
from soundselect.render.page import song_page
from soundselect.render.pdf import html_to_pdf, pdf_available
from soundselect.render.scores import PARTS, chord_score, song_score
from soundselect.render.staff import draw
from soundselect.render.text import song_text


def test_key(found_a_love):
    key = found_a_love.key
    assert (key.concert.tonic, key.concert.mode) == ("Bb", "major")
    assert key.confidence > 0.9
    view = found_a_love.view
    assert (view.instrument, view.name, view.interval, view.respelled) == (
        "alto_sax",
        "Alto sax in E♭",
        "M6",
        False,
    )
    assert (view.written_key.tonic, view.written_key.mode, view.written_key.fifths) == (
        "G",
        "major",
        1,
    )


def test_headline_is_the_keys_pentatonic_written_for_alto(found_a_love):
    headline = found_a_love.headline
    assert found_a_love.scales[0] is headline
    assert headline.kind == "major_pentatonic"
    assert headline.written.staff == ["G4", "A4", "B4", "D5", "E5", "G5"]
    assert headline.concert.notes == ["Bb", "C", "D", "F", "G"]


def test_other_scales(found_a_love):
    minor, blues = found_a_love.scales[1:]
    assert minor.written.staff == ["E4", "G4", "A4", "B4", "D5", "E5"]
    assert blues.written.staff == ["E4", "G4", "A4", "Bb4", "B4", "D5", "E5"]


def test_chords_for_alto(found_a_love):
    written = {c.symbol: c.written.symbol for c in found_a_love.chords}
    assert written == {
        "Bb": "G", "F/A": "D/F#", "Gm": "Em", "Eb": "C",
        "F": "D", "Gm7": "Em7", "Bb/D": "G/B", "Cm7": "Am7",
    }  # fmt: skip
    counts = {c.symbol: c.count for c in found_a_love.chords}
    assert counts["Bb"] == 4
    assert counts["Eb"] == 3
    clashing = {
        c.written.symbol: c.clashes.written for c in found_a_love.chords if c.clashes.written
    }
    assert clashing == {"D/F#": ["G"], "D": ["G"]}
    d = found_a_love.chord_info("F")
    assert d.scales[0].written.notes == ["D", "E", "F#", "A", "B"]


def test_form_keeps_chords_over_their_words(found_a_love):
    verse, chorus = found_a_love.form
    assert (verse.kind, verse.label, chorus.kind, chorus.label) == (
        "verse",
        "Verse",
        "chorus",
        "Chorus",
    )
    first = verse.lines[0]
    assert [(c.chord, c.written, c.pos) for c in first.chords] == [
        ("Bb", "G", 0),
        ("F/A", "D/F#", 16),
        ("Gm", "Em", 27),
    ]


def test_identity(found_a_love):
    identity = found_a_love.identity
    assert (identity.title, identity.artist, identity.source) == (
        "I Found a Love",
        "Test Band",
        "text",
    )
    assert len(identity.fingerprint) == 64


def test_names(found_a_love):
    named = with_names(found_a_love, "russian")
    assert named.names["Bb"] == "си♭"
    assert named.names["G"] == "соль"
    assert named.names["F#"] == "фа♯"


def test_json_round_trip(found_a_love):
    assert Song.model_validate_json(found_a_love.model_dump_json()) == found_a_love


@pytest.mark.parametrize("part", PARTS)
def test_musicxml_parts_parse_and_draw(found_a_love, part):
    xml = song_score(found_a_love, part, names="russian")
    root = ET.fromstring(xml.encode())
    assert root.tag == "score-partwise"
    assert draw(xml).lstrip().startswith("<svg")


def test_headline_score_is_in_g_major(found_a_love):
    root = ET.fromstring(song_score(found_a_love, "headline").encode())
    assert root.find(".//key/fifths").text == "1"
    steps = [n.findtext("pitch/step") + n.findtext("pitch/octave") for n in root.iter("note")]
    assert steps == ["G4", "A4", "B4", "D5", "E5", "G5"]


def test_chord_score(found_a_love):
    xml = chord_score(found_a_love, found_a_love.chord_info("F/A"))
    root = ET.fromstring(xml.encode())
    assert len(root.findall(".//measure")) == 2  # the chord's notes, then its scale
    assert root.find(".//harmony/root/root-step").text == "D"


def test_song_page(found_a_love):
    html = song_page(found_a_love, "russian")
    for text in [
        "I Found a Love",
        "соль мажор",  # the key for alto, in Russian names
        "си-бемоль мажор",  # the concert key
        "Your pentatonic",
        "Major pentatonic on соль",
        "D/F♯",
        "Darling just dive right in",
    ]:
        assert text in html, text
    assert html.count("<svg") >= 3 + len(found_a_love.chords)
    assert "@font-face" in html  # the music font, once for the whole page


def test_concert_page(found_a_love):
    html = song_page(found_a_love, "letters", written=False)
    assert "B♭ major pentatonic" in html
    assert "Key for" not in html


def test_song_text(found_a_love):
    text = song_text(found_a_love, "russian")
    assert "Key for Alto sax in E♭: соль мажор (G major, 1 sharp)" in text
    assert "Your pentatonic: Major pentatonic on соль" in text
    assert "соль ля си ре ми  (G A B D E)" in text


@pytest.mark.skipif(not pdf_available(), reason="PDF output needs the Pango library")
def test_pdf(found_a_love):
    pdf = html_to_pdf(song_page(found_a_love, "russian"))
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 10_000


def test_russian_sheet_end_to_end(russian_song):
    assert (russian_song.key.concert.tonic, russian_song.key.concert.mode) == ("B", "minor")
    assert russian_song.view.written_key.tonic == "G#"
    assert russian_song.headline.written.notes == ["G#", "B", "C#", "D#", "F#"]
    assert [c.written.symbol for c in russian_song.chords][:4] == ["G#m", "A#m", "B", "D#7"]
    assert any(n.code == "capo" for n in russian_song.notes)
