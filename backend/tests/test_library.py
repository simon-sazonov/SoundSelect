"""The library: the database, stored inputs, batches and jobs, songs and settings."""

import sqlite3

import pytest

from soundselect.core.song import Corrections
from soundselect.imports import ImportOptions, InputRef, JobPlan
from soundselect.pipeline.chord_sheet import analyze_sheet
from soundselect.settings import Settings
from soundselect.store import Library
from soundselect.store.db import MIGRATIONS


def text_plan(lib: Library, text: str, name: str = "Song") -> JobPlan:
    return JobPlan([lib.store_input(text.encode(), "text")], name, "chord_sheet")


def test_new_library_folder(tmp_path):
    lib = Library(tmp_path / "home")
    assert (tmp_path / "home" / "library.db").exists()
    with sqlite3.connect(lib.db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    Library(tmp_path / "home")  # opening it again changes nothing


def test_library_from_a_newer_version(tmp_path):
    lib = Library(tmp_path)
    with sqlite3.connect(lib.db) as conn:
        conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    with pytest.raises(RuntimeError, match="newer SoundSelect"):
        Library(tmp_path)


def test_home_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SOUNDSELECT_HOME", str(tmp_path / "from-env"))
    assert Library().home == tmp_path / "from-env"


def test_inputs_are_stored_once(library):
    a = library.store_input(b"Am C G", "text")
    b = library.store_input(b"Am C G", "text", "again.txt")
    assert a.sha == b.sha and a.size == 6
    assert library.read_input(b) == b"Am C G"
    assert len(list(library.inputs_dir.rglob("*"))) == 2  # one folder, one file
    with pytest.raises(ValueError):
        library.read_input(InputRef(kind="link", url="https://example.com"))


def test_settings(library):
    assert library.settings() == Settings()
    saved = library.save_settings(Settings(instrument="tenor_sax", names="letters"))
    assert library.settings() == saved
    with sqlite3.connect(library.db) as conn:
        conn.execute("UPDATE settings SET value = '{\"instrument\": 5}'")
    assert library.settings() == Settings()  # unreadable settings fall back to the defaults


def test_batch_with_jobs(library):
    plans = [
        text_plan(library, "Am C"),
        JobPlan([], "song.mp3", None, "Songs from audio files come later."),
    ]
    batch = library.create_batch(plans, ImportOptions(instrument="alto_sax", title="One"))
    assert (batch.status, batch.total, batch.done, batch.failed) == ("working", 2, 0, 1)
    waiting, failed = batch.jobs
    assert waiting.status == "queued" and waiting.kind == "chord_sheet"
    assert failed.error == "Songs from audio files come later." and failed.finished
    # a title belongs to one song, so it is not given to each song of a batch
    assert library.job_options(waiting.id) == ImportOptions(instrument="alto_sax")

    library.update_job(waiting.id, status="running", step="key", progress=0.5)
    job = library.job(waiting.id)
    assert (job.status, job.step, job.progress, job.rev) == ("running", "key", 0.5, 2)
    assert [j.id for j in library.jobs_with_status("running")] == [waiting.id]
    assert library.job_revs([waiting.id, failed.id]) == {waiting.id: 2, failed.id: 1}

    library.update_job(waiting.id, status="queued")
    assert library.claim_job(waiting.id, step="read")  # one worker takes it
    assert not library.claim_job(waiting.id)  # and no other
    assert not library.claim_job(failed.id)
    assert library.job(waiting.id).step == "read"

    library.update_job(waiting.id, status="done")
    assert library.batch(batch.id).status == "done"
    assert library.batch("nope") is None and library.job("nope") is None


def test_single_song_keeps_its_options(library):
    options = ImportOptions(title="One", key="Bb", capo=2)
    batch = library.create_batch([text_plan(library, "Am C")], options)
    assert library.job_options(batch.jobs[0].id) == options


def test_songs(library, data_dir):
    love = analyze_sheet(data_dir / "found_a_love.txt")
    russian = analyze_sheet(data_dir / "russian_h.txt")
    ref = InputRef(kind="text", name="found_a_love.txt", sha="0" * 64, size=1)
    a = library.add_song(love, pipeline="chord_sheet", inputs=[ref])
    b = library.add_song(russian, pipeline="chord_sheet", inputs=[ref])
    assert a.id and b.id and a.id != b.id
    assert library.count_songs() == 2

    record = library.song_record(a.id)
    assert record.song == a and record.inputs == [ref] and record.pipeline == "chord_sheet"
    assert library.find_song(love.identity.fingerprint) == a.id
    assert library.find_song("nothing") is None

    rows, total = library.list_songs()
    assert total == 2 and [r.id for r in rows] == [b.id, a.id]  # newest first
    rows, _ = library.list_songs(sort="title")
    assert [r.title for r in rows] == ["I Found a Love", "Песня про лето"]
    assert [r.id for r in library.list_songs("found love")[0]] == [a.id]  # every word
    assert [r.id for r in library.list_songs("ЛЕТО")[0]] == [b.id]  # any case, any script
    assert library.list_songs("камыш")[0][0].id == b.id  # lyrics too
    assert library.list_songs("love лето")[1] == 0
    assert library.list_songs("100%")[1] == 0  # LIKE wildcards are plain text
    rows, total = library.list_songs(limit=1, offset=1)
    assert total == 2 and [r.id for r in rows] == [a.id]
    assert library.song_row(a.id).key.tonic == "Bb"

    fixed = a.model_copy(update={"corrections": Corrections(title="Renamed")})
    library.save_song(fixed)
    assert library.song_record(a.id).corrections.title == "Renamed"
    with pytest.raises(KeyError):
        library.save_song(a.model_copy(update={"id": "nope"}))

    assert library.delete_song(a.id) and not library.delete_song(a.id)
    assert library.song_record(a.id) is None and library.song_row(a.id) is None


def test_song_saved_by_another_version(library, data_dir):
    song = library.add_song(
        analyze_sheet(data_dir / "found_a_love.txt"), pipeline="chord_sheet", inputs=[]
    )
    with sqlite3.connect(library.db) as conn:
        conn.execute('UPDATE songs SET song = \'{"kind": "song"}\' WHERE id = ?', (song.id,))
    record = library.song_record(song.id)
    assert record is not None and record.song is None


def test_step_cache(library):
    assert library.cache.get("k") is None
    library.cache.put("k", {"notes": ["си♭", 1]})
    assert library.cache.get("k") == {"notes": ["си♭", 1]}
