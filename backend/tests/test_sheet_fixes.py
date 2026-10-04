"""Chord sheets before the real ones: B♭ on Russian sheets, stated keys, short labels,
lowercase chords and repeat words."""

from soundselect.core.song import Corrections
from soundselect.pipeline.chord_sheet import analyze_sheet
from soundselect.sheets.lines import sort_lines
from soundselect.sheets.model import SheetText, TextLine
from soundselect.sheets.parse import parse_sheet, reads_differently

RUSSIAN_D_MINOR = """Песня

Dm         Gm
Снова ночь и тишина
A7         Dm
Только ветер за окном
B          C
Я иду к тебе одна
F          A7
И горит в окне огонь
"""


def sorted_sheet(text):
    return sort_lines(SheetText(lines=[TextLine(text=t) for t in text.split("\n")], source="text",
                                fingerprint="x"))  # fmt: skip


def symbols(song):
    return [c.symbol for c in song.chords]


def codes(song):
    return [n.code for n in song.notes]


# A. B or B♭


def test_russian_sheet_without_h_reads_b_flat():
    song = analyze_sheet(RUSSIAN_D_MINOR)
    assert "Bb" in symbols(song) and "B" not in symbols(song)
    assert codes(song)[0] == "b_flat_guess"
    assert (song.key.concert.tonic, song.key.concert.mode) == ("D", "minor")


def test_b_correction_keeps_b_natural():
    song = analyze_sheet(RUSSIAN_D_MINOR, corrections=Corrections(b_is_flat=False))
    assert "B" in symbols(song) and "Bb" not in symbols(song)
    assert "b_flat_guess" not in codes(song)


def test_b_reading_from_the_chords():
    assert "Bb" in symbols(analyze_sheet("F   B   C   F\nЛетний день и солнце светит\n"))
    assert "B" in symbols(analyze_sheet("E   A   B   E\nЛетний день и солнце светит\n"))
    english = analyze_sheet("Dm Gm A7 B C F\nSome words in English here\n")
    assert "B" in symbols(english) and "b_flat_guess" not in codes(english)
    both = analyze_sheet("Bb  B  F\nЛетний день и солнце светит\n")
    assert symbols(both) == ["Bb", "B", "F"]  # the sheet spells B♭ itself


def test_h_as_bass_note():
    assert sorted_sheet("G/H  C\nслова").uses_h
    assert not sorted_sheet("G/B  C\nслова").uses_h


def test_stated_b_on_a_sheet_with_h():
    sheet = parse_sheet(sorted_sheet("Тональность: B\n\nG   H   Em\nЛетний день"))
    assert sheet.meta.stated_key == "Bb major"
    song = analyze_sheet("Тональность: B\n\nB   Es   F   H7\nЛетний день\n")
    assert (song.key.concert.tonic, song.key.concert.mode) == ("Bb", "major")


def test_reads_differently():
    assert reads_differently("B") and reads_differently("G/B") and reads_differently("(Bm7)")
    assert (
        not reads_differently("Bb") and not reads_differently("H") and not reads_differently("Am")
    )


def test_b_correction_through_the_api(client):
    res = client.post("/api/v1/imports", data={"text": RUSSIAN_D_MINOR})
    song_id = res.json()["jobs"][0]["song_id"]
    song = client.patch(f"/api/v1/songs/{song_id}", json={"b_is_flat": False}).json()
    assert song["corrections"]["b_is_flat"] is False
    assert "B" in [c["symbol"] for c in song["chords"]]
    song = client.patch(f"/api/v1/songs/{song_id}", json={"b_is_flat": None}).json()
    assert song["corrections"]["b_is_flat"] is None
    assert "Bb" in [c["symbol"] for c in song["chords"]]
    page = client.get(f"/songs/{song_id}").text
    assert 'id="ss-b"' in page  # the Fix panel offers the choice


