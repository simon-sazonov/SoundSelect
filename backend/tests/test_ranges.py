from soundselect.core.pitch import p
from soundselect.core.ranges import fit_melody, place_ascending


def names(pitches):
    return [str(x) for x in pitches]


def test_scales_rise_from_the_bottom_of_the_comfortable_range():
    g = [p("G"), p("A"), p("B"), p("D"), p("E")]
    assert names(place_ascending(g, p("C4"), p("C6"))) == ["G4", "A4", "B4", "D5", "E5", "G5"]
    b = [p("B"), p("C#"), p("D#"), p("F#"), p("G#")]
    assert names(place_ascending(b, p("C4"), p("C6"))) == ["B4", "C#5", "D#5", "F#5", "G#5", "B5"]


def test_chord_notes_without_the_octave():
    tones = [p("D"), p("F#"), p("A")]
    assert names(place_ascending(tones, p("C4"), p("C6"), add_octave=False)) == ["D4", "F#4", "A4"]


def test_moves_down_when_the_top_is_too_high_but_not_below_the_floor():
    notes = [p("A"), p("C"), p("E"), p("G"), p("B"), p("D"), p("F")]
    placed = place_ascending(notes, p("C4"), p("E5"), floor=p("Bb3"))
    assert names(placed)[0] == "A4"  # A3 would be below the floor, so it stays
    placed = place_ascending(notes, p("C4"), p("E5"))
    assert names(placed)[0] == "A3"


def test_fit_melody_moves_by_octaves():
    low_melody = [p("C3"), p("E3"), p("G3"), p("C4")]
    fit = fit_melody(low_melody, p("C4"), p("C6"), lowest=p("Bb3"), highest=p("F#6"))
    assert fit.octaves == 1
    assert names(fit.notes) == ["C4", "E4", "G4", "C5"]
    assert fit.out_of_range == []


def test_fit_melody_marks_notes_that_cannot_fit():
    wide = [p("C3"), p("C4"), p("C5"), p("C6"), p("C7")]
    fit = fit_melody(wide, p("C4"), p("C6"), lowest=p("Bb3"), highest=p("F#6"))
    assert fit.octaves == 0
    assert fit.out_of_range == [0, 4]
