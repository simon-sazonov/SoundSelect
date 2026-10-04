"""Reading the words on the page with RapidOCR: chord names above each staff, placed in their
bar by the barlines found in the picture, and the title, composer and part name at the top.

Chord names in a music font can lose their flat sign (B♭ read as "B2"), which is mended here;
the check screen shows anything that still looks wrong.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import numpy as np

from .models import ChordMark, SystemBars
from .staves import Image, find_systems, to_gray
from .stitch import PageStaff, sheet_region

CHORD = re.compile(
    r"^[A-H](#|b)?(maj|min|m|dim|aug|sus|add|M|°|ø|o|\+)?\d*(\([^)]*\))?(sus\d|add\d|b\d|#\d)*"
    r"(/[A-H](#|b)?)?$"
)
_lock = threading.Lock()
_reader = None


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def ocr_available() -> bool:
    try:
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


PAD = 30


def _pad(img: Image) -> Image:
    import cv2

    return cv2.copyMakeBorder(img, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def read_words(img: Image, dx: float = 0.0) -> list[Word]:
    """Words in a picture with their boxes; ``dx`` is added to every x."""
    global _reader
    if img.size == 0 or min(img.shape[:2]) < 8:
        return []
    from rapidocr import RapidOCR

    with _lock:
        if _reader is None:
            import logging

            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            _reader = RapidOCR()
        result = _reader(img)
    if result.boxes is None:
        return []
    words = []
    for box, text in zip(result.boxes, result.txts, strict=False):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        words.append(Word(str(text).strip(), min(xs) + dx, min(ys), max(xs) + dx, max(ys)))
    return [w for w in words if w.text]


def chord_text(token: str) -> str | None:
    """A chord name from an OCR token, or None when it isn't one."""
    t = token.strip().replace("♭", "b").replace("♯", "#").replace("Δ", "maj7")
    t = re.sub(r"^([A-G])[2,₂]", r"\1b", t)  # a music-font flat sign often comes back as "2"
    return t if CHORD.match(t) else None


def barlines(gray: Image, box: tuple[float, float, float, float]) -> list[float]:
    """x of each barline on a staff: vertical lines exactly the staff's height (stems stick out
    above or below it). Double bars and repeat signs count once."""
    x0, y0, x1, y1 = box
    top, bottom = round(y0), round(y1)
    sp = (bottom - top) / 4
    above, below = int(top - 0.6 * sp), int(bottom + 0.6 * sp)
    if above < 0 or below >= gray.shape[0]:
        return []
    runs: list[list[int]] = []
    for x in range(int(x0) + 2, min(int(x1) + 3, gray.shape[1])):
        col = gray[top : bottom + 1, x]
        if (col < 140).mean() > 0.97 and gray[above, x] > 200 and gray[below, x] > 200:
            if runs and x - runs[-1][-1] <= 2:
                runs[-1].append(x)
            else:
                runs.append([x])
    merged: list[list[float]] = []
    for x in (float(np.mean(r)) for r in runs):
        if merged and x - merged[-1][-1] < 1.2 * sp:
            merged[-1].append(x)
        else:
            merged.append([x])
    return [m[-1] for m in merged]


def lost_accidental(gray: Image, w: Word) -> str:
    """The accidental drawn after a lone chord letter that the reader dropped ('B' for B♭).

    A plain capital is at most about as wide as it is tall; past that, the strokes to the right
    of the letter are counted: one upright stroke is a flat, two are a sharp."""
    if w.x1 - w.x0 < 1.0 * w.height:
        return ""
    x0, x1 = int(w.x0 + 0.7 * w.height), int(w.x1)
    y0, y1 = int(w.y0), int(w.y1)
    glyph = gray[max(0, y0) : y1, max(0, x0) : x1] < 128
    if glyph.size == 0 or not glyph.any():
        return ""
    rows = np.where(glyph.any(axis=1))[0]
    tall = glyph.sum(axis=0) > 0.7 * (rows[-1] - rows[0] + 1)
    strokes = int(np.count_nonzero(np.diff(np.concatenate([[0], tall.astype(int)])) == 1))
    return {1: "b", 2: "#"}.get(strokes, "")


