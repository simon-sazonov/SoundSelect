"""What the app does with songs: imports, corrections, the library list, source pages."""

import pytest

from soundselect import service
from soundselect.core.song import ChordFix
from soundselect.imports import ImportOptions
from soundselect.jobs import run_job
from soundselect.service import BadRequest, NotFound, SongPatch
from soundselect.sheets import readers


def add(lib, text=None, files=None, **options):
    batch = service.start_import(
        lib, texts=[text] if text else None, files=files, options=ImportOptions(**options)
    )
    for job_id in service.queued_jobs(batch):
        run_job(lib, job_id)
    return lib.batch(batch.id)


def add_song(lib, text=None, files=None, **options):
    job = add(lib, text, files, **options).jobs[0]
    assert job.status == "done", job.error
    return job.song_id


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "Nothing to import"),
        ({"texts": ["   \n"]}, "Nothing to import"),
        ({"texts": ["Am"] * (service.MAX_ITEMS + 1)}, "import them in parts"),
        ({"texts": ["Am"], "options": ImportOptions(key="Q")}, "Can't read 'Q' as a key"),
        ({"texts": ["Am"], "options": ImportOptions(instrument="kazoo")}, "Unknown instrument"),
        ({"files": [("a.png", b"x")], "options": ImportOptions(groups=[[0, 3]])}, "file 3"),
        ({"texts": ["x" * (service.MAX_TEXT + 1)]}, "longer than"),
    ],
)
def test_imports_that_cant_start(library, kwargs, message):
    with pytest.raises(BadRequest, match=message):
        service.start_import(library, **kwargs)
    assert library.count_songs() == 0


def test_large_file(library, monkeypatch):
    monkeypatch.setattr(service, "MAX_FILE", 10)
    with pytest.raises(BadRequest, match=r"big\.pdf is larger than"):
        service.start_import(library, files=[("big.pdf", b"%PDF-" + b"0" * 10)])


@pytest.mark.usefixtures("without_song")
def test_every_item_gets_a_job(library, sheet_text, data_dir):
    pdf = (data_dir / "pdf" / "found_a_love_mono.pdf").read_bytes()
    batch = service.start_import(
        library,
        texts=[sheet_text, "\n\n   " + "A very long first line of pasted text " * 3],
        files=[
            ("sheet.pdf", pdf),
            ("song.txt", b""),
            ("notes.docx", b"PK\x03\x04"),
            ("page.jpg", b"\xff\xd8\xff\xe0"),
            ("track.mp3", b"ID3"),
            ("lesson.mp4", b"\x00\x00\x00\x18ftyp"),
        ],
        links=["https://youtu.be/abc", "  "],
    )
    names = [j.name for j in batch.jobs]
    long_name = "A very long first line of pasted text A very long first l..."
    assert names[:2] == ["Test Band - I Found a Love", long_name]  # their first lines
    assert names[2:] == [
        "sheet.pdf", "song.txt", "notes.docx", "page.jpg", "track.mp3", "lesson.mp4",
        "https://youtu.be/abc",
    ]  # fmt: skip
    waiting = [j.name for j in batch.jobs if j.status == "queued"]
    assert waiting == [*names[:3], "page.jpg"]  # a photo is read, and fails when it runs
    errors = {j.name: j.error for j in batch.jobs if j.status == "failed"}
    assert errors == {
        "song.txt": "This file is empty.",
        "notes.docx": "SoundSelect can't read .docx files. Save the sheet as a PDF or plain text.",
        "track.mp3": "Songs from audio files come in a later build phase.",
        "lesson.mp4": "Sheet music videos come in a later build phase.",
        "https://youtu.be/abc": "Links (YouTube and others) come in a later build phase.",
    }
    assert batch.jobs[2].inputs[0].kind == "pdf" and batch.jobs[2].kind == "chord_sheet"


