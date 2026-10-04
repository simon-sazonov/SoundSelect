"""Photos and screenshots of chord sheets, scanned PDF pages, and songs spread over several
pictures.

A picture is prepared (page cut out, straightened, sized; see ``ocr.image``), its words are read
with their boxes (``ocr.engine``), and the words are laid out in lines the way the PDF reader
lays out a PDF's words: each chord goes over the letter of the lyric it sits above, pages
printed in two columns are read left column first, and page numbers and web addresses in the
margins are left out. Each line keeps its box on the prepared picture, so the song page can
show the reading beside the photo.

Reading mistakes that turn a chord into near-text are put right when the whole line then reads
as chords: two chords read without the space between them (``Bb/DCm7``), ``rn`` or a Cyrillic
``т`` read for ``m``,
and ``l`` read for a flat. (Cyrillic letters that look like Latin ones, and the ♯ and ♭
signs, the chord parser takes as they are.)

A group is several inputs that make one song (photos of a song that runs over two pages, or a
photo plus a scanned PDF): each is read in turn and the pages follow on, numbered across the
whole group.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass

from ...core.chords import parse_chord
from ...core.song import Notice, SourcePage, SourceRef
from ...ocr import engine as ocr
from ...ocr.image import Prepared, UnreadableImage, from_array, prepare
from ..lines import clean_chord_text, is_chord_line, tokenize
from ..model import SheetText, TextLine
from . import SheetInput, UnsupportedInput, detect_kind, read_sheet, register, register_pages
from .pdf import (
    BLOCK_GAP,
    SCALE,
    _char_width,
    _columns,
    _group_lines,
    _Line,
    _line_up_chords,
    _margin_noise,
    _place,
    _text,
    _without_margin_noise,
    _Word,
)

VERSION = "1"
SCAN_ZOOM = 2  # scanned PDF pages are read at twice the size they're shown at
UNSURE = 0.75  # a chord read less surely than this is pointed out

_CHORD_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rn"), "m"),  # "Arn" -> "Am"
    (re.compile(r"(?<=^[A-HА-ЕН])т"), "m"),  # Cyrillic т, read for m by the Russian model: "Ат"
    (re.compile(r"(?<=[A-H])\s*#"), "#"),
    (re.compile(r"^([A-H])l(?=$|[m7/])"), r"\1b"),  # "Bl" for "Bb" in some fonts
]


def _is_chord(text: str) -> bool:
    return parse_chord(clean_chord_text(text)) is not None


def _split(text: str) -> list[str] | None:
    """Chords read without the space between them ("Bb/DCm7"), split apart; None when the
    text can't be split into chords."""
    if _is_chord(text):
        return [text]
    for cut in range(len(text) - 1, 0, -1):
        if _is_chord(text[:cut]):
            rest = _split(text[cut:])
            if rest is not None:
                return [text[:cut], *rest]
    return None


def _as_chords(word: str) -> list[str] | None:
    """The word made into one or more chords by undoing common reading mistakes, or None when
    it is a chord already or can't be made into chords."""
    if _is_chord(word):
        return None
    fixed = word
    for pattern, repl in _CHORD_FIXES:
        fixed = pattern.sub(repl, fixed)
    return _split(fixed)


def _respread(word: _Word, text: str) -> None:
    """Give the word new text, its letters sharing out its width evenly."""
    step = (word.x1 - word.x0) / max(1, len(text))
    word.text = text
    word.chars = [(word.x0 + i * step, word.x0 + (i + 1) * step) for i in range(len(text))]


def _piece(word: _Word, start: int, text: str, total: int) -> _Word:
    """Part of a word, from letter ``start``, with its share of the word's width."""
    step = (word.x1 - word.x0) / max(1, total)
    x0 = word.x0 + start * step
    part = dataclasses.replace(word, text=text, x0=x0, x1=x0 + len(text) * step, chars=[])
    _respread(part, text)
    return part


def fix_chord_rows(words: list[_Word]) -> list[_Word]:
    """The words, with reading mistakes put right in rows that, once put right, are all
    chords."""
    out: list[_Word] = []
    for row in _group_lines(words):
        fixes = {id(w): _as_chords(w.text) for w in row.words}
        texts = [" ".join(fixes[id(w)] or [w.text]) for w in row.words]
        if not any(fixes.values()) or not is_chord_line(tokenize("  ".join(texts))):
            out += row.words
            continue
        for w in row.words:
            parts = fixes[id(w)]
            if not parts:
                out.append(w)
                continue
            total, at = sum(map(len, parts)), 0
            for text in parts:
                out.append(_piece(w, at, text, total))
                at += len(text)
    return out


@dataclass
class _OcrWord(_Word):
    score: float = 1.0


def _words(result: ocr.OcrResult, zoom: float = 1.0) -> list[_Word]:
    """The engine's words as layout words, in pixels of the picture shown (``zoom`` is how much
    larger the picture read was)."""
    words: list[_Word] = []
    for w in result.words:
        x0, y0, x1, y1 = (v / zoom for v in w.box)
        height = max(1.0, y1 - y0)
        word = _OcrWord(
            w.text, x0, x1, y0, y1, size=height / 1.2, font="ocr", chars=[], score=w.score
        )
        _respread(word, w.text)
        words.append(word)
    return words


def _box(line: _Line) -> tuple[float, float, float, float]:
    return (round(line.x0, 1), round(line.top, 1), round(line.x1, 1), round(line.bottom, 1))


