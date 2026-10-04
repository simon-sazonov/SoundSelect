"""What the app does with songs, in one place for the API, the screens, the jobs and the command
line, so they all behave the same.

A stored song is the pipeline's result for the instrument it was made for. Showing it for
another instrument, or with note names, is worked out when it is asked for; the stored result
never changes for that. Corrections are saved apart from the result and re-run only the steps
they touch.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from pydantic import Field, ValidationError

from .core.chords import parse_chord
from .core.instruments import Transposition, get_instrument
from .core.keys import Key
from .core.names import NameSystem
from .core.scales import song_scales
from .core.song import ChordFix, Corrections, KeyName, Model, Song
from .core.view import apply_instrument, with_names
from .imports import (
    ImportOptions,
    InputRef,
    Unreadable,
    check_groups,
    file_kind,
    plan_jobs,
    text_name,
    unreadable_message,
)
from .pipeline.registry import get_pipeline
from .settings import ViewSettings
from .store import BatchInfo, Library, SongList, SongRecord, SongRow, SongSummary

MAX_TEXT = 200_000  # characters of pasted text
MAX_FILE = 25 * 1024 * 1024  # bytes per file
MAX_ITEMS = 100  # songs per import


class BadRequest(ValueError):
    """Something in the request can't be used; the message says what, for the player."""


class NotFound(LookupError):
    pass


class SongPatch(Model):
    """Corrections to save. Fields left out stay as they are; null clears one."""

    title: str | None = None
    artist: str | None = None
    key: str | None = Field(None, description="The right concert key: 'Bb', 'Gm', 'ля минор'.")
    capo: int | None = Field(None, ge=0, le=12)
    chords: list[ChordFix] | None = Field(
        None, description="The whole list of chord fixes (send the list with yours added)."
    )
    melody_octave: int | None = Field(None, ge=-3, le=3)

    def apply(self, current: Corrections) -> Corrections:
        data = current.model_dump()
        for name in self.model_fields_set:
            value = getattr(self, name)
            if name == "chords":
                value = [f.model_dump() for f in value or []]
            elif isinstance(value, str):
                value = value.strip() or None
            data[name] = value
        return Corrections.model_validate(data)


def check_key(text: str | None) -> None:
    if text is None:
        return
    try:
        Key.parse(text)
    except ValueError:
        raise BadRequest(f"Can't read {text!r} as a key. Try 'Bb', 'F#m' or 'ля минор'.") from None


def check_chord_fixes(fixes: list[ChordFix]) -> None:
    for fix in fixes:
        to = fix.to.strip()
        if to and parse_chord(to) is None and parse_chord(to, b_is_flat=True) is None:
            raise BadRequest(f"Can't read {fix.to!r} as a chord.")


def view_settings(lib: Library, instrument: str | None = None) -> ViewSettings:
    try:
        return lib.settings().view(instrument)
    except (ValueError, ValidationError) as exc:
        raise BadRequest(f"Unknown instrument {instrument!r}.") from exc


def _record(lib: Library, song_id: str) -> SongRecord:
    record = lib.song_record(song_id)
    if record is None:
        raise NotFound(f"No song with id {song_id!r}.")
    return record


def recompute(lib: Library, record: SongRecord, corrections: Corrections) -> Song:
    """Make the song again from its inputs; saved step outputs make it quick."""
    spec = get_pipeline(record.pipeline)
    song = spec.analyze(
        record.inputs,
        lib.read_input,
        corrections=corrections,
        view=view_settings(lib),
        cache=lib.cache,
    )
    try:
        return lib.save_song(song.model_copy(update={"id": record.id}))
    except KeyError:
        raise NotFound("That song is no longer in the library.") from None


def stored_song(lib: Library, song_id: str) -> Song:
    """The saved song; one saved by an older version is made again first."""
    record = _record(lib, song_id)
    if record.song is None:
        return recompute(lib, record, record.corrections)
    return record.song


def present(song: Song, view: ViewSettings, names: NameSystem | None = None) -> Song:
    """The song written for the asked instrument and range, with note names when asked."""
    inst = get_instrument(view.instrument)
    wanted = (
        inst.id,
        view.comfortable_low or str(inst.comfortable_low),
        view.comfortable_high or str(inst.comfortable_high),
    )
    current = song.view
    if current is None or (
        (current.instrument, current.comfortable_low, current.comfortable_high) != wanted
    ):
        song = apply_instrument(
            song,
            view.instrument,
            comfortable_low=view.comfortable_low,
            comfortable_high=view.comfortable_high,
        )
    if names is not None and names != "none":
        song = with_names(song, names)
    return song


def get_song(
    lib: Library,
    song_id: str,
    *,
    instrument: str | None = None,
    names: NameSystem | None = None,
) -> Song:
    return present(stored_song(lib, song_id), view_settings(lib, instrument), names)


def correct_song(
    lib: Library,
    song_id: str,
    patch: SongPatch,
    *,
    instrument: str | None = None,
    names: NameSystem | None = None,
) -> Song:
    """Save corrections and re-run the steps they touch. An empty patch refreshes the song
    with the current version of every step, keeping the corrections."""
    check_key(patch.key)
    check_chord_fixes(patch.chords or [])
    record = _record(lib, song_id)
    corrections = patch.apply(record.corrections)
    song = recompute(lib, record, corrections)
    return present(song, view_settings(lib, instrument), names)


