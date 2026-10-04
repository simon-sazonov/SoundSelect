"""Sheet music (Phase 3): joining views, video capture, chord names, the score and the Song.

The test pictures are a public-domain lead sheet (Alexander's Ragtime Band) engraved and cut
into video-style views: three screenshots of three lines each, every one repeating the last line
of the one before, and a 14-second video with fades and a moving playback cursor. Reading notes
needs homr's downloaded models; those tests are skipped without them.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("cv2")
pytest.importorskip("music21")

import cv2
import numpy as np

from soundselect.core.song import ChordFix, Corrections
from soundselect.core.view import apply_instrument
from soundselect.sheetmusic import detect, score, stitch, text, video
from soundselect.sheetmusic.build import build_song, piece_key
from soundselect.sheetmusic.files import FileStore
from soundselect.sheetmusic.models import (
    ChordMark,
    Clean,
    PageBox,
    PageText,
    Read,
    SystemBars,
)
from soundselect.sheetmusic.pipeline import (
    Item,
    SheetMusicSource,
    fix_chords,
    make_clean,
    run_sheet_music,
)

DATA = Path(__file__).parent / "data" / "sheetmusic"
SHOTS = [DATA / f"screenshot_{i}.jpg" for i in (1, 2, 3)]


def _homr_ready() -> bool:
    if importlib.util.find_spec("homr") is None or importlib.util.find_spec("rapidocr") is None:
        return False
    from homr.main import default_config, segnet_path_onnx

    paths = [segnet_path_onnx, default_config.filepaths.encoder_path]
    return all(Path(p).exists() for p in paths)


needs_homr = pytest.mark.skipif(not _homr_ready(), reason="homr or its models aren't installed")


def _views() -> list[np.ndarray]:
    return [stitch.decode_image(p.read_bytes()) for p in SHOTS]


def _source(tmp_path: Path, kind: str = "screenshots") -> SheetMusicSource:
    paths = SHOTS if kind == "screenshots" else [DATA / "test_video.mp4"]
    items = tuple(
        Item(p.name, hashlib.sha256(p.read_bytes()).hexdigest(), p.read_bytes) for p in paths
    )
    return SheetMusicSource(kind, items, FileStore(tmp_path / "files"))  # type: ignore[arg-type]


# Joining views


def test_screenshots_join_into_seven_lines_in_order():
    lines = stitch.stitch(_views())
    # 3 screenshots x 3 lines, each repeating the previous one's last line: 7 different lines
    assert len(lines) == 7
    assert [ln.views for ln in lines] == [[0], [0], [0, 1], [1], [1, 2], [2], [2]]
    lay = stitch.layout(lines)
    assert len(lay.pages) == 1
    assert len(lay.staves) == 7
    page = lay.pages[0]
    assert page.shape == (3507, 2480)  # A4 at 300 dpi
    tops = [s.box.y0 for s in lay.staves]
    assert tops == sorted(tops)


def test_an_unchanged_view_adds_nothing():
    views = _views()
    assert len(stitch.stitch([views[0], views[0], views[1]])) == 5


def test_a_view_without_staves_is_skipped():
    blank = np.full((720, 1280, 3), 30, np.uint8)
    assert len(stitch.stitch([blank, *_views()])) == 7


def test_clean_copy_pdf(tmp_path):
    clean = make_clean_from_shots(tmp_path)
    pdf = stitch.clean_copy_pdf([np.full((100, 70), 255, np.uint8)])
    assert pdf.startswith(b"%PDF")
    assert clean.views == 3 and len(clean.systems) == 7


def make_clean_from_shots(tmp_path: Path) -> Clean:
    files = FileStore(tmp_path / "files")
    from soundselect.sheetmusic.models import Views

    shas = [files.put(p.read_bytes()) for p in SHOTS]
    return make_clean(Views(views=shas), files)


# Spotting sheet music


def test_screenshots_show_staves():
    assert all(detect.has_staves(p.read_bytes()) for p in SHOTS)


def _encode(img: np.ndarray) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def test_a_chord_sheet_has_no_staves():
    page = np.full((1100, 850), 255, np.uint8)
    for i, line in enumerate(["Am      F       C       G", "Hello darkness my old friend"] * 8):
        cv2.putText(page, line, (60, 80 + 60 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    assert not detect.has_staves(_encode(page))


def test_a_guitar_tab_is_not_a_staff():
    page = np.full((600, 1200), 255, np.uint8)
    for block in (100, 350):
        for k in range(6):
            cv2.line(page, (50, block + 14 * k), (1150, block + 14 * k), 0, 1)
    assert not detect.has_staves(_encode(page))


def test_spotting_never_raises():
    assert not detect.has_staves(b"not a picture")


# Video capture


def test_views_from_frames_drop_fades_and_the_cursor():
    views = _views()
    frames = []
    for i, v in enumerate(views):
        if i:  # a short fade from the previous view
            frames.append(cv2.addWeighted(views[i - 1], 0.5, v, 0.5, 0))
        for k in range(6):  # a cursor moving across the view
            f = v.copy()
            x = 100 + 150 * k
            cv2.rectangle(f, (x, 0), (x + 12, f.shape[0]), (255, 160, 90), -1)
            frames.append(f)
    runs = video.find_views(frames)
    assert len(runs) == 3
    cleaned = [video.clean_view(frames, r) for r in runs]
    assert len(stitch.stitch(cleaned)) == 7
    # the cursor is gone: the clean view matches the original screenshot
    assert np.abs(cleaned[0].astype(int) - views[0].astype(int)).mean() < 2


def test_video_file_gives_its_views():
    frames = video.sample(DATA / "test_video.mp4")
    assert 20 <= len(frames) <= 32  # 14 seconds at two a second
    views = video.views_of(frames)
    assert len(stitch.stitch(views)) == 7


def test_a_broken_video_says_so():
    with pytest.raises(video.VideoError):
        video.sample_bytes(b"not a video")


# Chord names


@pytest.mark.parametrize(
    ("token", "chord"),
    [("F", "F"), ("C7", "C7"), ("B2", "Bb"), ("B♭7", "Bb7"), ("F#m", "F#m"), ("G/B", "G/B")],
)
def test_chord_names_from_ocr(token, chord):
    assert text.chord_text(token) == chord


@pytest.mark.parametrize("token", ["Come", "and", "10", "N.C.", "hear"])
def test_words_are_not_chords(token):
    assert text.chord_text(token) is None


def test_barlines_found_on_the_clean_copy():
    lay = stitch.layout(stitch.stitch(_views()))
    first = lay.staves[0].box
    gray = lay.pages[0]
    # the first line has a pickup bar, a repeat sign and two more bars
    assert len(text.barlines(gray, (first.x0, first.y0, first.x1, first.y1))) == 4


@pytest.mark.parametrize(
    ("name", "instrument"),
    [
        ("Alto Sax", "alto_sax"),
        ("Alto Saxophone", "alto_sax"),
        ("A. Sax", "alto_sax"),
        ("Альт-саксофон", "alto_sax"),
        ("Tenor Sax", "tenor_sax"),
        ("Electric Piano", None),
        (None, None),
    ],
)
def test_part_names(name, instrument):
    assert text.part_instrument(name) == instrument


def test_chord_fixes():
    page = PageText(
        chords=[
            ChordMark(text="B", measure=1, position=0, system=0),
            ChordMark(text="F", measure=2, position=0, system=0),
            ChordMark(text="B", measure=5, position=0, system=1),
        ]
    )
    one = fix_chords(page, [ChordFix(original="B", to="Bb", line=1, index=0)])
    assert [m.text for m in one.chords] == ["B", "F", "Bb"]
    every = fix_chords(page, [ChordFix(original="B", to="Bb")])
    assert [m.text for m in every.chords] == ["Bb", "F", "Bb"]
    removed = fix_chords(page, [ChordFix(original="F", to="")])
    assert [m.text for m in removed.chords] == ["B", "B"]


# The score

PIECE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Alto Sax</part-name>
</score-part></part-list><part id="P1">
<measure number="1"><attributes><divisions>1</divisions><key><fifths>3</fifths></key>
<time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef>
</attributes>
<note><pitch><step>A</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
<note><pitch><step>C</step><alter>1</alter><octave>5</octave></pitch><duration>2</duration>
<type>half</type></note></measure>
<measure number="2">
<note><pitch><step>E</step><octave>5</octave></pitch><duration>1</duration><type>quarter</type></note>
<note><rest/><duration>1</duration><type>quarter</type></note>
<note><pitch><step>A</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
</measure></part></score-partwise>"""


