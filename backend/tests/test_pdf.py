"""Reading chord sheets from PDFs: typewriter and word-processor sheets, columns, margins."""

import io

import pypdfium2 as pdfium
import pytest

from soundselect.pipeline.chord_sheet import analyze_sheet
from soundselect.sheets.readers import SheetInput, UnsupportedInput, read_sheet
from soundselect.sheets.readers.pdf import PAGE_DPI, ScannedPdf, render_page


@pytest.fixture
def pdfs(data_dir):
    return data_dir / "pdf"


def chords(song):
    return [[(c.chord, c.pos) for c in line.chords] for line in song.lines()]


def lyrics(song):
    return [line.lyrics for line in song.lines()]


def same_song(a, b):
    assert (a.identity.title, a.identity.artist) == (b.identity.title, b.identity.artist)
    assert a.key.concert == b.key.concert
    assert [c.symbol for c in a.chords] == [c.symbol for c in b.chords]


@pytest.mark.parametrize("name", ["found_a_love_mono.pdf", "two_columns.pdf"])
def test_typewriter_pdfs_read_like_the_text(pdfs, found_a_love, name):
    song = analyze_sheet(pdfs / name)
    same_song(song, found_a_love)
    assert lyrics(song) == lyrics(found_a_love)
    assert chords(song) == chords(found_a_love)  # every chord over the same letter
    assert song.identity.source == "pdf" and song.identity.source_name == name


def test_word_processor_pdf(pdfs, found_a_love):
    """Chords typed with spaces in a proportional font land within a letter of their place."""
    song = analyze_sheet(pdfs / "found_a_love_word.pdf")
    same_song(song, found_a_love)
    assert lyrics(song) == lyrics(found_a_love)
    for read, expected in zip(song.lines(), found_a_love.lines(), strict=True):
        assert [c.chord for c in read.chords] == [c.chord for c in expected.chords]
        for a, b in zip(read.chords, expected.chords, strict=True):
            assert abs(a.pos - b.pos) <= 1, (read.lyrics, a, b)


def test_margins_and_page_breaks(pdfs, russian_song):
    song = analyze_sheet(pdfs / "russian_two_pages.pdf")
    same_song(song, russian_song)
    assert lyrics(song) == lyrics(russian_song)
    text = " ".join(lyrics(song))
    assert "amdm" not in text and "Страница" not in text  # web address, page numbers
    for read, expected in zip(song.lines(), russian_song.lines(), strict=True):
        assert [c.chord for c in read.chords] == [c.chord for c in expected.chords]
        for a, b in zip(read.chords, expected.chords, strict=True):
            if b.pos < len(expected.lyrics):  # past the end of the words, spacing is free
                assert abs(a.pos - b.pos) <= 1, (read.lyrics, a, b)
    assert [p.index for p in song.source_pages] == [0, 1]
    assert {line.source.page for line in song.lines()} == {0, 1}


def test_line_boxes(pdfs):
    song = analyze_sheet(pdfs / "found_a_love_mono.pdf")
    page = song.source_pages[0]
    assert (page.width, page.height) == (1191, 1684)  # A4 at 144 dpi
    assert PAGE_DPI == 144
    boxes = [line.source.box for line in song.lines()]
    for x0, y0, x1, y1 in boxes:
        assert 0 <= x0 < x1 <= page.width and 0 <= y0 < y1 <= page.height
    tops = [box[1] for box in boxes]
    assert tops == sorted(tops)  # one column, top to bottom


def test_page_images(pdfs):
    data = (pdfs / "russian_two_pages.pdf").read_bytes()
    png = render_page(data, 1)
    assert png.startswith(b"\x89PNG")
    from PIL import Image

    assert Image.open(io.BytesIO(png)).size == (1191, 1684)
    with pytest.raises(IndexError):
        render_page(data, 2)


def with_footer(path, text: str) -> bytes:
    """The PDF with ``text`` centred at the foot of its first page (built-in Helvetica)."""
    import ctypes

    pdf = pdfium.PdfDocument(path)
    page = pdf[0]
    width, _ = page.get_size()
    raw = pdfium.raw
    obj = raw.FPDFPageObj_NewTextObj(pdf.raw, b"Helvetica", ctypes.c_float(9))
    encoded = (text + "\0").encode("utf-16-le")
    raw.FPDFText_SetText(
        obj, ctypes.cast(ctypes.c_char_p(encoded), ctypes.POINTER(ctypes.c_ushort))
    )
    raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, width / 2 - 2.2 * len(text), 30)
    raw.FPDFPage_InsertObject(page.raw, obj)
    raw.FPDFPage_GenerateContent(page.raw)
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def test_two_columns_with_a_page_number_in_the_footer(pdfs, found_a_love, tmp_path):
    """A centred footer sits across the gap between the columns; it mustn't hide the gap."""
    path = tmp_path / "two_columns_footer.pdf"
    path.write_bytes(with_footer(pdfs / "two_columns.pdf", "Page 1 of 1"))
    song = analyze_sheet(path)
    same_song(song, found_a_love)
    assert lyrics(song) == lyrics(found_a_love)
    assert chords(song) == chords(found_a_love)
    assert "Page" not in " ".join(lyrics(song))


