"""The melody on the staff: bars, rests, ties, beams, multi-bar rests and red doubtful notes."""

import xml.etree.ElementTree as ET

import pytest

from soundselect.render.melody import Meter, note_fits, rest_fits, split
from soundselect.render.page import song_page
from soundselect.render.scores import song_score
from soundselect.render.staff import draw


def bars(song, names="none"):
    root = ET.fromstring(song_score(song, "melody", names=names).encode())
    return root.findall(".//measure")


def shown(measure):
    """Each note as "G4:quarter" (dots added as "."), each rest as "rest:half"."""
    out = []
    for n in measure.findall("note"):
        if n.find("rest") is not None:
            out.append("rest:" + (n.findtext("type") or "bar"))
            continue
        pitch = n.findtext("pitch/step") + n.findtext("pitch/octave")
        out.append(f"{pitch}:{n.findtext('type')}" + "." * len(n.findall("dot")))
    return out


def test_a_note_across_the_bar_line_is_tied(add_melody):
    first, second = bars(add_melody([("Ab3", 3, 2.5)]), "russian")  # written F4: a natural
    assert shown(first) == ["rest:half", "rest:quarter", "F4:quarter"]
    assert shown(second) == ["F4:quarter.", "rest:eighth", "rest:half"]
    start, stop = first.findall("note")[-1], second.findall("note")[0]
    assert [t.get("type") for t in start.findall("tie")] == ["start"]
    assert [t.get("type") for t in stop.findall("tie")] == ["stop"]
    assert start.findtext("accidental") == "natural" and stop.find("accidental") is None
    assert start.findtext("lyric/text") == "фа" and stop.find("lyric") is None


@pytest.mark.parametrize(
    ("time", "rests"),
    [("4/4", ["rest:quarter", "rest:half"]), ("3/4", ["rest:quarter", "rest:quarter"])],
)
def test_rests_keep_the_beats(add_melody, time, rests):
    [bar] = bars(add_melody([("Bb3", 0, 1)], time=time))
    assert shown(bar) == ["G4:quarter", *rests]


def test_eighth_quarter_eighth_needs_no_ties(add_melody):
    notes = [("Bb3", 0, 0.5), ("C4", 0.5, 1), ("D4", 1.5, 0.5), ("Bb3", 2, 2)]
    [bar] = bars(add_melody(notes))
    assert shown(bar) == ["G4:eighth", "A4:quarter", "B4:eighth", "G4:half"]
    assert not bar.findall(".//tie")


def test_a_long_note_off_the_beat_is_tied_at_the_beat(add_melody):
    [bar] = bars(add_melody([("Bb3", 0.5, 1.5)]))
    assert shown(bar) == ["rest:eighth", "G4:eighth", "G4:quarter", "rest:half"]


def test_beams_by_the_beat(add_melody):
    sixteenths = [("Bb3", i / 4, 0.25) for i in range(4)]
    dotted = [("C4", 1, 0.75), ("D4", 1.75, 0.25)]
    snap = [("Bb3", 2, 0.25), ("C4", 2.25, 0.5), ("D4", 2.75, 0.25)]
    [bar] = bars(add_melody([*sixteenths, *dotted, *snap, ("Bb3", 3, 1)]))
    beams = [tuple(b.text for b in n.findall("beam")) for n in bar.findall("note")]
    assert beams == [
        ("begin", "begin"),
        ("continue", "continue"),
        ("continue", "continue"),
        ("end", "end"),
        ("begin",),
        ("end", "backward hook"),
        ("begin", "forward hook"),
        ("continue",),
        ("end", "backward hook"),
        (),
    ]


def test_empty_bars_are_one_multi_bar_rest(add_melody):
    measures = bars(add_melody([("Bb3", 12, 4)]))  # the singing starts in bar 4
    assert len(measures) == 4
    assert measures[0].findtext(".//multiple-rest") == "3"
    assert all(m.find(".//rest").get("measure") == "yes" for m in measures[:3])
    assert measures[0].findtext(".//metronome/per-minute") == "96"
    assert measures[0].find(".//time").get("print-object") is None  # 4/4 is shown


def test_doubtful_notes_are_red(add_melody):
    [bar] = bars(add_melody([("Bb3", 0, 1, 0.9), ("C4", 1, 3, 0.2)]))
    assert [n.get("color") for n in bar.findall("note")] == [None, "#C0392B"]


def test_overlapping_notes_are_cut_short(add_melody):
    [bar] = bars(add_melody([("Bb3", 0, 2), ("C4", 1, 3)]))
    assert shown(bar) == ["G4:quarter", "A4:half."]


@pytest.mark.parametrize(
    ("start", "end", "pieces"),
    [
        (0, 16, [(0, 16)]),
        (0, 10, [(0, 8), (8, 2)]),
        (4, 16, [(4, 12)]),  # a dotted half from beat 2
        (3, 6, [(3, 1), (4, 2)]),  # no eighth across a beat
        (1, 4, [(1, 3)]),
        (2, 6, [(2, 4)]),  # a quarter between two eighths
    ],
)
def test_note_values_in_4_4(start, end, pieces):
    assert split(Meter(4, 4), start, end, note_fits) == pieces


@pytest.mark.parametrize(
    ("start", "end", "pieces"),
    [(4, 16, [(4, 4), (8, 8)]), (1, 4, [(1, 1), (2, 2)]), (0, 12, [(0, 8), (8, 4)])],
)
def test_rest_values_in_4_4(start, end, pieces):
    assert split(Meter(4, 4), start, end, rest_fits) == pieces


def test_meters():
    assert Meter.parse("3/4").bar == 12 and Meter.parse("3/4").half is None
    assert Meter.parse("6/8").beat == 6 and Meter.parse("4/4").half == 8
    assert Meter.parse("nonsense") == Meter.parse(None) == Meter(4, 4)


def test_melody_part_and_all(add_melody, found_a_love):
    song = add_melody([("Bb3", 0, 1), ("C4", 1, 3)])
    assert song_score(found_a_love, "melody") is None  # a chord sheet has no melody
    xml = song_score(song, "all", names="russian")
    measures = ET.fromstring(xml.encode()).findall(".//measure")
    assert measures[0].find(".//metronome") is not None
    assert measures[1].find("print").get("new-system") == "yes"  # then the scales
    assert draw(xml).lstrip().startswith("<svg")


def test_song_page_shows_the_melody_after_the_pentatonic(add_melody, found_a_love):
    html = song_page(add_melody([("Bb3", 0, 1, 0.2), ("C4", 1, 3)]), "russian")
    assert html.index("Your pentatonic") < html.index("Melody for") < html.index("More scales")
    assert "4/4 · 96 beats a minute" in html and "the red note was the hardest" in html
    assert "Liberation Serif" in html  # names in the font they were measured with
    assert "Melody for" not in song_page(found_a_love, "russian")


def test_fix_panel_offers_the_melody_octave(client, tmp_path, add_melody):
    from soundselect.store import Library

    song = add_melody([("Bb3", 0, 1)]).model_copy(update={"form": [], "chords": []})
    saved = Library(tmp_path / "library").add_song(song, pipeline="song", inputs=[])
    page = client.get(f"/songs/{saved.id}").text
    assert "Melody octave" in page and "Found from the recording" in page
    assert 'id="ss-capo"' not in page  # no capo for a recording