def read_chords(
    pages: list[Image], staves: list[PageStaff]
) -> tuple[list[ChordMark], list[SystemBars]]:
    """Chord names above the top staff of every system, each placed in its bar."""
    found: list[tuple[ChordMark, float]] = []
    bars: list[SystemBars] = []
    first = 1
    tops: dict[int, PageStaff] = {}
    for st in staves:
        if st.system not in tops or st.box.y0 < tops[st.system].box.y0:
            tops[st.system] = st
    for system, st in sorted(tops.items()):
        page = pages[st.page]
        gray = to_gray(page)
        b = st.box
        sp = (b.y1 - b.y0) / 4
        lines = barlines(gray, (b.x0, b.y0, b.x1, b.y1))
        ends_with_bar = bool(lines) and lines[-1] > b.x1 - 3 * sp
        count = len(lines) if ends_with_bar else len(lines) + 1
        bars.append(SystemBars(first=first, count=max(1, count)))
        # Only the strip above this staff, cut to its width and padded: isolated chord letters
        # are found reliably there, and the text finder misses them in a page-wide strip.
        top, left_edge = max(0, int(b.y0 - 5 * sp)), max(0, int(b.x0 - sp))
        strip = page[top : max(top + 1, int(b.y0 - 0.3 * sp)), left_edge : int(b.x1) + 1]
        for w in read_words(_pad(strip), dx=left_edge - PAD):
            if not (b.x0 + 3 * sp < w.x0 < b.x1):
                continue  # left of that is the clef (and a bar number above it)
            tokens = w.text.split()
            for token in tokens:
                chord = chord_text(token)
                if chord is None:
                    continue
                if len(tokens) == 1 and len(chord) == 1:
                    on_page = Word(w.text, w.x0, w.y0 + top - PAD, w.x1, w.y1 + top - PAD)
                    chord += lost_accidental(gray, on_page)
                k = sum(1 for x in lines if x < w.x0)  # bars before it on this system
                left = lines[k - 1] if k else b.x0 + 6 * sp  # past the clef and key
                right = lines[k] if k < len(lines) else b.x1
                pos = (w.x0 - left) / (right - left) if right > left else 0.0
                mark = ChordMark(
                    text=chord,
                    measure=first + k,
                    position=round(float(min(1.0, max(0.0, pos))), 3),
                    system=system,
                )
                found.append((mark, w.height))
        first += max(1, count)
    if not found:
        return [], bars
    # Chord names share one size; much smaller letters are fingerings or rehearsal marks.
    usual = float(np.median([h for _, h in found]))
    return [m for m, h in found if h >= 0.65 * usual], bars


_INSTRUMENT_WORDS = [
    ("alto_sax", r"alto\s*sax|a\.?\s*sax|sax(ophone)?\s*alto|альт.?саксофон|e\s*b\s*alto"),
    ("tenor_sax", r"tenor\s*sax|t\.?\s*sax|тенор.?саксофон"),
    ("soprano_sax", r"soprano\s*sax|сопрано.?саксофон"),
    ("baritone_sax", r"bari(tone)?\s*sax|баритон.?саксофон"),
]
PART_WORDS = re.compile(
    r"sax|piano|voice|vocal|violin|flute|clarinet|trumpet|guitar|bass|lead|melody|"
    r"in\s*[EB]\s*[b♭]|саксофон|фортепиано|голос",
    re.I,
)


def part_instrument(part_name: str | None) -> str | None:
    """The instrument a part name means, when the page is written for a transposing one."""
    if not part_name:
        return None
    text = part_name.casefold()
    for inst, pattern in _INSTRUMENT_WORDS:
        if re.search(pattern, text):
            return inst
    return None


def read_header(view: Image) -> tuple[str | None, str | None, str | None]:
    """Title, composer and part name from the top of the first view (above and left of its
    first system)."""
    sheet = sheet_region(view)
    gray = to_gray(sheet)
    systems, sp = find_systems(gray)
    if not systems or sp is None:
        return None, None, None
    first = systems[0][0]
    words: list[Word] = []
    head = sheet[: max(0, int(first.top - 4 * sp))]
    words += read_words(head)
    margin = sheet[int(first.top - 2 * sp) : int(systems[0][-1].bottom + 2 * sp), : first.x0]
    left = read_words(margin) if first.x0 > 4 * sp else []

    part = next((w.text for w in left + words if PART_WORDS.search(w.text)), None)
    text_words = [
        w
        for w in words
        if w.text != part and sum(c.isalpha() for c in w.text) >= 3 and not chord_text(w.text)
    ]
    title = composer = None
    if text_words:
        biggest = max(text_words, key=lambda w: w.height)
        title = biggest.text
        width = sheet.shape[1]
        right = [w for w in text_words if w is not biggest and w.x1 > 0.7 * width]
        if right:
            composer = max(right, key=lambda w: w.height).text
    return title, composer, part
