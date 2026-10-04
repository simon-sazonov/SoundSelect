"""PDF chord sheets made from text: every word read with its position on the page.

Positions become letter columns, so each chord stays over its syllable. With a typewriter-style
font (Courier) every letter has the same width and columns come straight from the positions.
With other fonts a chord line is lined up against the letters of the lyric line under it,
since that is what the writer lined it up with. Pages printed in two columns are read left
column first. Page numbers and web addresses in the page margins are left out.

Each line keeps where it sits on its page (in pixels of the page drawn at ``PAGE_DPI``), so a
screen can show the reading beside the original. A scanned PDF has pictures instead of text:
those pages go through the photo reader.
"""

from __future__ import annotations

import io
import re
import statistics
import threading
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from ...core.song import Notice, SourcePage, SourceRef
from ..lines import is_chord_line, tokenize
from ..model import SheetText, TextLine
from . import SheetInput, UnsupportedInput, register, register_pages

PAGE_DPI = 144
SCALE = PAGE_DPI / 72  # PDF positions are in points, 72 to the inch
MARGIN = 0.07  # top and bottom share of the page where page numbers and web addresses sit
BLOCK_GAP = 0.75  # a gap between lines this many line heights tall is a blank line

_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page|p\.|стр\.?|страница|seite)?\s*\d{1,3}\s*(?:(?:of|/|из|von)\s*\d{1,3})?\s*$",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b\S+\.(?:com|ru|net|org|io)/\S*", re.IGNORECASE)
_STAMP_RE = re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]\d{2,4},?\s+\d{1,2}:\d{2}")

# PDFium (pypdfium2) isn't safe to use from two threads at once, and page images are drawn
# in the web server's thread pool.
_pdfium_lock = threading.Lock()


class ScannedPdf(UnsupportedInput):
    """The PDF's pages are pictures, with no text to read."""


@dataclass
class _Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    font: str
    chars: list[tuple[float, float]]  # each letter's left and right edge
    col: int = 0
    fixed: bool = False  # in a font whose letters all have the same width

    @property
    def end(self) -> int:
        return self.col + len(self.text)

    def indent(self, cw: float) -> float:
        """The width of one space before this word: a letter's width in a fixed-width font,
        about a quarter of the font size in others."""
        return cw if self.fixed else 0.25 * self.size


@dataclass
class _Line:
    words: list[_Word] = field(default_factory=list)
    text: str = ""

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)


def _visible(page: Any) -> Any:
    """The part of the page a PDF viewer shows (its CropBox), which is what gets drawn."""
    from pdfplumber.utils import get_bbox_overlap

    box = get_bbox_overlap(page.cropbox, page.mediabox) or page.mediabox
    return page if tuple(box) == tuple(page.bbox) else page.crop(box)


def _words(page: Any) -> list[_Word]:
    """The page's words, with positions measured from the top left of the visible page."""
    ox, oy = float(page.bbox[0]), float(page.bbox[1])
    raw = page.extract_words(
        x_tolerance_ratio=0.15,
        y_tolerance=2,
        keep_blank_chars=False,
        use_text_flow=False,
        extra_attrs=["size", "fontname"],
        return_chars=True,
    )
    words = []
    for w in raw:
        text = w["text"].strip()
        if not text:
            continue
        x0, x1 = w["x0"] - ox, w["x1"] - ox
        chars = [(c["x0"] - ox, c["x1"] - ox) for c in w["chars"] if not c["text"].isspace()]
        if len(chars) != len(text):  # ligatures and the like: spread the word evenly
            step = (x1 - x0) / len(text)
            chars = [(x0 + i * step, x0 + (i + 1) * step) for i in range(len(text))]
        top, bottom = w["top"] - oy, w["bottom"] - oy
        words.append(_Word(text, x0, x1, top, bottom, w["size"], w["fontname"], chars))
    fixed = _fixed_fonts(words)
    for w in words:
        w.fixed = w.font in fixed
    return words


