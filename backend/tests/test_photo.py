"""Reading chord sheets from photos, screenshots, scanned PDFs and groups of pictures.

The pictures in data/photos are made from the sample sheets by data/photos/make.py.
"""

import io

import numpy as np
import pytest
from PIL import Image

from soundselect.ocr import engine, image
from soundselect.pipeline.chord_sheet import analyze_sheet
from soundselect.sheets.readers import SheetInput, UnsupportedInput, read_sheet
from soundselect.sheets.readers.photo import _as_chords, group_input, render_photo


@pytest.fixture
def photos(data_dir):
    return data_dir / "photos"


def stripped(line):
    """Lyrics without their indent, and chord positions counted from the first letter."""
    indent = len(line.lyrics) - len(line.lyrics.lstrip())
    return line.lyrics.strip(), [(c.chord, c.pos - indent) for c in line.chords]


def reads_like(song, expected):
    """Same key, title and chords as the text, each chord within a letter of its place."""
    assert song.key.concert == expected.key.concert
    assert (song.identity.title, song.identity.artist) == (
        expected.identity.title,
        expected.identity.artist,
    )
    assert [c.symbol for c in song.chords] == [c.symbol for c in expected.chords]
    for read, truth in zip(song.lines(), expected.lines(), strict=True):
        read_lyrics, read_chords = stripped(read)
        truth_lyrics, truth_chords = stripped(truth)
        assert read_lyrics == truth_lyrics
        assert [c for c, _ in read_chords] == [c for c, _ in truth_chords]
        for (_, a), (_, b) in zip(read_chords, truth_chords, strict=True):
            assert abs(a - b) <= 1, (read.lyrics, read_chords, truth_chords)


def test_screenshot(photos, found_a_love):
    song = analyze_sheet(photos / "screenshot.png")
    reads_like(song, found_a_love)
    assert song.identity.source == "photo"
    assert not song.notes


def test_phone_photo(photos, found_a_love):
    """At an angle on a dark table, tilted, soft and grainy: the page is cut out first."""
    song = analyze_sheet(photos / "photo.jpg")
    reads_like(song, found_a_love)
    assert image.prepare((photos / "photo.jpg").read_bytes()).steps[0] == "page"


def test_line_boxes_point_at_the_picture(photos):
    data = (photos / "screenshot.png").read_bytes()
    sheet = read_sheet(SheetInput(data, "screenshot.png"))
    [page] = sheet.pages
    png = Image.open(io.BytesIO(render_photo(data, 0)))
    assert png.size == (page.width, page.height)
    first = next(line for line in sheet.lines if line.text.strip())
    x0, y0, x1, y1 = first.source.box
    assert 0 <= x0 < x1 <= page.width and 0 <= y0 < y1 < page.height * 0.15  # the title, on top
    with pytest.raises(IndexError):
        render_photo(data, 1)


def _rotated_with_tag(data: bytes, orientation: int) -> bytes:
    """The picture turned on its side, with the tag that tells a viewer to turn it back."""
    im = Image.open(io.BytesIO(data))
    turned = im.transpose(Image.Transpose.ROTATE_90 if orientation == 6 else Image.ROTATE_270)
    exif = Image.Exif()
    exif[0x0112] = orientation
    buffer = io.BytesIO()
    turned.convert("RGB").save(buffer, "JPEG", quality=92, exif=exif)
    return buffer.getvalue()


@pytest.mark.parametrize("orientation", [6, 8])
def test_orientation_tag(photos, found_a_love, orientation):
    data = _rotated_with_tag((photos / "screenshot.png").read_bytes(), orientation)
    reads_like(analyze_sheet(SheetInput(data, "turned.jpg")), found_a_love)


def test_tilted_photo_is_straightened(photos, found_a_love):
    im = Image.open(photos / "screenshot.png").convert("RGB")
    tilted = im.rotate(3.0, expand=True, fillcolor="white", resample=Image.BICUBIC)
    buffer = io.BytesIO()
    tilted.save(buffer, "PNG")
    prepared = image.prepare(buffer.getvalue())
    assert any(step.startswith("tilt") for step in prepared.steps)
    angle = float(prepared.steps[-1].split()[1])
    assert abs(angle + 3.0) <= 0.5  # turned back by about the 3 degrees it was tilted
    reads_like(analyze_sheet(SheetInput(buffer.getvalue(), "tilted.png")), found_a_love)


def test_heic_photo(photos, found_a_love):
    pillow_heif = pytest.importorskip("pillow_heif")
    im = Image.open(photos / "screenshot.png").convert("RGB")
    heif = pillow_heif.from_pillow(im)
    buffer = io.BytesIO()
    heif.save(buffer, quality=90)
    reads_like(analyze_sheet(SheetInput(buffer.getvalue(), "IMG_0001.HEIC")), found_a_love)