def test_grouped_photos(library):
    batch = service.start_import(
        library,
        files=[("p1.jpg", b"\xff\xd8\xff"), ("p2.jpg", b"\xff\xd8\xff\x00"), ("p3.png", b"\x89PN")],
        options=ImportOptions(groups=[[1, 0]]),
    )
    jobs = [(j.name, j.kind, j.status) for j in batch.jobs]
    assert jobs[1] == ("p3.png", "chord_sheet", "queued")
    assert jobs[0][1:] == ("chord_sheet", "queued")
    assert [r.name for r in batch.jobs[0].inputs] == ["p2.jpg", "p1.jpg"]  # in the group's order


def test_library_list(library, sheet_text, data_dir):
    love = add_song(library, sheet_text)
    russian = add_song(library, (data_dir / "russian_h.txt").read_text(encoding="utf-8"))
    found = service.list_songs(library)
    assert found.total == 2 and [s.id for s in found.songs] == [russian, love]
    summary = found.songs[1]
    assert (summary.key.tonic, summary.written_key.tonic) == ("Bb", "G")
    assert summary.pentatonic == ["G", "A", "B", "D", "E"]
    assert summary.instrument == "alto_sax" and summary.source == "text"
    tenor = service.list_songs(library, "love", instrument="tenor_sax").songs[0]
    assert tenor.written_key.tonic == "C" and tenor.pentatonic == ["C", "D", "E", "G", "A"]
    assert service.song_summary(library, love).title == "I Found a Love"
    with pytest.raises(NotFound):
        service.song_summary(library, "nope")
    with pytest.raises(BadRequest):
        service.list_songs(library, instrument="kazoo")


def test_get_song(library, sheet_text):
    song_id = add_song(library, sheet_text)
    song = service.get_song(library, song_id)
    assert song.id == song_id and song.names is None
    named = service.get_song(library, song_id, instrument="tenor_sax", names="russian")
    assert named.view.instrument == "tenor_sax" and named.names["Bb"] == "си♭"
    with pytest.raises(NotFound):
        service.get_song(library, "nope")
    with pytest.raises(BadRequest):
        service.get_song(library, song_id, instrument="kazoo")


def test_comfortable_range_follows_the_settings(library, sheet_text):
    song_id = add_song(library, sheet_text)
    assert service.get_song(library, song_id).view.comfortable_low == "C4"  # alto's own
    settings = library.settings()
    library.save_settings(settings.model_copy(update={"comfortable_low": "D4"}))
    assert service.get_song(library, song_id).view.comfortable_low == "D4"
    library.save_settings(settings)  # back to the instrument's range
    assert service.get_song(library, song_id).view.comfortable_low == "C4"
    with_range = settings.model_copy(update={"comfortable_low": "A3", "comfortable_high": "A5"})
    library.save_settings(with_range)
    song_id = add_song(library, "C G Am F\nwords")  # made with the range set
    library.save_settings(settings)
    assert service.get_song(library, song_id).view.comfortable_high == "C6"


def test_fixing_the_key_runs_only_what_it_touches(library, sheet_text, monkeypatch):
    song_id = add_song(library, sheet_text)

    def no_reading(source):
        raise AssertionError("the sheet was read again")

    monkeypatch.setitem(readers.READERS, "text", no_reading)
    song = service.correct_song(library, song_id, SongPatch(key="Gm"))
    assert song.key.concert.tonic == "G" and song.key.concert.mode == "minor"
    assert song.key.basis == "correction"
    assert song.view.written_key.tonic == "E"  # G minor for alto is E minor
    assert song.headline.kind == "minor_pentatonic"
    assert service.get_song(library, song_id).key.concert.tonic == "G"  # saved

    song = service.correct_song(library, song_id, SongPatch(title="My title", capo=2))
    assert song.corrections.key == "Gm" and song.identity.title == "My title"
    assert song.corrections.capo == 2
    song = service.correct_song(library, song_id, SongPatch.model_validate({"key": None}))
    assert song.corrections.key is None and song.corrections.title == "My title"
    assert song.key.basis == "chords"