def delete_song(lib: Library, song_id: str) -> None:
    if not lib.delete_song(song_id):
        raise NotFound(f"No song with id {song_id!r}.")


def page_image(lib: Library, song_id: str, index: int) -> Path:
    """A page of the song's source drawn as an image (made once, then kept)."""
    record = _record(lib, song_id)
    ref = next((r for r in record.inputs if r.kind == "pdf" and r.sha), None)
    if ref is None or ref.sha is None:
        raise NotFound("This song has no source pages to show.")
    path = lib.pages_dir / ref.sha / f"{index}.png"
    if not path.exists():
        from .sheets.readers.pdf import render_page

        try:
            png = render_page(lib.read_input(ref), index)
        except IndexError as exc:
            raise NotFound(f"The source has no page {index + 1}.") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{index}.{secrets.token_hex(4)}.tmp")
        tmp.write_bytes(png)
        tmp.replace(path)
    return path


def summarize(row: SongRow, instrument: str) -> SongSummary:
    inst = get_instrument(instrument)
    written_key: KeyName | None = None
    pentatonic: list[str] = []
    if row.key is not None:
        key = row.key.to_key()
        tr = Transposition.for_key(inst, key)
        if tr.written_key is not None:
            written_key = KeyName.of(tr.written_key)
        headline = song_scales(key)[0].scale.transpose(tr.interval)
        pentatonic = [str(n) for n in headline.notes]
    return SongSummary(
        id=row.id,
        title=row.title,
        artist=row.artist,
        source=row.source,
        source_name=row.source_name,
        key=row.key,
        written_key=written_key,
        instrument=inst.id,
        pentatonic=pentatonic,
        warnings=row.warnings,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def song_summary(lib: Library, song_id: str, *, instrument: str | None = None) -> SongSummary:
    row = lib.song_row(song_id)
    if row is None:
        raise NotFound(f"No song with id {song_id!r}.")
    return summarize(row, view_settings(lib, instrument).instrument)


def list_songs(
    lib: Library,
    query: str | None = None,
    *,
    sort: str = "recent",
    limit: int = 50,
    offset: int = 0,
    instrument: str | None = None,
) -> SongList:
    view = view_settings(lib, instrument)
    rows, total = lib.list_songs(query, sort=sort, limit=limit, offset=offset)
    return SongList(songs=[summarize(r, view.instrument) for r in rows], total=total)


def start_import(
    lib: Library,
    *,
    texts: list[str] | None = None,
    files: list[tuple[str | None, bytes]] | None = None,
    links: list[str] | None = None,
    options: ImportOptions | None = None,
) -> BatchInfo:
    """Store the inputs and make a batch with a job per song. Queueing the jobs is up to the
    caller, which knows how its jobs run."""
    texts = [t for t in texts or [] if t.strip()]
    files = files or []
    links = [link.strip() for link in links or [] if link.strip()]
    options = options or ImportOptions()
    if not (texts or files or links):
        raise BadRequest("Nothing to import: paste a chord sheet, or choose files or a link.")
    if len(texts) + len(files) + len(links) > MAX_ITEMS:
        raise BadRequest(f"That's more than {MAX_ITEMS} songs at once; import them in parts.")
    if options.instrument is not None:
        view_settings(lib, options.instrument)
    check_key(options.key)
    problem = check_groups(options.groups, len(files))
    if problem:
        raise BadRequest(f"The file groups don't fit: {problem}.")

    text_refs: list[InputRef] = []
    for text in texts:
        if len(text) > MAX_TEXT:
            raise BadRequest(f"A pasted text is longer than {MAX_TEXT:,} characters.")
        text_refs.append(lib.store_input(text.encode("utf-8"), "text"))
    named_texts = [(ref, text_name(text)) for ref, text in zip(text_refs, texts, strict=True)]

    file_refs: list[InputRef | Unreadable] = []
    for name, data in files:
        if len(data) > MAX_FILE:
            raise BadRequest(f"{name or 'A file'} is larger than {MAX_FILE // 2**20} MB.")
        kind = file_kind(name, data[:4096])
        if not data:
            file_refs.append(Unreadable(name or "File", "This file is empty."))
        elif kind is None:
            file_refs.append(Unreadable(name or "File", unreadable_message(name)))
        else:
            file_refs.append(lib.store_input(data, kind, name))

    link_refs = [InputRef(kind="link", url=link) for link in links]
    plans = plan_jobs([r for r, _ in named_texts], file_refs, link_refs, options.groups)
    for plan, (_, name) in zip(plans, named_texts, strict=False):
        plan.name = name  # pasted texts come first, named by their first line
    return lib.create_batch(plans, options)


def queued_jobs(batch: BatchInfo) -> list[str]:
    return [j.id for j in batch.jobs if j.status == "queued"]


__all__ = [
    "BadRequest",
    "NotFound",
    "SongPatch",
    "correct_song",
    "delete_song",
    "get_song",
    "list_songs",
    "page_image",
    "present",
    "queued_jobs",
    "song_summary",
    "start_import",
    "stored_song",
]
