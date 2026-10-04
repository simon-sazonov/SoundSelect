"""Reading chord sheets: text decoding, sorting lines, chords, capo."""

from soundselect.core.song import ChordFix
from soundselect.sheets.capo import apply_capo
from soundselect.sheets.lines import is_chord_line, sort_lines, tokenize
from soundselect.sheets.parse import parse_sheet
from soundselect.sheets.readers import SheetInput, UnsupportedInput, detect_kind, read_sheet
from soundselect.sheets.readers.text import clean_lines, decode_text


def sorted_sheet(data_dir, name):
    return sort_lines(read_sheet(SheetInput.from_path(data_dir / name)))


def test_decoding():
    assert decode_text("﻿Am C".encode()) == "Am C"  # byte order mark dropped
    assert decode_text("Припев".encode("cp1251")) == "Припев"  # old Windows Russian files
    assert clean_lines("A B\tC​") == ["A B     C"]


def test_input_kinds():
    assert detect_kind(SheetInput("Am C")) == "text"
    assert detect_kind(SheetInput(b"%PDF-1.7", "song.pdf")) == "pdf"
    assert detect_kind(SheetInput(b"\x89PNG", "song.png")) == "photo"
    try:
        read_sheet(SheetInput(b"%PDF-1.7", "song.pdf"))
    except UnsupportedInput as exc:
        assert "pdf" in str(exc)
    else:
        raise AssertionError("PDF sheets are not read yet")


def test_chord_lines():
    assert is_chord_line(tokenize("Am   C   G   D"))
    assert is_chord_line(tokenize("| Em  C  | G  D  |"))
    assert not is_chord_line(tokenize("I am here"))
    assert not is_chord_line(tokenize("A day in the life"))


def test_english_sheet(data_dir):
    sheet = sorted_sheet(data_dir, "found_a_love.txt")
    assert (sheet.meta.title, sheet.meta.artist, sheet.meta.capo) == (
        "I Found a Love",
        "Test Band",
        0,
    )
    kinds = [line.kind for line in sheet.lines]
    assert kinds[:7] == ["header", "blank", "meta", "blank", "section", "chords", "lyrics"]
    sections = [(line.section, line.label) for line in sheet.lines if line.kind == "section"]
    assert sections == [("verse", "Verse"), ("chorus", "Chorus")]


def test_russian_sheet_with_h_and_capo(data_dir):
    sheet = sorted_sheet(data_dir, "russian_h.txt")
    assert sheet.meta.title == "Песня про лето"
    assert sheet.meta.artist == "Тестовая группа"
    assert sheet.meta.capo == 2
    assert sheet.uses_h
    intro, verse, chorus = (line for line in sheet.lines if line.kind == "section")
    assert (intro.section, intro.label) == ("intro", "Вступление")
    assert [t.text for t in intro.tokens if t.kind == "chord"] == ["Am", "Hm", "C", "E7"]
    assert (verse.section, verse.label) == ("verse", "Куплет 1")
    assert (chorus.section, chorus.label, chorus.repeat) == ("chorus", "Припев", 2)


def test_chordpro(data_dir):
    sheet = sorted_sheet(data_dir, "river_song.cho")
    assert (sheet.meta.title, sheet.meta.artist, sheet.meta.stated_key) == (
        "River Song",
        "The Test Players",
        "D",
    )
    first = next(line for line in sheet.lines if line.kind == "lyrics")
    assert first.lyrics == "Down by the river where the water runs slow"
    chords = [(t.text, t.pos) for t in first.tokens if t.kind == "chord"]
    assert chords == [("D", 0), ("A", 12), ("Bm", 28), ("G", 39)]
    assert first.lyrics[12:17] == "river"


def test_parse_pairs_chords_with_lyrics(data_dir):
    parsed = parse_sheet(sorted_sheet(data_dir, "found_a_love.txt"))
    verse = parsed.sections[0]
    line = verse.lines[0]
    assert line.lyrics == "  I found a love, for me"
    assert [(c.symbol, c.pos) for c in line.chords] == [("Bb", 0), ("F/A", 16), ("Gm", 27)]
    assert [c.symbol for c in parsed.chords()][-1] == "Bb"


def test_chord_fixes(data_dir):
    sheet = sorted_sheet(data_dir, "found_a_love.txt")
    everywhere = parse_sheet(sheet, [ChordFix(original="Eb", to="Ebmaj7")])
    assert [c.symbol for c in everywhere.chords()].count("Ebmaj7") == 3
    one = parse_sheet(sheet, [ChordFix(original="Eb", to="Ebmaj7", line=1, index=0)])
    assert [c.symbol for c in one.chords()].count("Ebmaj7") == 1


def test_capo_moves_shapes_to_sounding_chords(data_dir):
    parsed = parse_sheet(sorted_sheet(data_dir, "russian_h.txt"))
    moved = apply_capo(parsed)
    assert [c.symbol for c in parsed.chords()][:4] == ["Am", "Bm", "C", "E7"]
    assert [c.symbol for c in moved.chords()][:4] == ["Bm", "C#m", "D", "F#7"]
    assert any(n.code == "capo" for n in moved.notices)
    assert apply_capo(parsed, capo=0).chords() == parsed.chords()


def test_chords_on_a_label_line_keep_their_repeat():
    sheet = parse_sheet(sort_lines(read_sheet(SheetInput("Intro: C G x2\n\nC   G\nSome words\n"))))
    intro = sheet.sections[0]
    assert (intro.kind, intro.label) == ("intro", "Intro")
    assert [c.symbol for c in intro.lines[0].chords] == ["C", "G"]
    assert intro.lines[0].repeat == 2


def test_punctuation_around_chords():
    parsed = parse_sheet(sort_lines(read_sheet(SheetInput("(Am)  G/B.  C*  D,  Em...\nwords\n"))))
    assert [(c.symbol, c.readable) for c in parsed.chords()] == [
        ("Am", True),
        ("G/B", True),
        ("C", True),
        ("D", True),
        ("Em", True),
    ]