def test_chords_go_on_the_nearest_note():
    s = score.parse(PIECE)
    beats = score.add_chords(
        s,
        [
            ChordMark(text="A", measure=1, position=0.0, system=0),
            ChordMark(text="E7", measure=1, position=0.55, system=0),
            ChordMark(text="D", measure=9, position=0.0, system=0),  # no such bar
        ],
    )
    assert beats == [0.0, 2.0, None]


def test_an_alto_page_is_moved_to_concert_pitch():
    built = score.build(
        [PIECE],
        [ChordMark(text="A", measure=1, position=0, system=0)],
        title="Test",
        composer=None,
        page_instrument="alto_sax",
    )
    assert built.moved.name == "-M6"
    s = score.parse(built.xml)
    assert score.key_fifths(s) == 0  # written A major is concert C major
    notes = [n.nameWithOctave for n in s.recurse().notes if not n.isChord]
    assert notes[:3] == ["C4", "E4", "G4"]
    assert "<root-step>C</root-step>" in built.xml
    assert "<root-alter>0" not in built.xml


def test_concert_keys_never_get_seven_sharps():
    page = PIECE.replace("<fifths>3</fifths>", "<fifths>-4</fifths>")  # written Ab major
    # Ab major down a major sixth is Cb major (7 flats); B major (5 sharps) is used instead
    s, moved = score.to_concert(score.parse(page), "alto_sax")
    assert abs(score.key_fifths(s)) <= 6
    assert moved.semitones == -9


