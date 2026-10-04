from soundselect.core.song import ChordPlacement, Line
from soundselect.render.chart import chart_text, line_rows


def placement(chord, written, pos):
    return ChordPlacement(chord=chord, written=written, text=chord, pos=pos)


def test_chords_keep_their_columns():
    line = Line(lyrics="I found a love", chords=[placement("Bb", "G", 0), placement("F", "D", 8)])
    (row,) = line_rows(line)
    assert row.chord_text() == "G       D"
    assert row.lyrics == "I found a love"


def test_a_longer_chord_pushes_the_next_one_and_the_lyrics():
    # F/A becomes D/F# for alto: one letter longer, so the next chord and the words move right
    line = Line(
        lyrics="ab cd ef",
        chords=[placement("F/A", "D/F#", 0), placement("G", "E", 3)],
    )
    (row,) = line_rows(line)
    assert row.chord_text() == "D/F# E"
    assert row.lyrics == "ab   cd ef"
    assert row.lyrics.index("cd") == row.chords[1].col  # E still sits over "cd"


def test_chord_only_lines_start_at_the_left():
    line = Line(lyrics="", chords=[placement("Am", "F#m", 12), placement("C", "A", 17)])
    (row,) = line_rows(line)
    assert row.chord_text() == "F#m  A"


def test_long_lines_wrap_at_a_space_with_their_chords():
    words = "one two three four five six seven eight nine ten eleven twelve"
    line = Line(lyrics=words, chords=[placement("C", "A", 0), placement("G", "E", 42)])
    rows = line_rows(line, width=30)
    assert len(rows) > 1
    assert all(len(r.lyrics) <= 30 for r in rows)
    assert " ".join(r.lyrics for r in rows).split() == words.split()
    found = [(r.lyrics, m.col, m.label) for r in rows for m in r.chords]
    for lyrics, col, label in found:
        if label == "E":
            assert lyrics[col:].startswith(words[42:].split()[0])


def test_chart_text(found_a_love):
    text = chart_text(found_a_love)
    assert text.startswith("[Verse]\nG               D/F#       Em\n  I found a love, for me\n")
    assert "[Chorus]\nC    G/B   Am7   D      G\n" in text
    concert = chart_text(found_a_love, written=False)
    assert "Bb              F/A        Gm" in concert
