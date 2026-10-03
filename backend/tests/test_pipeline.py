"""The step runner: saved outputs are reused, and a correction re-runs only what it touches."""

from soundselect.core.song import Corrections, Song
from soundselect.pipeline.chord_sheet import CHORD_SHEET, analyze_sheet, run_chord_sheet
from soundselect.pipeline.runner import DirCache, MemoryCache
from soundselect.settings import ViewSettings
from soundselect.sheets.readers import SheetInput

ALL_STEPS = ["read", "sort", "parse", "capo", "key", "song", "view"]


def source(data_dir):
    return SheetInput.from_path(data_dir / "found_a_love.txt")


def test_second_run_reuses_everything(data_dir):
    cache = MemoryCache()
    first = run_chord_sheet(source(data_dir), cache=cache)
    assert first.ran == ALL_STEPS
    second = run_chord_sheet(source(data_dir), cache=cache)
    assert second.ran == []
    assert second["view"] == first["view"]


def test_key_correction_reruns_only_key_and_after(data_dir):
    cache = MemoryCache()
    run_chord_sheet(source(data_dir), cache=cache)
    fixed = run_chord_sheet(source(data_dir), cache=cache, corrections=Corrections(key="Gm"))
    assert fixed.ran == ["key", "song", "view"]
    song: Song = fixed["view"]
    assert (song.key.concert.tonic, song.key.concert.mode, song.key.basis) == (
        "G",
        "minor",
        "correction",
    )
    assert song.view.written_key.tonic == "E"


def test_other_instrument_reruns_only_the_view(data_dir):
    cache = MemoryCache()
    run_chord_sheet(source(data_dir), cache=cache)
    tenor = run_chord_sheet(
        source(data_dir), cache=cache, view=ViewSettings(instrument="tenor_sax")
    )
    assert tenor.ran == ["view"]
    assert tenor["view"].view.written_key.tonic == "C"


def test_saved_outputs_survive_on_disk(data_dir, tmp_path):
    run_chord_sheet(source(data_dir), cache=DirCache(tmp_path))
    again = run_chord_sheet(source(data_dir), cache=DirCache(tmp_path))
    assert again.ran == []


def test_progress_events(data_dir):
    events = []
    run_chord_sheet(source(data_dir), on_step=lambda *e: events.append(e))
    assert events[0] == ("read", "start", 1, 7)
    assert events[-1] == ("view", "done", 7, 7)


def test_song_records_step_versions(data_dir):
    song = analyze_sheet(data_dir / "found_a_love.txt")
    assert song.versions == CHORD_SHEET.versions


def test_pasted_text():
    song = analyze_sheet("Am F C G\nSome words here")
    assert song.identity.source == "text"
    assert [c.symbol for c in song.chords] == ["Am", "F", "C", "G"]


def test_same_contents_under_another_name_is_read_again(tmp_path):
    text = b"C   G   Am   F\nwords go here\n"
    cache = MemoryCache()
    first = run_chord_sheet(SheetInput(text, "first.txt"), cache=cache)
    second = run_chord_sheet(SheetInput(text, "second.txt"), cache=cache)
    assert "read" in second.ran
    assert first["view"].identity.title == "first"
    assert second["view"].identity.title == "second"
    # the song itself is recognized as the same one
    assert first["view"].identity.fingerprint == second["view"].identity.fingerprint


def test_an_unreadable_saved_output_is_made_again(data_dir):
    cache = MemoryCache()
    run_chord_sheet(source(data_dir), cache=cache)
    for key in cache.items:
        if key.startswith("chord_sheet/key/"):
            cache.items[key] = {"value": {"not": "a key result"}}
    again = run_chord_sheet(source(data_dir), cache=cache)
    assert again.ran == ["key"]
    assert again["key"].concert.tonic == "Bb"
