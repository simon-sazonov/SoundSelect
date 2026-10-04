"""The re-engraved piece: the score read from the pictures, written for the player's instrument
(or in concert pitch), with note names under the notes when asked for, drawn fresh by Verovio
on A4 pages and printed to PDF.

The concert-pitch score is a saved step output, so asking for it again costs only the drawing.
"""

from __future__ import annotations

import threading
from html import escape
from importlib.resources import files as package_files
from typing import TYPE_CHECKING, Any, Literal

from ..core.names import NameSystem
from ..core.pitch import Interval, Pitch
from ..core.song import Song

if TYPE_CHECKING:
    from ..store import Library

PitchView = Literal["written", "concert"]
_lock = threading.Lock()
_toolkit: Any = None

PAGE_OPTIONS: dict[str, Any] = {
    "pageWidth": 2100,
    "pageHeight": 2970,
    "scale": 40,
    "pageMarginLeft": 100,
    "pageMarginRight": 100,
    "pageMarginTop": 80,
    "pageMarginBottom": 80,
    "spacingSystem": 14,
    "header": "auto",
    "footer": "none",
    "breaks": "auto",
    "svgViewBox": True,
    "smuflTextFont": "none",  # the music font goes in once per document (music_font_css)
    "lyricSize": 2.6,
}


def concert_xml(lib: Library, song_id: str) -> str:
    """The saved concert-pitch score of a sheet music song (made again if it isn't saved)."""
    from .. import service
    from .pipeline import run_sheet_music
    from .spec import source_of

    record = lib.song_record(song_id)
    if record is None:
        raise service.NotFound(f"No song with id {song_id!r}.")
    if record.pipeline != "sheet_music":
        raise service.NotFound("This song wasn't read from sheet music.")
    result = run_sheet_music(
        source_of(record.inputs, lib.read_input),
        corrections=record.corrections,
        view=service.view_settings(lib),
        cache=lib.cache,
    )
    return result["score"].xml


def piece_xml(
    song: Song, xml: str, *, view: PitchView = "written", names: NameSystem = "none"
) -> str:
    """The piece as MusicXML for the song's instrument (or in concert pitch), titled as the
    song is (a corrected title shows), with note names under the notes when asked for."""
    from . import score as scores

    s = scores.parse(xml)
    part_name = "Concert pitch"
    if view == "written" and song.view is not None:
        s = scores.transpose(s, Interval.parse(song.view.interval))
        part_name = song.view.name
    scores.name_parts(s, part_name)
    scores.set_title(s, song.identity.title, song.identity.artist)
    if names != "none":
        _add_names(s, names)
    return scores.to_xml(s)


def _add_names(s: Any, names: NameSystem) -> None:
    from ..render.musicxml import names_for

    for n in s.recurse().notes:
        if n.isChord or not hasattr(n, "pitch"):
            continue
        p = Pitch.parse(n.pitch.name.replace("-", "b"))
        for i, text in enumerate(names_for(p, names), start=1):
            n.addLyric(text, lyricNumber=i)


def _get_toolkit() -> Any:
    global _toolkit
    if _toolkit is None:
        import verovio

        verovio.enableLog(verovio.LOG_OFF)
        tk = verovio.toolkit(False)
        if not tk.setResourcePath(str(package_files("verovio") / "data")):
            raise RuntimeError("Verovio's music fonts are missing; reinstall verovio")
        _toolkit = tk
    return _toolkit


def svg_pages(xml: str) -> list[str]:
    """The piece drawn on A4 pages, one SVG each."""
    with _lock:
        tk = _get_toolkit()
        tk.setOptions(PAGE_OPTIONS)
        if not tk.loadData(xml):
            raise ValueError("the drawing engine could not read this score")
        return [tk.renderToSVG(i) for i in range(1, tk.getPageCount() + 1)]


def piece_html(pages: list[str], title: str | None) -> str:
    from ..render.staff import fit_svg, music_font_css

    body = "".join(f'<div class="page">{fit_svg(svg)}</div>' for svg in pages)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title or 'Sheet music')}</title><style>"
        f"{music_font_css()}"
        "@page{size:A4;margin:0}body{margin:0}"
        ".page{width:210mm;height:297mm;page-break-after:always;overflow:hidden}"
        ".page:last-child{page-break-after:auto}"
        ".page>svg{width:210mm !important;height:297mm !important}"
        f"</style></head><body>{body}</body></html>"
    )


def piece_pdf(xml: str, title: str | None) -> bytes:
    from ..render.pdf import html_to_pdf

    return html_to_pdf(piece_html(svg_pages(xml), title))


def piece_svg(xml: str) -> str:
    """The piece as one long SVG for the screen (the page breaks are the browser's job)."""
    from ..render.staff import draw

    return draw(xml, width=2100, scale=40)