def test_two_pages_join_with_bars_numbered_on():
    s = score.join_pages([PIECE, PIECE])
    numbers = [m.number for m in s.parts[0].getElementsByClass("Measure")]
    assert numbers == [1, 2, 3, 4]


def test_key_from_the_signature():
    from soundselect.core.chords import chord as ch
    from soundselect.core.pitch import Pitch

    major = piece_key(-1, [ch("F"), ch("C7"), ch("F")], Pitch.parse("F4"), None)
    assert major is not None and (major.concert.tonic, major.concert.mode) == ("F", "major")
    minor = piece_key(-1, [ch("Dm"), ch("A7"), ch("Dm")], Pitch.parse("D4"), None)
    assert minor is not None and (minor.concert.tonic, minor.concert.mode) == ("D", "minor")
    fixed = piece_key(-1, [], None, "G")
    assert fixed is not None and fixed.basis == "correction"
    assert piece_key(None, [], None, None) is None


def test_song_from_a_read_score():
    built = score.build(
        [PIECE],
        [
            ChordMark(text="A", measure=1, position=0, system=0),
            ChordMark(text="E7", measure=2, position=0, system=0),
            ChordMark(text="Xq", measure=2, position=0.5, system=0),
        ],
        title="Test",
        composer="Someone",
        page_instrument="alto_sax",
    )
    read = Read(
        xml=built.xml,
        moved=built.moved.name,
        measures=built.measures,
        chord_beats=built.chord_beats,
        page_instrument="alto_sax",
        part_name="Alto Sax",
    )
    clean = Clean(
        pages=["x"],
        width=2480,
        height=3507,
        systems=[PageBox(page=0, box=(177, 177, 2303, 500))],
        staves=[],
        views=2,
    )
    page = PageText(
        title="Test",
        composer="Someone",
        part_name="Alto Sax",
        chords=[
            ChordMark(text="A", measure=1, position=0, system=0),
            ChordMark(text="E7", measure=2, position=0, system=0),
            ChordMark(text="Xq", measure=2, position=0.5, system=0),
        ],
        systems=[SystemBars(first=1, count=2)],
    )
    song = build_song(
        clean,
        page,
        read,
        Corrections(),
        source="screenshots",
        source_name="a.png (+1)",
        fingerprint="f" * 64,
        fallback_title=None,
    )
    assert song.identity.title == "Test" and song.identity.artist == "Someone"
    assert (song.key.concert.tonic, song.key.concert.mode) == ("C", "major")
    assert song.key.basis == "signature"
    assert [c.symbol for c in song.chords] == ["C", "G7"]
    line = song.lines()[0]
    assert [(p.chord, p.beat, p.text) for p in line.chords] == [
        ("C", 0.0, "A"),
        ("G7", 4.0, "E7"),
        (None, None, "Xq"),
    ]
    assert line.source is not None and line.source.box == (177, 177, 2303, 500)
    assert [n.concert for n in song.melody.notes] == ["C4", "E4", "G4", None, "C4"]
    assert song.timing.time_signature == "4/4"
    assert song.sheet_music.page_instrument == "alto_sax"
    assert {n.code for n in song.notes} >= {"check_sheet", "page_transposed", "chord_unreadable"}
    alto = apply_instrument(song, "alto_sax")
    assert alto.view.written_key.tonic == "A"
    assert alto.scales[0].written.notes == ["A", "B", "C#", "E", "F#"]