def test_group_of_two_pictures(photos, found_a_love):
    parts = [SheetInput.from_path(photos / name) for name in ("page1.png", "page2.png")]
    song = analyze_sheet(group_input(parts))
    reads_like(song, found_a_love)
    assert [p.index for p in song.source_pages] == [0, 1]
    pages = [line.source.page for line in song.lines()]
    assert pages == sorted(pages) and set(pages) == {0, 1}
    assert song.identity.source_name == "page1.png + page2.png"


def test_group_identity(photos):
    a, b = (SheetInput.from_path(photos / n) for n in ("page1.png", "page2.png"))
    same = group_input([SheetInput(a.raw, "other.png"), b])
    assert group_input([a, b]).fingerprint("group") == same.fingerprint("group")
    assert group_input([a, b]).fingerprint("group") != group_input([b, a]).fingerprint("group")


def test_scanned_pdf_goes_to_the_photo_reader(data_dir, found_a_love):
    song = analyze_sheet(data_dir / "pdf" / "scanned.pdf")
    assert song.key.concert == found_a_love.key.concert
    assert [c.symbol for c in song.chords] == [c.symbol for c in found_a_love.chords]
    assert song.identity.source == "pdf" and song.source_pages[0].index == 0
    boxes = [line.source.box for line in song.lines()]
    width, height = song.source_pages[0].width, song.source_pages[0].height
    assert all(0 <= b[0] < b[2] <= width and 0 <= b[1] < b[3] <= height for b in boxes)


def test_not_a_picture():
    with pytest.raises(UnsupportedInput, match="isn't a picture that can be opened"):
        read_sheet(SheetInput(b"\xff\xd8\xff and then nothing", "photo.jpg"))


def test_blank_picture():
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1200), "white").save(buffer, "PNG")
    with pytest.raises(UnsupportedInput, match="No writing was found"):
        read_sheet(SheetInput(buffer.getvalue(), "blank.png"))


def test_engine_missing(monkeypatch, photos):
    monkeypatch.setattr(engine, "available", lambda: False)
    with pytest.raises(UnsupportedInput, match="isn't installed"):
        read_sheet(SheetInput.from_path(photos / "screenshot.png"))


@pytest.mark.parametrize(
    ("read", "chords"),
    [
        ("Am", None),  # a chord already
        ("Аm", None),  # Russian А: the chord parser reads it as it is
        ("Arn", ["Am"]),
        ("Bl", ["Bb"]),  # a flat in some fonts
        ("Bbm7", None),
        ("Bb/DCm7", ["Bb/D", "Cm7"]),  # no space between them
        ("CGAm", ["C", "G", "Am"]),
        ("Солнце", None),
        ("Hello", None),
    ],
)
def test_reading_mistakes_put_right(read, chords):
    assert _as_chords(read) == chords


def test_russian_photo(photos, russian_song):
    """Cyrillic lyrics need the East Slavic model, downloaded once; skipped without it."""
    if engine._engine("eslav") is None:
        pytest.skip("the East Slavic reading model can't be downloaded here")
    song = analyze_sheet(photos / "russian_photo.jpg")
    assert song.key.concert == russian_song.key.concert
    assert [c.symbol for c in song.chords] == [c.symbol for c in russian_song.chords]
    read = [stripped(line)[0] for line in song.lines()]
    truth = [stripped(line)[0] for line in russian_song.lines()]
    same = sum(a == b for a, b in zip(read, truth, strict=False))
    assert same >= 0.8 * len(truth), (read, truth)


def test_tilt_of_a_clean_page_is_zero(photos):
    data = np.asarray(Image.open(photos / "screenshot.png").convert("RGB"))[:, :, ::-1]
    assert image.tilt(np.ascontiguousarray(data)) == 0.0


def test_photos_through_the_app(client, photos, found_a_love):
    """Two photos stacked into one song, and a photo of its own, from upload to page image."""
    files = [
        ("files", (name, (photos / name).read_bytes(), "image/png"))
        for name in ("page2.png", "page1.png", "screenshot.png")
    ]
    res = client.post("/api/v1/imports", files=files, data={"groups": "[[1, 0]]"})
    assert res.status_code == 202, res.text
    jobs = res.json()["jobs"]
    assert [(j["name"], j["status"]) for j in jobs] == [
        ("page1.png, page2.png", "done"),
        ("screenshot.png", "done"),
    ]
    song = client.get(f"/api/v1/songs/{jobs[0]['song_id']}").json()
    assert song["key"]["concert"] == found_a_love.key.concert.model_dump(mode="json")
    pages = song["source_pages"]
    assert [p["index"] for p in pages] == [0, 1]
    image = client.get(f"/api/v1/songs/{jobs[0]['song_id']}/pages/1.png")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert Image.open(io.BytesIO(image.content)).size == (pages[1]["width"], pages[1]["height"])