def test_cropped_pdf(pdfs, found_a_love, tmp_path):
    """Sizes and line boxes are those of the visible (cropped) page, as it is drawn."""
    pdf = pdfium.PdfDocument(pdfs / "found_a_love_mono.pdf")
    width, height = pdf[0].get_size()
    pdf[0].set_cropbox(30, 40, width - 50, height - 20)
    path = tmp_path / "cropped.pdf"
    with path.open("wb") as f:
        pdf.save(f)
    pdf.close()

    song = analyze_sheet(path)
    assert lyrics(song) == lyrics(found_a_love)
    page = song.source_pages[0]
    from PIL import Image

    image = Image.open(io.BytesIO(render_page(path.read_bytes(), 0)))
    assert (page.width, page.height) == image.size
    assert page.width == round((width - 80) * PAGE_DPI / 72)
    uncropped = analyze_sheet(pdfs / "found_a_love_mono.pdf")
    for a, b in zip(song.lines(), uncropped.lines(), strict=True):
        x0, y0, _, _ = a.source.box
        bx0, by0, _, _ = b.source.box
        assert abs(x0 - (bx0 - 30 * 2)) <= 1  # the crop's left edge, in pixels
        assert abs(y0 - (by0 - 20 * 2)) <= 1  # the crop's top edge (20 points from the top)


def test_page_images_from_many_threads(pdfs):
    """PDFium can't draw from two threads at once; page images are drawn in a thread pool."""
    from concurrent.futures import ThreadPoolExecutor

    data = (pdfs / "russian_two_pages.pdf").read_bytes()
    expected = render_page(data, 0)
    with ThreadPoolExecutor(8) as pool:
        images = list(pool.map(lambda i: render_page(data, i % 2), range(40)))
    assert all(png.startswith(b"\x89PNG") for png in images)
    assert images[0] == expected


def test_scanned_pdf(pdfs, monkeypatch):
    """A scan is read by the photo reader (see test_photo); without one it can't be read."""
    from soundselect.ocr import engine

    monkeypatch.setattr(engine, "available", lambda: False)
    with pytest.raises(ScannedPdf, match="This PDF is a scan"):
        read_sheet(SheetInput.from_path(pdfs / "scanned.pdf"))
    assert issubclass(ScannedPdf, UnsupportedInput)


def joined(*paths) -> bytes:
    out = pdfium.PdfDocument.new()
    for path in paths:
        out.import_pages(pdfium.PdfDocument(path))
    buffer = io.BytesIO()
    out.save(buffer)
    return buffer.getvalue()


def test_partly_scanned_pdf(pdfs, found_a_love, monkeypatch):
    data = joined(pdfs / "found_a_love_mono.pdf", pdfs / "scanned.pdf")
    song = analyze_sheet(SheetInput(data, "mixed.pdf"))
    assert [c.symbol for c in song.chords] == [c.symbol for c in found_a_love.chords]
    assert {line.source.page for line in song.lines()} == {0, 1}  # the scan is read too
    assert not song.notes

    from soundselect.ocr import engine

    monkeypatch.setattr(engine, "available", lambda: False)
    song = analyze_sheet(SheetInput(data, "mixed2.pdf"))
    assert lyrics(song) == lyrics(found_a_love)
    notes = " ".join(n.message for n in song.notes)
    assert "Page 2 of the PDF is a picture, and the photo reader isn't installed" in notes


def test_pdf_without_text():
    blank = pdfium.PdfDocument.new()
    blank.new_page(595, 842)
    buffer = io.BytesIO()
    blank.save(buffer)
    with pytest.raises(UnsupportedInput, match="no text"):
        read_sheet(SheetInput(buffer.getvalue(), "blank.pdf"))


def test_not_a_pdf():
    with pytest.raises(UnsupportedInput, match="isn't a PDF"):
        read_sheet(SheetInput(b"%PDF-1.7 and then nothing", "broken.pdf"))