def test_piece_written_for_alto_and_with_names():
    from soundselect.core.song import Identity, Song
    from soundselect.sheetmusic import engrave

    built = score.build([PIECE], [], title="T", composer=None, page_instrument="alto_sax")
    song = apply_instrument(
        Song(identity=Identity(title="My title", source="screenshots", fingerprint="0")), "alto_sax"
    )
    xml = engrave.piece_xml(song, built.xml, view="written", names="russian")
    s = score.parse(xml)
    assert [n.nameWithOctave for n in s.recurse().notes][:2] == ["A4", "C#5"]
    assert "<text>ля</text>" in xml
    assert "My title" in xml
    concert = engrave.piece_xml(song, built.xml, view="concert")
    assert [n.nameWithOctave for n in score.parse(concert).recurse().notes][:1] == ["C4"]


def test_piece_pdf():
    from soundselect.render.pdf import pdf_available
    from soundselect.sheetmusic import engrave

    if not pdf_available():
        pytest.skip("PDF output needs Pango")
    pdf = engrave.piece_pdf(PIECE, "Test")
    assert pdf.startswith(b"%PDF")


# The whole pipeline (needs homr's models)


def _notes(xml: str) -> list[tuple[int, float]]:
    s = score.parse(xml)
    out = []
    for n in s.parts[0].stripTies().flatten().notes:
        if n.isChord:
            out.append((max(p.midi for p in n.pitches), float(n.quarterLength)))
        elif hasattr(n, "pitch"):
            out.append((n.pitch.midi, float(n.quarterLength)))
    return out


def _matched(truth: list, got: list) -> int:
    import difflib

    sm = difflib.SequenceMatcher(a=truth, b=got, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks())


@needs_homr
@pytest.mark.parametrize("kind", ["screenshots", "video"])
def test_pipeline_reads_every_note(tmp_path, kind):
    from soundselect.pipeline.runner import MemoryCache

    cache = MemoryCache()
    result = run_sheet_music(_source(tmp_path, kind), cache=cache)
    truth = _notes((DATA / "ragtime_truth.musicxml").read_text(encoding="utf-8"))
    got = _notes(result["score"].xml)
    assert _matched(truth, got) >= 0.95 * len(truth)
    song = result["view"]
    assert song.sheet_music.systems == 7
    assert song.key.concert.fifths == 0
    assert {"F", "C7", "Bb", "G7"} <= {c.symbol for c in song.chords}
    # a correction re-runs only what comes after it
    again = run_sheet_music(_source(tmp_path, kind), corrections=Corrections(key="F"), cache=cache)
    assert again.ran == ["song", "view"]
    assert again["view"].key.concert.tonic == "F"


def test_a_dropped_flat_or_sharp_is_put_back():
    def lone(letter_and_sign: str) -> str:
        img = np.full((80, 200), 255, np.uint8)
        cv2.putText(img, letter_and_sign, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.8, 0, 3)
        ink = np.where((img < 128).any(axis=0))[0]
        rows = np.where((img < 128).any(axis=1))[0]
        word = text.Word(letter_and_sign[0], ink[0], rows[0], ink[-1], rows[-1])
        return text.lost_accidental(img, word)

    assert lone("F#") == "#"
    assert lone("F") == ""


def _registered() -> bool:
    from soundselect.pipeline import registry

    return "sheet_music" in registry.PIPELINES


@needs_homr
@pytest.mark.skipif(not _registered(), reason="the pipeline registry hook hasn't landed yet")
def test_downloads_for_a_sheet_music_song(client):
    from soundselect.sheetmusic.spec import source_of

    lib = client.app.state.library
    refs = [lib.store_input(p.read_bytes(), "photo", p.name) for p in SHOTS]
    result = run_sheet_music(source_of(refs, lib.read_input), cache=lib.cache)
    song = lib.add_song(result["view"], pipeline="sheet_music", inputs=refs)

    clean = client.get(f"/api/v1/songs/{song.id}/export?format=clean")
    assert clean.status_code == 200 and clean.content.startswith(b"%PDF")
    xml = client.get(f"/api/v1/songs/{song.id}/export?format=musicxml&names=none")
    assert xml.status_code == 200 and b"Alto sax" in xml.content
    sheet = client.get(f"/api/v1/songs/{song.id}/score?part=sheet&view=concert&format=svg")
    assert sheet.status_code == 200 and sheet.text.startswith("<svg")
    pdf = client.get(f"/api/v1/songs/{song.id}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    fixed = client.patch(f"/api/v1/songs/{song.id}", json={"page_instrument": "alto_sax"})
    assert fixed.status_code == 200
    assert fixed.json()["sheet_music"]["page_instrument"] == "alto_sax"


def test_only_sheet_music_has_a_clean_copy(client, sheet_text):
    batch = client.post("/api/v1/imports", data={"text": sheet_text}).json()
    song_id = batch["jobs"][0]["song_id"]
    assert client.get(f"/api/v1/songs/{song_id}/export?format=clean").status_code == 404
