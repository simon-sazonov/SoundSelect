"""Drawing the staff with Verovio, the same engine the browser front end runs.

The SVG is adjusted to scale cleanly in a page (and to print through WeasyPrint): the outer
picture keeps its natural size but may shrink to fit, and the inner drawing fills it.
"""

from __future__ import annotations

import re
import threading
from importlib.resources import files
from typing import Any

import verovio

_lock = threading.Lock()
_toolkit: verovio.toolkit | None = None

BASE_OPTIONS: dict[str, Any] = {
    "adjustPageHeight": True,
    "header": "none",
    "footer": "none",
    "svgViewBox": True,
    "svgRemoveXlink": False,
    "fontTextLiberation": False,
    "smuflTextFont": "none",  # the music font is added once per page instead (music_font_css)
    "lyricSize": 3.4,
    "spacingLinear": 0.45,
    "spacingNonLinear": 0.6,
    "pageMarginLeft": 30,
    "pageMarginRight": 30,
    "pageMarginTop": 20,
    "pageMarginBottom": 10,
    "pageHeight": 60000,
}
LINE_HEIGHT = 300  # a page shorter than two lines of music holds one line


def _get_toolkit() -> verovio.toolkit:
    global _toolkit
    if _toolkit is None:
        verovio.enableLog(verovio.LOG_OFF)
        # Verovio keeps its default font folder per thread, set in the thread that imported
        # it; a toolkit first made in a web request's thread is given the folder itself.
        toolkit = verovio.toolkit(False)
        if not toolkit.setResourcePath(str(files("verovio") / "data")):
            raise RuntimeError("Verovio's music fonts are missing; reinstall verovio")
        _toolkit = toolkit
    return _toolkit


def draw(
    musicxml: str,
    *,
    width: int = 2000,
    scale: int = 40,
    wrap: bool = True,
    by_line: bool = False,
) -> str:
    """One SVG for a whole (short) score. ``width`` is the line width before scaling.

    ``by_line`` draws each line of music as an SVG of its own, so a long score (a melody) can
    break between lines when it is printed.
    """
    with _lock:
        tk = _get_toolkit()
        tk.setOptions(
            {
                **BASE_OPTIONS,
                "pageWidth": width,
                "scale": scale,
                "breaks": "auto" if wrap else "none",
                **({"pageHeight": LINE_HEIGHT} if by_line else {}),
            }
        )
        if not tk.loadData(musicxml):
            raise ValueError("the drawing engine could not read this score")
        pages = [tk.renderToSVG(i) for i in range(1, tk.getPageCount() + 1)]
    return fit_svg(pages[0]) if len(pages) == 1 else "\n".join(fit_svg(p) for p in pages)


_FONT_CSS: str | None = None


def music_font_css() -> str:
    """The @font-face rule for Verovio's music font, used by accidentals in chord symbols.

    Each drawing leaves the font out; a page includes this once.
    """
    global _FONT_CSS
    if _FONT_CSS is None:
        probe = (
            '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0"><part-list>'
            '<score-part id="P1"><part-name/></score-part></part-list><part id="P1">'
            '<measure number="1"><attributes><divisions>1</divisions></attributes><harmony><root>'
            "<root-step>B</root-step><root-alter>-1</root-alter></root><kind>major</kind>"
            "</harmony><note><pitch><step>B</step><octave>4</octave></pitch><duration>4"
            "</duration><type>whole</type></note></measure></part></score-partwise>"
        )
        with _lock:
            tk = _get_toolkit()
            tk.setOptions({**BASE_OPTIONS, "smuflTextFont": "embedded", "breaks": "none"})
            tk.loadData(probe)
            svg = tk.renderToSVG(1)
        rules = re.findall(r"@font-face\s*\{[^}]*\}", svg)
        _FONT_CSS = "\n".join(rules)
    return _FONT_CSS


TEXT_FONTS = "'Liberation Serif', 'Times New Roman', Times, serif"


def fit_svg(svg: str) -> str:
    """Give the SVG its natural width, let it shrink to fit, and make the inner drawing fill it."""
    m = re.search(r'<svg viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if m:
        w, h = m.group(1), m.group(2)
        svg = svg.replace(
            m.group(0),
            f'<svg class="staff" width="{w}px" height="{h}px" viewBox="0 0 {w} {h}"',
            1,
        )
    svg = svg.replace(
        '<svg class="definition-scale"',
        '<svg class="definition-scale" width="100%" height="100%"',
        1,
    )
    # Names and bar numbers in the font the drawing engine measured them with; the PDF maker
    # reads "Times, serif" as one unknown font and falls back to a wider one, so names collide.
    return svg.replace('font-family="Times, serif"', f'font-family="{TEXT_FONTS}"')
