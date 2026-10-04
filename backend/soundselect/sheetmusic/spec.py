"""The sheet music pipeline as the app sees it: which inputs it reads, how it is named to the
player, and the hooks for its source pages, its engines and spotting staves in a picture."""

from __future__ import annotations

from pathlib import Path

from ..core.song import Corrections, Song
from ..imports import InputRef
from ..pipeline.registry import PipelineSpec, ReadInput
from ..settings import ViewSettings
from .files import FileStore
from .pipeline import (
    LABELS,
    SHEET_MUSIC,
    Item,
    SheetMusicSource,
    analyze_sheet_music,
    clean_page,
    files_for,
)


def _files(read: ReadInput) -> FileStore:
    """The file store in the library folder the inputs come from."""
    lib = getattr(read, "__self__", None)
    home = getattr(lib, "home", None)
    if home is None:
        from ..store.library import default_home

        home = default_home()
    return files_for(Path(home))


def source_of(inputs: list[InputRef], read: ReadInput) -> SheetMusicSource:
    if not inputs:
        raise ValueError("sheet music needs screenshots, a video or a link")
    files = _files(read)
    kinds = {r.kind for r in inputs}
    if kinds == {"link"}:
        if len(inputs) != 1:
            raise ValueError("a piece is read from one link")
        return SheetMusicSource("link", (Item(None, url=inputs[0].url),), files)
    if kinds == {"video"}:
        if len(inputs) != 1:
            raise ValueError("a piece is read from one video")
        ref = inputs[0]
        return SheetMusicSource("video", (Item(ref.name, ref.sha, lambda: read(ref)),), files)
    if kinds == {"photo"}:
        items = tuple(Item(r.name, r.sha, (lambda r=r: read(r))) for r in inputs)
        return SheetMusicSource("screenshots", items, files)
    raise ValueError("a piece is read from screenshots, one video or one link")


def make(
    source: SheetMusicSource,
    *,
    corrections: Corrections | None = None,
    view: ViewSettings | None = None,
    cache=None,
    on_step=None,
) -> Song:
    return analyze_sheet_music(
        source, corrections=corrections, view=view, cache=cache, on_step=on_step
    )


def pages(inputs: list[InputRef], read: ReadInput, index: int) -> bytes:
    return clean_page(source_of(inputs, read), index)


def available() -> bool:
    """Whether OpenCV, homr, RapidOCR and music21 are installed (homr fetches its models the
    first time it reads, so they don't need to be there yet)."""
    import importlib.util

    return all(
        importlib.util.find_spec(name) is not None
        for name in ("cv2", "numpy", "homr", "rapidocr", "music21")
    )


def claims(data: bytes) -> bool:
    """Whether a picture shows sheet music (five-line staves). Fast and never raises."""
    try:
        from .detect import has_staves

        return has_staves(data)
    except Exception:
        return False


def make_spec() -> PipelineSpec:

    return PipelineSpec(
        name="sheet_music",
        pipeline=SHEET_MUSIC,
        labels=LABELS,
        source=source_of,
        identity=lambda source: source.fingerprint(),
        make=make,
        pages=pages,
        available=available,
        claims=claims,
    )
