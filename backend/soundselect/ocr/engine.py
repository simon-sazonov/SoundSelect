"""Reading the words in a picture, on this computer, with RapidOCR (PaddleOCR's models).

Two reading models work together. The one that comes with RapidOCR reads Latin letters, digits
and signs, so chords like ``F#m7`` and English lyrics; it can't read Cyrillic. PaddleOCR's East
Slavic model reads Russian, Ukrainian and Belarusian lyrics (and Latin letters too); it is
downloaded the first time it's needed (about 8 MB). Both read every piece of text the finder
outlines, and the more confident reading wins. When the East Slavic model can't be fetched,
reading goes on with the first model and says that Russian words may be missing.

Each word comes back with its box on the picture, so a chord can be placed over the syllable it
sits above and the song page can show which part of the photo each line came from.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in pixels of the picture

MIN_SCORE = 0.5  # readings less sure than this are dropped
SAME_BOX = 0.5  # two outlines overlapping this much (of the smaller) are the same text
CYRILLIC_SCORE = 0.6  # a Cyrillic reading at least this sure beats a Latin one

# The settings each reading model adds to RapidOCR's defaults, as strings RapidOCR turns into
# its own option values. "multi" is the model that ships inside RapidOCR's package.
MODELS: dict[str, dict[str, str]] = {
    "multi": {},
    "eslav": {"Rec.lang_type": "eslav", "Rec.ocr_version": "PP-OCRv5", "Rec.model_type": "mobile"},
}
DEFAULT_MODELS = ("multi", "eslav")

_ENUM_KEYS = {
    "Rec.lang_type": "LangRec",
    "Rec.ocr_version": "OCRVersion",
    "Rec.model_type": "ModelType",
}


@dataclass(frozen=True)
class OcrWord:
    """One word as read, with its box and how sure the reading is (0 to 1)."""

    text: str
    box: Box
    score: float
    segment: int  # the piece of text it was read in: words of one piece share a number
    model: str = "multi"


@dataclass
class OcrResult:
    words: list[OcrWord]
    missing: list[str] = field(default_factory=list)  # models that couldn't be loaded
    unread: int = 0  # pieces of writing found but not read (counted only when a model is missing)
    seconds: float = 0.0


_lock = threading.Lock()
_engines: dict[str, Any] = {}
_failed: dict[str, float] = {}  # when each model last failed to load
RETRY = 600.0  # seconds before trying a model that failed (to download) again


def available() -> bool:
    """Whether the reading engine is installed."""
    try:
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


def _params(name: str) -> dict[str, Any]:
    from rapidocr.utils import typings

    params: dict[str, Any] = {
        "Global.log_level": "error",
        "Global.text_score": MIN_SCORE,
        "Global.max_side_len": 4000,  # pictures arrive sized already; don't shrink them again
        "Det.box_thresh": 0.4,  # keep faint, lone letters such as a single "C" chord
    }
    for key, value in MODELS[name].items():
        enum_name = _ENUM_KEYS.get(key)
        params[key] = getattr(typings, enum_name)(value) if enum_name else value
    return params


def _engine(name: str) -> Any | None:
    """The engine for one reading model, made once; None when it can't be loaded."""
    import time

    if name in _engines:
        return _engines[name]
    if time.monotonic() - _failed.get(name, -RETRY) < RETRY:
        return None
    from rapidocr import RapidOCR

    try:
        engine = RapidOCR(params=_params(name))
    except Exception as exc:  # a failed download surfaces as many kinds of error
        log.warning("OCR model %s could not be loaded: %s", name, exc)
        _failed[name] = time.monotonic()
        return None
    _engines[name] = engine
    return engine


def _box(points: Any) -> Box:
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    return (
        round(float(pts[:, 0].min()), 1),
        round(float(pts[:, 1].min()), 1),
        round(float(pts[:, 0].max()), 1),
        round(float(pts[:, 1].max()), 1),
    )