def test_chord_fixes(library, sheet_text):
    song_id = add_song(library, sheet_text)
    before = service.get_song(library, song_id)
    first = before.lines()[0].chords[0]
    count = sum(c.text == first.text for line in before.lines() for c in line.chords)
    fixes = [ChordFix(original=first.text, to=first.text + "7")]
    song = service.correct_song(library, song_id, SongPatch(chords=fixes))
    fixed = [c for line in song.lines() for c in line.chords if c.text == first.text]
    assert len(fixed) == count and {c.chord for c in fixed} == {first.chord + "7"}
    assert song.corrections.chords == fixes
    song = service.correct_song(library, song_id, SongPatch(chords=[]))
    assert song.lines()[0].chords[0].chord == first.chord
    one = [ChordFix(original=first.text, to="", line=0, index=0)]  # remove just this one
    song = service.correct_song(library, song_id, SongPatch(chords=one))
    assert len(song.lines()[0].chords) == len(before.lines()[0].chords) - 1
    with pytest.raises(BadRequest, match="as a chord"):
        service.correct_song(
            library, song_id, SongPatch(chords=[ChordFix(original=first.text, to="Xyz")])
        )
    with pytest.raises(BadRequest, match="as a key"):
        service.correct_song(library, song_id, SongPatch(key="the usual one"))


def test_empty_patch_keeps_corrections(library, sheet_text):
    song_id = add_song(library, sheet_text, title="Kept")
    song = service.correct_song(library, song_id, SongPatch())
    assert song.identity.title == "Kept" and song.corrections.title == "Kept"


def test_song_saved_by_an_older_version_is_made_again(library, sheet_text):
    import sqlite3

    song_id = add_song(library, sheet_text, key="C")
    with sqlite3.connect(library.db) as conn:
        conn.execute("UPDATE songs SET song = '{}' WHERE id = ?", (song_id,))
    song = service.stored_song(library, song_id)
    assert song.id == song_id and song.key.concert.tonic == "C"  # corrections kept
    assert library.song_record(song_id).song == song


def test_delete(library, sheet_text):
    song_id = add_song(library, sheet_text)
    service.delete_song(library, song_id)
    with pytest.raises(NotFound):
        service.delete_song(library, song_id)


def test_source_pages(library, sheet_text, data_dir):
    pdf = (data_dir / "pdf" / "russian_two_pages.pdf").read_bytes()
    song_id = add_song(library, files=[("russian.pdf", pdf)])
    path = service.page_image(library, song_id, 1)
    assert path.read_bytes().startswith(b"\x89PNG")
    assert service.page_image(library, song_id, 1) == path  # drawn once, then kept
    with pytest.raises(NotFound, match="no page 3"):
        service.page_image(library, song_id, 2)
    text_id = add_song(library, sheet_text)
    with pytest.raises(NotFound, match="no source pages"):
        service.page_image(library, text_id, 0)


def test_song_deleted_while_a_correction_is_saved(library, sheet_text, monkeypatch):
    song_id = add_song(library, sheet_text)
    recompute = service.recompute

    def deleted_meanwhile(lib, record, corrections):
        lib.delete_song(record.id)
        return recompute(lib, record, corrections)

    monkeypatch.setattr(service, "recompute", deleted_meanwhile)
    with pytest.raises(NotFound):
        service.correct_song(library, song_id, SongPatch(key="C"))


@pytest.mark.parametrize(
    ("name", "head", "kind"),
    [
        ("song.wav", b"RIFF\x24\x08\x00\x00WAVEfmt ", "audio"),
        ("clip.avi", b"RIFF\x24\x08\x00\x00AVI LIST", "video"),
        ("picture.webp", b"RIFF\x24\x08\x00\x00WEBPVP8 ", "photo"),
        ("no_suffix", b"RIFF\x24\x08\x00\x00WEBPVP8 ", "photo"),
        ("no_suffix", b"RIFF\x24\x08\x00\x00WAVEfmt ", None),
    ],
)
def test_riff_files(name, head, kind):
    from soundselect.imports import file_kind

    assert file_kind(name, head) == kind
