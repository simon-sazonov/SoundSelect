"""Joining views of a scrolling score into whole pages.

A sheet music video shows a few lines at a time. Each new view repeats the previous view's last
lines at its top (from none of them to all of them), so the views are cut into systems, the
repeats are found by matching pictures, and every system is kept once, in reading order. The
systems are then laid out on A4 pages at one staff size: the clean copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .staves import Image, Staff, find_systems, to_gray

STAFF_SPACING = 20.0  # line spacing that every system is scaled to before matching
MATCH = 0.8  # how alike two systems must be to count as the same line of music
DPI = 300
MARGIN_MM = 15
GAP_MM = 6


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def scaled(self, f: float, dx: float = 0.0, dy: float = 0.0) -> Box:
        return Box(self.x0 * f + dx, self.y0 * f + dy, self.x1 * f + dx, self.y1 * f + dy)


@dataclass
class Cut:
    """One system cut out of a view, with room above for chord names and below for lyrics."""

    img: Image
    spacing: float
    staves: list[Box]  # the staff boxes (top line to bottom line) inside ``img``
    edge: bool  # cut off by the top or bottom of the view


@dataclass
class Line:
    """A system kept for the clean copy, scaled to the common staff size."""

    img: Image
    staves: list[Box]
    edge: bool
    views: list[int] = field(default_factory=list)  # every view it appeared in


def sheet_bbox(img: Image) -> tuple[int, int, int, int]:
    """x, y, width, height of the largest bright area: the sheet without player frame or UI."""
    bright = (to_gray(img) > 200).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bright)
    if n < 2:
        return 0, 0, img.shape[1], img.shape[0]
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(v) for v in stats[k, :4])
    return x, y, w, h


def sheet_region(img: Image) -> Image:
    x, y, w, h = sheet_bbox(img)
    return img[y : y + h, x : x + w]


def cut_systems(img: Image) -> list[Cut]:
    gray = to_gray(img)
    systems, s = find_systems(gray)
    if not systems or s is None:
        return []
    height, cuts = gray.shape[0], []
    for i, group in enumerate(systems):
        top_line, bottom_line = group[0].top, group[-1].bottom
        top = int((systems[i - 1][-1].bottom + top_line) / 2) if i else 0
        last = i == len(systems) - 1
        bottom = height if last else int((bottom_line + systems[i + 1][0].top) / 2)
        top, bottom = max(top, int(top_line - 8 * s)), min(bottom, int(bottom_line + 8 * s) + 1)
        part = gray[top:bottom]
        ink = np.where((part < 200).sum(axis=1) > 0)[0]
        edge = bool(len(ink)) and (
            (top == 0 and ink[0] <= 1) or (bottom == height and ink[-1] >= part.shape[0] - 2)
        )
        a, b = (max(0, int(ink[0]) - 4), int(ink[-1]) + 5) if len(ink) else (0, part.shape[0])
        boxes = [_staff_box(t, top + a) for t in group]
        cuts.append(Cut(img[top + a : top + b], s, boxes, edge))
    return cuts


def _staff_box(t: Staff, dy: float) -> Box:
    return Box(t.x0, t.top - dy, t.x1, t.bottom - dy)


def _normalize(cut: Cut) -> Line:
    f = STAFF_SPACING / cut.spacing
    interp = cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC
    img = cv2.resize(cut.img, None, fx=f, fy=f, interpolation=interp)
    return Line(img, [b.scaled(f) for b in cut.staves], cut.edge)


def similarity(a: Image, b: Image) -> float:
    """How alike two systems are (1.0 = identical), allowing small shifts and video noise."""
    width = 800
    ga, gb = (to_gray(x) for x in (a, b))
    ga = cv2.resize(ga, (width, max(8, int(ga.shape[0] * width / ga.shape[1]))))
    gb = cv2.resize(gb, (width, max(8, int(gb.shape[0] * width / gb.shape[1]))))
    if abs(ga.shape[0] - gb.shape[0]) > 0.25 * max(ga.shape[0], gb.shape[0]):
        return 0.0
    big, small = (ga, gb) if ga.shape[0] >= gb.shape[0] else (gb, ga)
    pad = cv2.copyMakeBorder(big, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
    templ = small[:, 6:-6] if small.shape[1] > 20 else small
    result = cv2.matchTemplate(255 - pad, 255 - templ, cv2.TM_CCOEFF_NORMED)
    return float(result.max())


def stitch(views: list[Image], threshold: float = MATCH) -> list[Line]:
    """The systems of all views in reading order, each kept once.

    A view repeats the previous view's last k systems at its top (k from 0 to all); everything
    after them is new. Of two copies of a line, the one not cut off by the view's edge is kept.
    """
    kept: list[Line] = []
    previous: list[int] = []
    for vi, view in enumerate(views):
        current = [_normalize(c) for c in cut_systems(sheet_region(view))]
        if not current:
            continue  # a title card, a black frame, a transition
        overlap = 0
        for k in range(min(len(current), len(previous)), 0, -1):
            tail = previous[len(previous) - k :]
            if all(similarity(current[j].img, kept[tail[j]].img) >= threshold for j in range(k)):
                overlap = k
                break
        ids = []
        for j, line in enumerate(current):
            if j < overlap:
                sid = previous[len(previous) - overlap + j]
                old = kept[sid]
                old.views.append(vi)
                if old.edge and not line.edge:
                    old.img, old.staves, old.edge = line.img, line.staves, False
            else:
                line.views = [vi]
                kept.append(line)
                sid = len(kept) - 1
            ids.append(sid)
        previous = ids
    return kept


@dataclass
class PageStaff:
    page: int
    system: int
    box: Box
    grand: bool  # one of two or more staves joined into a system


@dataclass
class PageSystem:
    page: int
    box: Box
    views: list[int]


@dataclass
class Layout:
    pages: list[Image]  # grayscale A4 pages
    staves: list[PageStaff]
    systems: list[PageSystem]


def layout(lines: list[Line], dpi: int = DPI) -> Layout:
    """Every system top to bottom on A4 pages, all at one staff size."""
    width, height = int(210 / 25.4 * dpi), int(297 / 25.4 * dpi)
    margin, gap = int(MARGIN_MM / 25.4 * dpi), int(GAP_MM / 25.4 * dpi)
    if not lines:
        return Layout([], [], [])
    scale = min((width - 2 * margin) / ln.img.shape[1] for ln in lines)
    pages: list[Image] = [np.full((height, width), 255, np.uint8)]
    staves: list[PageStaff] = []
    systems: list[PageSystem] = []
    y = margin
    for si, line in enumerate(lines):
        g = cv2.resize(to_gray(line.img), None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        # clean paper, crisp ink
        g = np.where(g > 170, 255, np.clip((g.astype(int) - 40) * 1.6, 0, 255)).astype(np.uint8)
        g = g[: height - 2 * margin, : width - 2 * margin]
        if y + g.shape[0] > height - margin and y > margin:
            pages.append(np.full((height, width), 255, np.uint8))
            y = margin
        page = len(pages) - 1
        pages[page][y : y + g.shape[0], margin : margin + g.shape[1]] = g
        grand = len(line.staves) > 1
        for b in line.staves:
            staves.append(PageStaff(page, si, b.scaled(scale, margin, y), grand))
        systems.append(
            PageSystem(page, Box(margin, y, margin + g.shape[1], y + g.shape[0]), line.views)
        )
        y += g.shape[0] + gap
    return Layout(pages, staves, systems)


def encode_png(gray: Image) -> bytes:
    ok, buf = cv2.imencode(".png", gray)
    if not ok:
        raise ValueError("could not encode the picture")
    return buf.tobytes()


def decode_image(data: bytes) -> Image:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not a picture OpenCV can read")
    return img


def clean_copy_pdf(pages: list[Image], dpi: int = DPI) -> bytes:
    """The clean copy as one PDF, a page per A4 page."""
    import io

    from PIL import Image as PILImage

    if not pages:
        raise ValueError("no pages")
    pil = [PILImage.fromarray(p) for p in pages]
    out = io.BytesIO()
    pil[0].save(out, "PDF", save_all=True, append_images=pil[1:], resolution=dpi)
    return out.getvalue()
