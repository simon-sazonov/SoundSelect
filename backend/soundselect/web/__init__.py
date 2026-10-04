"""The simple screens the back end serves, so SoundSelect can be used day to day before the
real front end is built: import, batch progress, the song page with fixes, library, settings.

They are plain pages with a little JavaScript that calls the same API as the front end will.
"""

from __future__ import annotations

from functools import cache
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from .. import __version__, service
from ..core.instruments import INSTRUMENTS, get_instrument
from ..core.keys import Key
from ..core.names import NAME_SYSTEMS, NameSystem, key_name, note_name
from ..core.pitch import Pitch
from ..render.page import song_page
from ..sheets.parse import reads_differently
from ..store import Library

router = APIRouter(include_in_schema=False)

NAME_LABELS = {
    "russian": "до ре ми",
    "letters": "C D E",
    "both": "Both",
    "solfege": "do re mi",
    "german": "C D E (German)",
    "none": "Off",
}
TOGGLE_NAMES = ("russian", "letters", "both", "none")
MAJOR_TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MINOR_TONICS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


@cache
def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("soundselect.web", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["version"] = __version__
    return env


def _page(name: str, **context: object) -> HTMLResponse:
    return HTMLResponse(_env().get_template(name).render(**context))


def _lib(request: Request) -> Library:
    return request.app.state.library


def _names(lib: Library, names: str | None) -> NameSystem:
    if names in NAME_SYSTEMS:
        return names  # type: ignore[return-value]
    return lib.settings().names


def _notes(notes: list[str], names: NameSystem) -> str:
    shown = names if names not in ("none", "both") else "letters"
    return " ".join(note_name(Pitch.parse(n), shown) for n in notes)


def _key_options(names: NameSystem) -> list[tuple[str, str]]:
    shown = "letters" if names == "none" else names
    options = []
    for mode, tonics in (("major", MAJOR_TONICS), ("minor", MINOR_TONICS)):
        for tonic in tonics:
            key = Key.parse(f"{tonic} {mode}")
            options.append((f"{tonic} {mode}", key_name(key, shown)))
    return options


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    lib = _lib(request)
    settings = lib.settings()
    recent = service.list_songs(lib, limit=8)
    return _page(
        "home.html",
        settings=settings,
        instruments=list(INSTRUMENTS.values()),
        songs=_rows(recent.songs, settings.names),
        total=recent.total,
    )


def _rows(songs: list, names: NameSystem) -> list[dict]:
    shown = "letters" if names == "none" else names
    return [
        {
            "id": s.id,
            "title": s.title or "Untitled song",
            "artist": s.artist,
            "key": key_name(s.written_key.to_key(), shown) if s.written_key else None,
            "pentatonic": _notes(s.pentatonic, names),
            "warnings": s.warnings,
            "added": s.created_at.date().isoformat(),
        }
        for s in songs
    ]


@router.get("/library", response_class=HTMLResponse)
def library_page(
    request: Request,
    q: str | None = None,
    sort: Annotated[str, Query(pattern="^(recent|title)$")] = "recent",
) -> HTMLResponse:
    lib = _lib(request)
    settings = lib.settings()
    found = service.list_songs(lib, q, sort=sort, limit=500)
    return _page(
        "library.html",
        q=q or "",
        sort=sort,
        songs=_rows(found.songs, settings.names),
        total=found.total,
        instrument=get_instrument(settings.instrument).display_name,
    )


@router.get("/batches/{batch_id}", response_class=HTMLResponse)
def batch_page(request: Request, batch_id: str) -> HTMLResponse:
    lib = _lib(request)
    batch = lib.batch(batch_id)
    if batch is None:
        return _page("missing.html", what="import")
    # songs imported for another instrument open written for that instrument
    instrument = batch.options.instrument
    other = instrument is not None and instrument != lib.settings().instrument
    return _page("batch.html", batch=batch, song_query=f"?instrument={instrument}" if other else "")


@router.get("/songs/{song_id}", response_class=HTMLResponse, response_model=None)
def song_screen(
    request: Request,
    song_id: str,
    names: str | None = None,
    view: str = "written",
    instrument: str | None = None,
) -> HTMLResponse | RedirectResponse:
    lib = _lib(request)
    shown = _names(lib, names)
    try:
        song = service.get_song(lib, song_id, instrument=instrument)
    except service.NotFound:
        return _page("missing.html", what="song")
    except service.BadRequest:
        return RedirectResponse(f"/songs/{song_id}")
    written = view != "concert"

    def link(**change: str | None) -> str:
        params = {"names": names, "view": view if view == "concert" else None}
        params["instrument"] = instrument
        params.update(change)
        query = urlencode({k: v for k, v in params.items() if v})
        return f"/songs/{song_id}" + (f"?{query}" if query else "")

    export = {"names": shown, "view": "written" if written else "concert"}
    if instrument:
        export["instrument"] = instrument
    sheet_chords = []
    for line in song.lines():
        for pl in line.chords:
            if pl.text not in sheet_chords:
                sheet_chords.append(pl.text)
    bar = (
        _env()
        .get_template("songbar.html")
        .render(
            song=song,
            names=shown,
            written=written,
            name_links=[(n, NAME_LABELS[n], link(names=n)) for n in TOGGLE_NAMES],
            written_link=link(view=None),
            concert_link=link(view="concert"),
            instrument_name=song.view.name.split(" in ")[0] if song.view else "Instrument",
            pdf_link=f"/api/v1/songs/{song_id}/export?{urlencode({**export, 'format': 'pdf'})}",
            key_options=_key_options(shown),
            sheet_chords=sheet_chords,
            b_choice=song.corrections.b_is_flat is not None
            or any(reads_differently(c) for c in sheet_chords),
            corrections=song.corrections,
            fixes=song.corrections.model_dump(mode="json")["chords"],
        )
    )
    head = Markup(_env().get_template("songbar_head.html").render())
    return HTMLResponse(song_page(song, shown, written=written, head=head, before=Markup(bar)))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    lib = _lib(request)
    return _page(
        "settings.html",
        settings=lib.settings(),
        instruments=list(INSTRUMENTS.values()),
        name_systems=[(n, NAME_LABELS[n]) for n in NAME_SYSTEMS],
    )


def add_screens(app: FastAPI) -> None:
    app.include_router(router)