def _fixed_fonts(words: list[_Word]) -> set[str]:
    """Fonts whose letters all have the same width, like Courier."""
    widths: dict[str, list[float]] = {}
    for w in words:
        widths.setdefault(w.font, []).extend((x1 - x0) / w.size for x0, x1 in w.chars if x1 > x0)
    fixed = set()
    for font, ws in widths.items():
        if len(ws) >= 6:
            median = statistics.median(ws)
            if median and statistics.pstdev(ws) / median < 0.03:
                fixed.add(font)
    return fixed


def _group_lines(words: list[_Word]) -> list[_Line]:
    """Words at the same height make a line."""
    lines: list[_Line] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        middle = (w.top + w.bottom) / 2
        for line in reversed(lines[-3:]):
            if line.top - 0.2 * w.size <= middle <= line.bottom + 0.2 * w.size:
                line.words.append(w)
                break
        else:
            lines.append(_Line([w]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def _gutter(words: list[_Word], width: float) -> float | None:
    """The middle of the widest empty strip down the middle of the page, if there is one."""
    covered = [False] * (int(width) + 2)
    for w in words:
        for x in range(max(0, int(w.x0)), min(len(covered), int(w.x1) + 1)):
            covered[x] = True
    best: tuple[int, int] | None = None
    start = None
    for x in range(int(width * 0.25), int(width * 0.75) + 1):
        if covered[x]:
            start = None
            continue
        start = x if start is None else start
        if best is None or x - start > best[1] - best[0]:
            best = (start, x)
    if best is None or best[1] - best[0] < 12:
        return None
    return (best[0] + best[1]) / 2


def _columns(words: list[_Word], width: float, height: float) -> list[list[_Word]]:
    """Split a page printed in two columns, at a strip down the middle that no word crosses.

    A title running across both columns at the top doesn't count as crossing, and neither do
    page numbers and web addresses in the top and bottom margins.
    """
    rows = _group_lines(words)
    for skip in range(min(4, len(rows))):
        body = [w for row in rows[skip:] for w in row.words]
        inside = [w for w in body if MARGIN * height < w.top and w.bottom < (1 - MARGIN) * height]
        gutter = _gutter(inside, width)
        if gutter is None:
            continue
        left = [w for w in body if w.x1 < gutter]
        right = [w for w in body if w.x0 > gutter]
        if len(_group_lines(left)) >= 3 and len(_group_lines(right)) >= 3:
            head = [w for row in rows[:skip] for w in row.words]
            across = [w for w in body if w.x0 <= gutter <= w.x1]  # in the margins
            head += [w for w in across if w.top <= MARGIN * height]
            right += [w for w in across if w.top > MARGIN * height]
            return [head + left, right]
    return [words]


def _char_width(lines: list[_Line]) -> float:
    """The width of one letter: of the fixed-width font when the sheet uses one."""
    words = [w for line in lines for w in line.words]
    chosen = [w for w in words if w.fixed] or words
    widths = [x1 - x0 for w in chosen for x0, x1 in w.chars if x1 > x0]
    return statistics.median(widths) if widths else 6.0


def _place(line: _Line, left: float, cw: float) -> None:
    """Give each word its column. In a fixed-width font columns come from the positions; in
    others, words close together get one space and only wide gaps keep their width."""
    previous: _Word | None = None
    for w in line.words:
        at = round((w.x0 - left) / cw)
        if previous is None:
            w.col = max(0, round((w.x0 - left) / w.indent(cw)))
        elif (w.fixed and previous.fixed) or w.x0 - previous.x1 > 2.2 * cw:
            w.col = max(at, previous.end + 1)
        else:
            w.col = previous.end + 1
        previous = w


def _column_at(x: float, under: _Line, cw: float) -> int:
    """The letter column of the lyric line below that sits at position x."""
    letters = [(x0, x1, w.col + i) for w in under.words for i, (x0, x1) in enumerate(w.chars)]
    first = letters[0]
    if x < first[0]:
        return max(0, first[2] - round((first[0] - x) / under.words[0].indent(cw)))
    i = max(k for k, (x0, _, _) in enumerate(letters) if x0 <= x + 0.3 * cw)
    _, x1, col = letters[i]
    if x < x1:
        return col
    if i + 1 < len(letters):
        nx0, _, ncol = letters[i + 1]
        if nx0 - x < 0.5 * cw:
            return ncol
        return min(col + 1 + round((x - x1) / cw), ncol)
    return col + 1 + round((x - x1) / cw)


def _line_up_chords(lines: list[_Line], cw: float) -> None:
    """Put each chord line's chords over the letters they sit above in the next line."""
    for line, under in pairwise(lines):
        height = line.bottom - line.top
        if under.top - line.bottom > BLOCK_GAP * height or not is_chord_line(tokenize(line.text)):
            continue
        if is_chord_line(tokenize(under.text)):
            continue
        if all(w.fixed for w in line.words + under.words):
            continue  # columns from a fixed-width font are exact already
        previous: _Word | None = None
        for w in line.words:
            col = _column_at(w.x0, under, cw)
            w.col = max(col, previous.end + 1) if previous else col
            previous = w
        line.text = _text(line)


def _text(line: _Line) -> str:
    out = ""
    for w in line.words:
        out = out.ljust(w.col) + w.text
    return out


def _margin_noise(line: _Line, height: float) -> bool:
    if MARGIN * height < line.top and line.bottom < (1 - MARGIN) * height:
        return False
    text = line.text.strip()
    return bool(_PAGE_NUMBER_RE.match(text) or _URL_RE.search(text) or _STAMP_RE.match(text))


def _without_margin_noise(words: list[_Word], height: float) -> list[_Word]:
    """The words, less page numbers and web addresses in the margins, so that a centred page
    number doesn't join the two columns of a page."""
    kept = []
    for row in _group_lines(words):
        row.text = " ".join(w.text for w in row.words)
        if not _margin_noise(row, height):
            kept += row.words
    return kept


def _box(line: _Line) -> tuple[float, float, float, float]:
    return tuple(round(v * SCALE, 1) for v in (line.x0, line.top, line.x1, line.bottom))  # type: ignore[return-value]


def _page_lines(page: Any, number: int) -> list[TextLine]:
    words = _without_margin_noise(_words(page), float(page.height))
    out: list[TextLine] = []
    if not words:
        return out
    for column_words in _columns(words, float(page.width), float(page.height)):
        column = _group_lines(column_words)
        cw = _char_width(column)
        left = min(line.x0 for line in column)
        for line in column:
            _place(line, left, cw)
            line.text = _text(line)
        _line_up_chords(column, cw)
        kept = [ln for ln in column if not _margin_noise(ln, float(page.height))]
        if out and kept:
            out.append(TextLine(text=""))  # a new column starts like a new block
        previous_bottom = None
        for line in kept:
            if previous_bottom is not None:
                gap = line.top - previous_bottom
                if gap > BLOCK_GAP * (line.bottom - line.top):
                    out.append(TextLine(text=""))
            out.append(TextLine(text=line.text, source=SourceRef(page=number, box=_box(line))))
            previous_bottom = line.bottom
    return out


def _numbers(pages: list[int]) -> str:
    shown = [str(p + 1) for p in pages]
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


@register("pdf")
def read_pdf(inp: SheetInput) -> SheetText:
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    try:
        pdf = pdfplumber.open(io.BytesIO(inp.raw))
    except (PDFPasswordIncorrect, PdfminerException) as exc:
        if "password" in repr(exc).lower() or isinstance(exc, PDFPasswordIncorrect):
            raise UnsupportedInput("This PDF is locked with a password.") from exc
        raise UnsupportedInput("This file isn't a PDF that can be opened.") from exc

    lines: list[TextLine] = []
    by_page: list[list[TextLine]] = []
    pages: list[SourcePage] = []
    scanned: list[int] = []
    unreadable = 0
    with pdf:
        for number, whole_page in enumerate(pdf.pages):
            page = _visible(whole_page)
            pages.append(
                SourcePage(
                    index=number,
                    width=round(float(page.width) * SCALE),
                    height=round(float(page.height) * SCALE),
                )
            )
            page_lines = _page_lines(page, number)
            if not page_lines and page.images:
                scanned.append(number)
            unreadable += sum(line.text.count("(cid:") for line in page_lines)
            by_page.append(page_lines)

    notices: list[Notice] = []
    no_reader = False
    if scanned:
        from .photo import scan_pages

        try:
            for number, reading in scan_pages(inp.raw, scanned).items():
                by_page[number] = reading.lines
                notices += reading.notices
        except UnsupportedInput:
            if not any(by_page):
                raise ScannedPdf(
                    "This PDF is a scan: its pages are pictures, with no text inside, and the "
                    "photo reader isn't installed."
                ) from None
            no_reader = True
        else:
            scanned = [n for n in scanned if not by_page[n]]  # pictures with nothing to read
    for page_lines in by_page:
        if not page_lines:
            continue
        if lines:
            lines.append(TextLine(text=""))  # page break
        lines += page_lines

    if not lines:
        if scanned:
            raise ScannedPdf(
                "This PDF is a scan, and no writing was found on its pages. A sharper scan "
                "usually reads well."
            )
        raise UnsupportedInput("This PDF has no text in it.")
    if unreadable > 20:
        raise UnsupportedInput(
            "The text in this PDF can't be read: its fonts hide which letters they draw. "
            "Printing it again to a new PDF often fixes that."
        )
    if scanned:
        which = _numbers(scanned)
        notices.append(
            Notice(
                level="warning",
                code="scanned_pages",
                message=(
                    f"Page {which} of the PDF is a picture, and the photo reader isn't "
                    "installed, so it was skipped."
                    if len(scanned) == 1
                    else f"Pages {which} of the PDF are pictures, and the photo reader isn't "
                    "installed, so they were skipped."
                )
                if no_reader
                else f"No writing was found on page {which} of the PDF, so it was skipped."
                if len(scanned) == 1
                else f"No writing was found on pages {which} of the PDF, so they were skipped.",
            )
        )
    return SheetText(
        lines=lines,
        source="pdf",
        source_name=inp.name,
        fingerprint=inp.fingerprint("pdf"),
        pages=pages,
        notices=notices,
    )


def render_page_array(data: bytes, index: int, scale: float = SCALE) -> Any:
    """One page of a PDF drawn as an RGB array (for reading a scanned page)."""
    import numpy as np
    import pypdfium2 as pdfium

    with _pdfium_lock:
        pdf = pdfium.PdfDocument(data)
        try:
            if not 0 <= index < len(pdf):
                raise IndexError(f"the PDF has no page {index + 1}")
            return np.asarray(pdf[index].render(scale=scale).to_pil().convert("RGB"))
        finally:
            pdf.close()


def page_count(data: bytes) -> int:
    """How many pages the PDF has."""
    import pypdfium2 as pdfium

    with _pdfium_lock:
        pdf = pdfium.PdfDocument(data)
        try:
            return len(pdf)
        finally:
            pdf.close()


def render_page(data: bytes, index: int) -> bytes:
    """One page of a PDF drawn as a PNG at ``PAGE_DPI``, the size the line boxes refer to."""
    import pypdfium2 as pdfium

    with _pdfium_lock:
        pdf = pdfium.PdfDocument(data)
        try:
            if not 0 <= index < len(pdf):
                raise IndexError(f"the PDF has no page {index + 1}")
            image = pdf[index].render(scale=SCALE).to_pil()
            buffer = io.BytesIO()
            image.save(buffer, "PNG", optimize=True)
            return buffer.getvalue()
        finally:
            pdf.close()


register_pages("pdf", page_count, render_page)
