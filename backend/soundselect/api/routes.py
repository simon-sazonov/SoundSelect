"""The web API, version 1: every call the front end makes, under ``/api/v1``.

FastAPI publishes the exact description of these calls at ``/api/v1/openapi.json`` (a copy is
kept in ``docs/openapi.json``), so the screens are built against what the back end returns.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .. import __version__, service
from ..core.instruments import INSTRUMENTS
from ..core.names import NameSystem
from ..core.song import Model, Song
from ..imports import ImageMode, ImportOptions, LinkMode
from ..jobs import JobQueue
from ..pipeline.registry import ready
from ..render.pdf import pdf_available
from ..render.scores import song_score
from ..settings import Settings
from ..sheets.readers import READERS
from ..store import BatchInfo, JobInfo, Library, SongList
from .errors import ERRORS, ApiError, ErrorResponse

router = APIRouter()

PitchView = Literal["written", "concert"]
ScorePart = Literal["headline", "scales", "chord_scales", "chord_notes", "melody", "all", "chord"]
ExportFormat = Literal["pdf", "html", "musicxml", "json", "txt", "midi"]
MUSICXML = "application/vnd.recordare.musicxml+xml"
POLL_SECONDS = 0.25


def library(request: Request) -> Library:
    return request.app.state.library


def job_queue(request: Request) -> JobQueue:
    return request.app.state.queue


Lib = Annotated[Library, Depends(library)]
Queue = Annotated[JobQueue, Depends(job_queue)]
NamesParam = Annotated[
    NameSystem | None,
    Query(description="Note names to add (or show on the staff); your default when left out."),
]
InstrumentParam = Annotated[
    str | None, Query(description="Instrument to write for; your default when left out.")
]
ViewParam = Annotated[
    PitchView, Query(description="Notes as written for the instrument, or in concert pitch.")
]


def _names(lib: Library, names: NameSystem | None) -> NameSystem:
    return names if names is not None else lib.settings().names


def _with_page_urls(song: Song) -> Song:
    if not song.source_pages or song.id is None:
        return song
    pages = [
        p.model_copy(update={"image": f"/api/v1/songs/{song.id}/pages/{p.index}.png"})
        for p in song.source_pages
    ]
    return song.model_copy(update={"source_pages": pages})


def _attachment(title: str | None, suffix: str) -> str:
    stem = re.sub(r"[^\w\- ]+", "", title or "").strip() or "song"
    ascii_stem = stem.encode("ascii", "ignore").decode().strip() or "song"
    return (
        f'attachment; filename="{ascii_stem}.{suffix}"; '
        f"filename*=UTF-8''{quote(stem)}.{quote(suffix)}"
    )


# Imports, batches and jobs


@router.post(
    "/imports",
    status_code=202,
    response_model=BatchInfo,
    responses=ERRORS,
    summary="Start an import",
    tags=["imports"],
)
def create_import(
    lib: Lib,
    queue: Queue,
    text: Annotated[
        list[str] | None, Form(description="Pasted chord sheets; each one is a song.")
    ] = None,
    files: Annotated[
        list[UploadFile] | None,
        File(
            description="Files: text, PDF and photos of chord sheets; screenshots and videos "
            "of sheet music; audio files. Each is read once its phase is built."
        ),
    ] = None,
    link: Annotated[
        list[str] | None,
        Form(description="Links (YouTube and others): sheet music videos or songs; see link_mode."),
    ] = None,
    instrument: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form(description="For a single song.")] = None,
    artist: Annotated[str | None, Form(description="For a single song.")] = None,
    key: Annotated[str | None, Form(description="Concert key, for a single song.")] = None,
    capo: Annotated[int | None, Form(ge=0, le=12, description="For a single song.")] = None,
    groups: Annotated[
        str | None,
        Form(description="Files that make one song or piece together, as JSON: [[0, 1], [2]]."),
    ] = None,
    image_mode: Annotated[ImageMode, Form()] = "auto",
    link_mode: Annotated[LinkMode, Form()] = "auto",
) -> BatchInfo:
    """Start making songs: pasted text, files and links, one song each. Files can be grouped
    into one song or piece, and sheet music screenshots in no group make one piece. Returns at
    once with a batch holding a job per song; follow it with ``GET /batches/{id}`` or the event
    stream. Inputs that can't be read yet get a job that has already failed with the reason, so
    every item shows up in the batch."""
    try:
        parsed_groups = json.loads(groups) if groups else None
        options = ImportOptions(
            instrument=instrument or None,
            title=title or None,
            artist=artist or None,
            key=key or None,
            capo=capo,
            groups=parsed_groups,
            image_mode=image_mode,
            link_mode=link_mode,
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        raise service.BadRequest(f"The import options can't be used: {exc}") from None
    uploads = []
    for f in files or []:
        data = f.file.read(service.MAX_FILE + 1)
        if not f.filename and not data:
            continue  # a file field left empty
        uploads.append((f.filename or None, data))
    batch = service.start_import(lib, texts=text, files=uploads, links=link, options=options)
    queue.enqueue(service.queued_jobs(batch))
    return lib.batch(batch.id) or batch


@router.get("/batches/{batch_id}", response_model=BatchInfo, responses=ERRORS, tags=["imports"])
def get_batch(batch_id: str, lib: Lib) -> BatchInfo:
    """A batch's progress: each song's status and current step."""
    batch = lib.batch(batch_id)
    if batch is None:
        raise service.NotFound(f"No batch with id {batch_id!r}.")
    return batch


@router.get(
    "/batches/{batch_id}/events",
    response_class=EventSourceResponse,
    responses=ERRORS,
    tags=["imports"],
)
async def batch_events(
    batch_id: str, lib: Lib, batch: Annotated[BatchInfo, Depends(get_batch)]
) -> AsyncIterator[ServerSentEvent]:
    """Live progress of a whole batch over one connection: a ``job`` event (a Job) each time a
    job changes, a ``batch`` event (the Batch) when the counts change, and ``end`` once every
    job has finished."""
    seen: dict[str, int] = {}
    counts = None
    while True:
        for job in batch.jobs:
            if seen.get(job.id) != job.rev:
                seen[job.id] = job.rev
                yield ServerSentEvent(event="job", data=job)
        now_counts = (batch.done, batch.failed)
        if now_counts != counts:
            counts = now_counts
            yield ServerSentEvent(event="batch", data=batch)
        if batch.status == "done":
            yield ServerSentEvent(event="end", data={"status": "done"})
            return
        await asyncio.sleep(POLL_SECONDS)
        batch = await run_in_threadpool(lib.batch, batch_id)
        if batch is None:
            return


@router.get("/jobs/{job_id}", response_model=JobInfo, responses=ERRORS, tags=["imports"])
def get_job(job_id: str, lib: Lib) -> JobInfo:
    job = lib.job(job_id)
    if job is None:
        raise service.NotFound(f"No job with id {job_id!r}.")
    return job


@router.get(
    "/jobs/{job_id}/events",
    response_class=EventSourceResponse,
    responses=ERRORS,
    tags=["imports"],
)
async def job_events(
    job_id: str, lib: Lib, job: Annotated[JobInfo, Depends(get_job)]
) -> AsyncIterator[ServerSentEvent]:
    """Live progress of one job: a ``job`` event (a Job) on every change, then ``end``."""
    rev = None
    while True:
        if job.rev != rev:
            rev = job.rev
            yield ServerSentEvent(event="job", data=job)
        if job.finished:
            yield ServerSentEvent(event="end", data={"status": job.status})
            return
        await asyncio.sleep(POLL_SECONDS)
        job = await run_in_threadpool(lib.job, job_id)
        if job is None:
            return


@router.get(
    "/batches/{batch_id}/songbook",
    response_class=Response,
    responses={
        **ERRORS,
        200: {"content": {"application/pdf": {}, "text/html": {}}, "description": "Songbook"},
    },
    tags=["imports"],
)
def batch_songbook(
    batch_id: str,
    lib: Lib,
    format: Literal["pdf", "html"] = "pdf",
    names: NamesParam = None,
    view: ViewParam = "written",
    instrument: InstrumentParam = None,
) -> Response:
    """The batch's finished songs in one document, with a contents page; written for the
    instrument the batch was imported for, unless another is asked for."""
    from ..render.pdf import html_to_pdf
    from ..render.songbook import songbook_html

    batch = get_batch(batch_id, lib)
    view_settings = service.view_settings(lib, instrument or batch.options.instrument)
    songs = []
    for job in batch.jobs:
        if job.status == "done" and job.song_id:
            try:
                song = service.stored_song(lib, job.song_id)
            except service.NotFound:
                continue  # deleted since
            songs.append(service.present(song, view_settings))
    if not songs:
        raise service.NotFound("No songs in this batch are ready yet.")
    html = songbook_html(songs, _names(lib, names), written=view == "written")
    if format == "html":
        return Response(html, media_type="text/html")
    return Response(
        html_to_pdf(html),
        media_type="application/pdf",
        headers={"Content-Disposition": _attachment("Songbook", "pdf")},
    )


# Songs


@router.get("/songs", response_model=SongList, responses=ERRORS, tags=["songs"])
def list_songs(
    lib: Lib,
    q: Annotated[str | None, Query(description="Words to find in title, artist, lyrics.")] = None,
    sort: Literal["recent", "title"] = "recent",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    instrument: InstrumentParam = None,
) -> SongList:
    """The library: newest first, or by title; a search matches every word given."""
    return service.list_songs(lib, q, sort=sort, limit=limit, offset=offset, instrument=instrument)


@router.get("/songs/{song_id}", response_model=Song, responses=ERRORS, tags=["songs"])
def get_song(
    song_id: str, lib: Lib, instrument: InstrumentParam = None, names: NamesParam = None
) -> Song:
    """The full Song result, written for the instrument, with a table of note names."""
    song = service.get_song(lib, song_id, instrument=instrument, names=_names(lib, names))
    return _with_page_urls(song)


@router.patch("/songs/{song_id}", response_model=Song, responses=ERRORS, tags=["songs"])
def patch_song(
    song_id: str,
    patch: service.SongPatch,
    lib: Lib,
    instrument: InstrumentParam = None,
    names: NamesParam = None,
) -> Song:
    """Save corrections (the key, the capo, a chord, the title) and get the song back once the
    steps they touch have run again. Fields left out stay as they are; null clears one. An
    empty body makes the song again with the newest version of every step."""
    song = service.correct_song(
        lib, song_id, patch, instrument=instrument, names=_names(lib, names)
    )
    return _with_page_urls(song)


@router.delete("/songs/{song_id}", status_code=204, responses=ERRORS, tags=["songs"])
def delete_song(song_id: str, lib: Lib) -> Response:
    service.delete_song(lib, song_id)
    return Response(status_code=204)


@router.get(
    "/songs/{song_id}/score",
    response_class=Response,
    responses={
        **ERRORS,
        200: {"content": {MUSICXML: {}, "image/svg+xml": {}}, "description": "The staff"},
    },
    tags=["songs"],
)
def get_score(
    song_id: str,
    lib: Lib,
    part: ScorePart = "all",
    chord: Annotated[
        str | None, Query(description="For part=chord: the chord's concert symbol.")
    ] = None,
    names: NamesParam = None,
    view: ViewParam = "written",
    instrument: InstrumentParam = None,
    format: Literal["musicxml", "svg"] = "musicxml",
) -> Response:
    """One part of the song on the staff, as MusicXML (draw it with Verovio) or as SVG:
    the key's pentatonic, the whole-song scales, each chord's scale, each chord's notes, the
    melody, or one chord with its notes and scale."""
    from ..render.scores import chord_score

    song = service.get_song(lib, song_id, instrument=instrument)
    shown = _names(lib, names)
    if part == "chord":
        info = song.chord_info(chord or "")
        if info is None:
            raise service.NotFound(f"The song has no chord {chord!r}.")
        xml: str | None = chord_score(song, info, names=shown, view=view)
    else:
        xml = song_score(song, part, names=shown, view=view)
    if not xml:
        raise service.NotFound("The song has nothing to show for that part.")
    if format == "svg":
        from ..render.staff import draw, music_font_css

        svg = draw(xml)
        style = f"<style>{music_font_css()}</style>"
        svg = svg.replace(">", ">" + style, 1) if svg.startswith("<svg") else svg
        return Response(svg, media_type="image/svg+xml")
    return Response(xml, media_type=MUSICXML)


@router.get(
    "/songs/{song_id}/export",
    response_class=Response,
    responses={
        **ERRORS,
        200: {
            "content": {
                "application/pdf": {},
                "text/html": {},
                MUSICXML: {},
                "application/json": {},
                "text/plain": {},
            },
            "description": "The file",
        },
        501: {"model": ErrorResponse, "description": "MIDI comes in a later phase."},
    },
    tags=["songs"],
)
def export_song(
    song_id: str,
    lib: Lib,
    format: ExportFormat = "pdf",
    names: NamesParam = None,
    view: ViewParam = "written",
    instrument: InstrumentParam = None,
) -> Response:
    """Download the song: the song page as PDF or HTML, the staves as MusicXML (opens in
    MuseScore), the Song result as JSON, or a text summary."""
    shown = _names(lib, names)
    song = service.get_song(lib, song_id, instrument=instrument, names=shown)
    written = view == "written"
    title = song.identity.title
    if format == "midi":
        raise ApiError(501, "not_built", "MIDI export comes in a later build phase.")
    if format in ("pdf", "html"):
        from ..render.page import song_page

        html = song_page(song, shown, written=written)
        if format == "html":
            body, media = html.encode(), "text/html"
        else:
            from ..render.pdf import html_to_pdf

            body, media = html_to_pdf(html), "application/pdf"
    elif format == "musicxml":
        score = song_score(song, "all", names=shown, view=view)
        if not score:
            raise service.NotFound("This song has no chords or key to write as staves.")
        body, media = score.encode(), MUSICXML
    elif format == "json":
        body, media = song.model_dump_json(indent=2).encode(), "application/json"
    else:
        from ..render.text import song_text

        body, media = song_text(song, shown, written=written).encode(), "text/plain"
    suffix = {"musicxml": "musicxml", "txt": "txt"}.get(format, format)
    return Response(
        body, media_type=media, headers={"Content-Disposition": _attachment(title, suffix)}
    )


class PageImage(Model):
    index: int
    width: int | None
    height: int | None
    image: str = Field(description="Where to get the page image (PNG).")


class LineBox(Model):
    line: int = Field(description="Line number across the whole song, as in corrections.")
    page: int
    box: tuple[float, float, float, float] = Field(
        description="x0, y0, x1, y1 on the page image, in pixels."
    )


class SourcePages(Model):
    pages: list[PageImage]
    lines: list[LineBox]


@router.get("/songs/{song_id}/pages", response_model=SourcePages, responses=ERRORS, tags=["songs"])
def get_pages(song_id: str, lib: Lib) -> SourcePages:
    """The source's pages as images, and where each line of the song sits on them, to check
    the reading side by side. Pasted text has no pages."""
    song = service.stored_song(lib, song_id)
    pages = [
        PageImage(
            index=p.index,
            width=p.width,
            height=p.height,
            image=f"/api/v1/songs/{song_id}/pages/{p.index}.png",
        )
        for p in song.source_pages
    ]
    lines = [
        LineBox(line=n, page=line.source.page, box=line.source.box)
        for n, line in enumerate(song.lines())
        if line.source is not None and line.source.box is not None
    ]
    return SourcePages(pages=pages, lines=lines)


@router.get(
    "/songs/{song_id}/pages/{index}.png",
    response_class=FileResponse,
    responses={**ERRORS, 200: {"content": {"image/png": {}}, "description": "The page"}},
    tags=["songs"],
)
def get_page_image(song_id: str, index: int, lib: Lib) -> FileResponse:
    path = service.page_image(lib, song_id, index)
    return FileResponse(path, media_type="image/png")


# Search, settings, health


@router.get(
    "/search",
    responses={501: {"model": ErrorResponse, "description": "Not built yet."}},
    tags=["songs"],
)
def search(q: str) -> Response:
    """Find a song on YouTube by name (arrives with the song tool)."""
    raise ApiError(501, "not_built", "Searching YouTube by name comes with the song tool.")


@router.get("/settings", response_model=Settings, tags=["settings"])
def get_settings(lib: Lib) -> Settings:
    """Your defaults: instrument, note names, comfortable range, photo reader."""
    return lib.settings()


@router.put("/settings", response_model=Settings, tags=["settings"])
def put_settings(settings: Settings, lib: Lib) -> Settings:
    return lib.save_settings(settings)


class InstrumentInfo(Model):
    id: str
    name: str
    interval: str = Field(description="From concert to written pitch, e.g. 'M6'.")
    lowest: str
    highest: str
    comfortable_low: str
    comfortable_high: str


@router.get("/instruments", response_model=list[InstrumentInfo], tags=["settings"])
def instruments() -> list[InstrumentInfo]:
    """The instruments songs can be written for."""
    return [
        InstrumentInfo(
            id=i.id,
            name=i.display_name,
            interval=i.interval.name,
            lowest=str(i.lowest),
            highest=str(i.highest),
            comfortable_low=str(i.comfortable_low),
            comfortable_high=str(i.comfortable_high),
        )
        for i in INSTRUMENTS.values()
    ]


class Tools(Model):
    pdf_output: bool = Field(description="Song pages as PDF (needs the Pango library).")
    pdf_reading: bool
    photo_reading: bool
    sheet_music: bool
    audio: bool
    links: bool


class Health(Model):
    status: Literal["ok"] = "ok"
    version: str
    api: str = "v1"
    songs: int
    jobs_waiting: int = Field(description="Jobs queued or running.")
    workers: bool = Field(description="Whether jobs run in this app (or a worker of its own).")
    tools: Tools


@router.get("/health", response_model=Health, tags=["settings"])
def health(lib: Lib, queue: Queue) -> Health:
    """Whether the app is up, and which tools are installed."""
    sheet_music, audio = ready("sheet_music"), ready("song")
    return Health(
        version=__version__,
        songs=lib.count_songs(),
        jobs_waiting=len(lib.jobs_with_status("queued", "running")),
        workers=queue.running,
        tools=Tools(
            pdf_output=pdf_available(),
            pdf_reading=True,
            photo_reading="photo" in READERS,
            sheet_music=sheet_music,
            audio=audio,
            # the link downloader (soundselect.links) comes with the sheet music tool
            links=importlib.util.find_spec("yt_dlp") is not None
            and importlib.util.find_spec("soundselect.links") is not None
            and (sheet_music or audio),
        ),
    )