def layout(words: list[_Word], width: float, height: float, page: int) -> list[TextLine]:
    """Words read on one picture as lines of text, chords over their syllables."""
    words = _without_margin_noise(words, height)
    out: list[TextLine] = []
    if not words:
        return out
    for column_words in _columns(words, width, height):
        column = _group_lines(column_words)
        cw = _char_width(column)
        left = min(line.x0 for line in column)
        for line in column:
            _place(line, left, cw)
            line.text = _text(line)
        _line_up_chords(column, cw)
        kept = [ln for ln in column if not _margin_noise(ln, height)]
        if out and kept:
            out.append(TextLine(text=""))  # a new column starts like a new block
        previous_bottom = None
        for line in kept:
            if previous_bottom is not None:
                gap = line.top - previous_bottom
                if gap > BLOCK_GAP * (line.bottom - line.top):
                    out.append(TextLine(text=""))
            out.append(TextLine(text=line.text, source=SourceRef(page=page, box=_box(line))))
            previous_bottom = line.bottom
    return out


@dataclass
class PageReading:
    lines: list[TextLine]
    page: SourcePage
    notices: list[Notice]


def _unsure(words: list[_Word]) -> int:
    """How many chords were read without much certainty."""
    return sum(
        1
        for w in words
        if isinstance(w, _OcrWord) and w.score < UNSURE and parse_chord(w.text) is not None
    )


def read_picture(prepared: Prepared, page: int, *, zoom: float = 1.0) -> PageReading:
    """Read one prepared picture as page ``page``. ``zoom`` > 1 means the picture is that much
    larger than the page as shown, and boxes are scaled back."""
    if not ocr.available():
        raise UnsupportedInput(
            "Reading photos needs the text recognition engine (rapidocr and onnxruntime), "
            "which isn't installed."
        )
    result = ocr.read_words(prepared.image)
    words = _words(result, zoom)
    words = fix_chord_rows(words)
    width, height = prepared.width / zoom, prepared.height / zoom
    lines = layout(words, width, height, page)
    notices = []
    if "eslav" in result.missing and result.unread:
        notices.append(
            Notice(
                level="warning",
                code="ocr_model_missing",
                message=f"Some writing on page {page + 1} couldn't be read. If it is Russian, "
                "that's because the model for reading Russian couldn't be downloaded (it needs "
                "the internet once). The chords are read as usual.",
            )
        )
    unsure = _unsure(words)
    if unsure:
        notices.append(
            Notice(
                level="warning",
                code="unsure_reading",
                message=f"{unsure} chord{'s were' if unsure > 1 else ' was'} hard to read on "
                f"page {page + 1}: check {'them' if unsure > 1 else 'it'} against the photo.",
            )
        )
    return PageReading(
        lines, SourcePage(index=page, width=round(width), height=round(height)), notices
    )


def _merge_notices(notices: list[Notice]) -> list[Notice]:
    seen: set[str] = set()
    out = []
    for n in notices:
        key = n.code if n.code == "ocr_model_missing" else n.message
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


@register("photo")
def read_photo(inp: SheetInput) -> SheetText:
    try:
        prepared = prepare(inp.raw)
    except UnreadableImage as exc:
        raise UnsupportedInput(str(exc)) from exc
    reading = read_picture(prepared, 0)
    if not any(line.text.strip() for line in reading.lines):
        raise UnsupportedInput(
            "No writing was found in this picture. A sharper photo, taken straight on in good "
            "light, usually reads well."
        )
    return SheetText(
        lines=reading.lines,
        source="photo",
        source_name=inp.name,
        fingerprint=inp.fingerprint("photo"),
        pages=[reading.page],
        notices=reading.notices,
    )


def scan_pages(data: bytes, indices: Sequence[int]) -> dict[int, PageReading]:
    """Pages of a PDF that are pictures, read as photos, with boxes in the page's shown size."""
    import numpy as np

    from .pdf import render_page_array

    out = {}
    for index in indices:
        rgb = render_page_array(data, index, SCALE * SCAN_ZOOM)
        prepared = from_array(np.ascontiguousarray(rgb[:, :, ::-1]))
        out[index] = read_picture(prepared, index, zoom=SCAN_ZOOM)
    return out


def _offset(lines: list[TextLine], by: int) -> list[TextLine]:
    out = []
    for line in lines:
        if line.source is not None:
            source = line.source.model_copy(update={"page": line.source.page + by})
            line = line.model_copy(update={"source": source})
        out.append(line)
    return out


@register("group")
def read_group(inp: SheetInput) -> SheetText:
    """Several inputs read as one song, their pages numbered on across the group."""
    if not inp.parts:
        raise UnsupportedInput("a group needs at least one file")
    lines: list[TextLine] = []
    pages: list[SourcePage] = []
    notices: list[Notice] = []
    names = []
    for part in inp.parts:
        sheet = read_sheet(part)
        start = len(pages)
        if lines and sheet.lines:
            lines.append(TextLine(text=""))  # the next picture starts a new block
        lines += _offset(sheet.lines, start)
        if sheet.pages:
            pages += [p.model_copy(update={"index": p.index + start}) for p in sheet.pages]
        notices += sheet.notices
        names.append(part.name or "file")
    kinds = {detect_kind(p) for p in inp.parts}
    return SheetText(
        lines=lines,
        source="photo" if kinds & {"photo", "pdf"} else "text",
        source_name=inp.name or " + ".join(names),
        fingerprint=inp.fingerprint("group"),
        pages=pages,
        notices=_merge_notices(notices),
    )


def render_photo(data: bytes, index: int) -> bytes:
    """The prepared photo as a PNG: the picture its line boxes refer to."""
    if index != 0:
        raise IndexError("a photo has one page")
    try:
        return prepare(data).png()
    except UnreadableImage as exc:
        raise IndexError(str(exc)) from exc


register_pages("photo", count=lambda data: 1, render=render_photo)


def group_input(parts: Sequence[SheetInput], name: str | None = None) -> SheetInput:
    return SheetInput(b"", name, kind="group", parts=tuple(parts))
