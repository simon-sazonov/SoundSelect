"""A songbook: several songs in one document, with a contents page, each song on new pages.

Seven sheets in, one printable book out. The contents page numbers come from the PDF itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from markupsafe import Markup

from .. import __version__
from ..core.names import NameSystem, key_name
from ..core.song import Song
from .page import song_body, template
from .staff import music_font_css


@dataclass
class ContentsEntry:
    anchor: str
    title: str
    artist: str | None
    key: str | None


def songbook_html(
    songs: list[Song],
    names: NameSystem = "russian",
    *,
    written: bool = True,
    title: str = "Songbook",
) -> str:
    entries, bodies = [], []
    for n, song in enumerate(songs, start=1):
        key = None
        if written and song.view and song.view.written_key:
            key = key_name(song.view.written_key.to_key(), names)
        elif song.key:
            key = key_name(song.key.concert.to_key(), names)
        entries.append(
            ContentsEntry(
                f"song-{n}", song.identity.title or "Untitled song", song.identity.artist, key
            )
        )
        bodies.append(song_body(song, names, written=written))
    instrument = songs[0].view.name if written and songs and songs[0].view else "concert pitch"
    return template("songbook.html").render(
        title=title,
        entries=entries,
        bodies=bodies,
        instrument=instrument,
        music_font_css=Markup(music_font_css()),
        version=__version__,
        today=date.today().isoformat(),
    )