def test_fix_panel_hides_the_b_choice_without_b(client, sheet_text):
    res = client.post("/api/v1/imports", data={"text": "Am  C\nслова\n"})
    page = client.get(f"/songs/{res.json()['jobs'][0]['song_id']}").text
    assert 'id="ss-b"' not in page


# B. Stated keys


def key_of(song):
    return (song.key.concert.tonic, song.key.concert.mode, song.key.basis)


def test_stated_keys_keep_their_words():
    song = analyze_sheet("Тональность: ре минор\n\nDm  Gm\nНочь\n")
    assert key_of(song) == ("D", "minor", "stated")
    assert sorted_sheet("Тональность: ре минор").meta.stated_key == "ре минор"
    assert key_of(analyze_sheet("Key: D minor\n\nDm  Gm\nNight\n"))[:2] == ("D", "minor")
    assert sorted_sheet("Key: Am, capo 3").meta.stated_key == "Am"


def test_key_words_in_lyrics():
    sheet = sorted_sheet("Am  F\nKey to my heart\nТон голоса твоего")
    assert [line.kind for line in sheet.lines] == ["chords", "lyrics", "lyrics"]
    assert sheet.meta.stated_key is None


# C. Short labels and the title


def test_label_before_a_tab():
    text = (
        "Little Riff Song\n\nIntro riff:\ne|-----0-----|\nB|---1---1---|\nG|-----------|\n"
        "D|-----------|\nA|-----------|\nE|-----------|\n\nVerse:\nAm   C\nwords here\n"
    )
    song = analyze_sheet(text)
    assert song.identity.title == "Little Riff Song"
    assert (song.form[0].kind, song.form[0].label) == ("intro", "Intro riff")


def test_part_names():
    text = (
        "Example Standard\n\nA1:\nCmaj7 Am7 Dm7 G7\nfirst words\nB:\nFmaj7 Fm6 Em7 A7\n"
        "second words\n"
    )
    song = analyze_sheet(text)
    assert song.identity.title == "Example Standard"
    assert [(s.kind, s.label) for s in song.form] == [("other", "A1"), ("other", "B")]
    assert "B" not in symbols(song)


def test_title_set_off_from_the_opening_words():
    song = analyze_sheet("Song Title\n\nSome opening words\nAm  F\nwords\n")
    assert song.identity.title == "Song Title"
    assert [line.lyrics for line in song.lines()] == ["Some opening words", "words"]


def test_lyric_ending_in_a_colon():
    sheet = sorted_sheet("Am   F\nAnd then she said:\nG   C\nmore words")
    assert [line.kind for line in sheet.lines] == ["chords", "lyrics", "chords", "lyrics"]


# D. Lowercase chords


def test_lowercase_chord_lines():
    song = analyze_sheet("am               dm\nНочь легла на города,\n")
    assert symbols(song) == ["Am", "Dm"]
    assert sorted_sheet("Am dm G\nsomething").lines[0].kind == "chords"
    sheet = sorted_sheet("Am  F\nI am here\nG   C\nA day in the life")
    assert [line.kind for line in sheet.lines] == ["chords", "lyrics", "chords", "lyrics"]


# E. Repeat words


def test_repeat_words_after_chords():
    song = analyze_sheet("Проигрыш: Am Dm E7 Am (2 раза)\n")
    assert song.form[0].kind == "interlude"
    line = song.form[0].lines[0]
    assert [c.chord for c in line.chords] == ["Am", "Dm", "E7", "Am"] and line.repeat == 2
    sheet = sorted_sheet("Am Dm E7 Am 2 times")
    assert sheet.lines[0].kind == "chords" and sheet.lines[0].repeat == 2
    sheet = sorted_sheet("Am  F\nПой со мной (2 раза)")
    assert (sheet.lines[1].kind, sheet.lines[1].lyrics, sheet.lines[1].repeat) == (
        "lyrics",
        "Пой со мной",
        2,
    )