def _spread(text: str, box: Box) -> list[tuple[str, Box]]:
    """Words of a piece of text with boxes shared out by letter count, when the engine gave
    no box for each word."""
    x0, y0, x1, y1 = box
    step = (x1 - x0) / max(1, len(text))
    out = []
    at = 0
    for word in text.split(" "):
        if word:
            out.append((word, (x0 + at * step, y0, x0 + (at + len(word)) * step, y1)))
        at += len(word) + 1
    return out


@dataclass
class _Piece:
    """One outlined piece of text, as one model read it."""

    box: Box
    text: str
    score: float
    words: list[tuple[str, Box]]
    model: str


def _pieces(output: Any, model: str) -> list[_Piece]:
    if getattr(output, "boxes", None) is None or getattr(output, "txts", None) is None:
        return []
    word_lines = list(output.word_results or [])
    usable = len(word_lines) == len(output.txts)
    pieces = []
    for i, (points, text, score) in enumerate(
        zip(output.boxes, output.txts, output.scores, strict=False)
    ):
        text = str(text).strip()
        if not text:
            continue
        box = _box(points)
        words: list[tuple[str, Box]] = []
        if usable:
            for item in word_lines[i]:
                if len(item) == 3 and item[2] is not None and str(item[0]).strip():
                    words.append((str(item[0]).strip(), _box(item[2])))
        if not words or "".join(w for w, _ in words) != text.replace(" ", ""):
            words = _spread(text, box)
        pieces.append(_Piece(box, text, float(score), words, model))
    return pieces


def _overlap(a: Box, b: Box) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller if smaller > 0 else 0.0


_CYRILLIC = re.compile(r"[\u0400-\u04ff]")


def _better(piece: _Piece, than: _Piece) -> bool:
    """Whether one reading of a piece of text beats another. Only the East Slavic model can
    read Cyrillic, and the other model reads a Russian word as look-alike Latin letters
    ("Капо" as "Kano") or as a lone sign, often quite surely; so a fair Cyrillic reading wins
    over one without Cyrillic. Otherwise the surer reading wins."""
    cyrillic, other = bool(_CYRILLIC.search(piece.text)), bool(_CYRILLIC.search(than.text))
    if cyrillic != other:
        return cyrillic and piece.score >= CYRILLIC_SCORE
    return piece.score > than.score + 0.02


def _merge(readings: list[list[_Piece]]) -> list[_Piece]:
    """One reading per piece of text: the better of the models' (see ``_better``)."""
    chosen: list[_Piece] = []
    for pieces in readings:
        for piece in pieces:
            same = next((c for c in chosen if _overlap(c.box, piece.box) > SAME_BOX), None)
            if same is None:
                chosen.append(piece)
            elif _better(piece, same):
                chosen[chosen.index(same)] = piece
    return chosen


def read_words(image: np.ndarray, models: Sequence[str] = DEFAULT_MODELS) -> OcrResult:
    """Every word in the picture (BGR array), each with its box, top to bottom."""
    import time

    started = time.perf_counter()
    readings: list[list[_Piece]] = []
    missing: list[str] = []
    with _lock:  # one picture at a time: the engines aren't made for sharing between threads
        for name in models:
            engine = _engine(name)
            if engine is None:
                missing.append(name)
                continue
            # RapidOCR keeps options from one call to the next, so every call names them all
            output = engine(image, use_det=True, use_cls=True, use_rec=True, return_word_box=True)
            readings.append(_pieces(output, name))
        pieces = _merge(readings)
        unread = 0
        if missing and _engines.get("multi") is not None:
            found = _engines["multi"](image, use_det=True, use_cls=False, use_rec=False)
            found_boxes = getattr(found, "boxes", None)
            boxes = [_box(points) for points in ([] if found_boxes is None else found_boxes)]
            unread = sum(1 for b in boxes if not any(_overlap(b, p.box) > SAME_BOX for p in pieces))
    words = [
        OcrWord(text, box, piece.score, segment, piece.model)
        for segment, piece in enumerate(pieces)
        for text, box in piece.words
    ]
    words.sort(key=lambda w: (w.box[1], w.box[0]))
    return OcrResult(words, missing, unread, round(time.perf_counter() - started, 2))
