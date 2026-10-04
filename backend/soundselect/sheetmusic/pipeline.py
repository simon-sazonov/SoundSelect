"""The sheet music pipeline: get the views, join them into a clean copy, read the notes and
the words, build the score in concert pitch, assemble the Song, then the music core writes it
for the player's instrument.

Every step saves its output, so a correction (the key, a chord, the page's instrument) re-runs
only what comes after it, in about a second.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from ..core.song import ChordFix, Corrections, Song
from ..core.view import VERSION as VIEW_VERSION
from ..core.view import apply_instrument
from ..pipeline.runner import Cache, Pipeline, RunResult, Step, StepEvent
from ..settings import ViewSettings
from .files import FileStore
from .models import Clean, Meta, PageBox, PageText, Read, SourceKind, Views

if TYPE_CHECKING:
    from .stitch import Image, PageStaff

# OpenCV, homr, RapidOCR and music21 are imported inside the steps, so registering the
# pipeline costs nothing until a piece is read.

# Bump a step's version when what it makes changes; saved outputs are then made again.
VIEWS_VERSION = "1"
CLEAN_VERSION = "1"
NOTES_VERSION = "1"
TEXT_VERSION = "1"
FIX_VERSION = "1"
SCORE_VERSION = "1"
SONG_VERSION = "1"


@dataclass(frozen=True)
class Item:
    name: str | None
    sha: str | None = None  # stored input
    load: Callable[[], bytes] | None = None
    url: str | None = None


@dataclass(frozen=True)
class SheetMusicSource:
    """What one piece is read from: screenshots in viewing order, a video file, or a link."""

    kind: SourceKind
    items: tuple[Item, ...]
    files: FileStore = field(compare=False)

    def fingerprint(self) -> str:
        h = hashlib.sha256(f"sheet_music:{self.kind}".encode())
        for item in self.items:
            h.update(b"\0" + (item.sha or item.url or "").encode())
        return h.hexdigest()

    def cache_key(self) -> str:
        return self.fingerprint()

    @property
    def name(self) -> str | None:
        if self.kind == "link":
            return self.items[0].url
        names = [i.name for i in self.items if i.name]
        if not names:
            return None
        return names[0] if len(names) == 1 else f"{names[0]} (+{len(names) - 1})"


def get_views(source: SheetMusicSource, files: FileStore) -> Views:
    from . import stitch, video

    if source.kind == "screenshots":
        shas = []
        for item in source.items:
            assert item.load is not None
            data = item.load()
            stitch.decode_image(data)  # fails early for a picture OpenCV can't read
            shas.append(files.put(data))
        return Views(views=shas)
    title = None
    if source.kind == "video":
        item = source.items[0]
        assert item.load is not None
        suffix = PurePath(item.name or "video.mp4").suffix or ".mp4"
        frames = video.sample_bytes(item.load(), suffix)
    else:
        from ..links import download

        url = source.items[0].url
        assert url is not None
        with tempfile.TemporaryDirectory() as tmp:
            info = download(url, tmp, want="video")
            assert info.path is not None
            frames = video.sample(info.path)
        title = info.title
    views = video.views_of(frames)
    if not views:
        raise video.VideoError("The video never holds still long enough to read the music.")
    return Views(views=[files.put(stitch.encode_png(v)) for v in views], title=title)


def _images(views: Views, files: FileStore) -> list[Image]:
    from . import stitch

    return [stitch.decode_image(files.get(sha)) for sha in views.views]


def make_clean(views: Views, files: FileStore) -> Clean:
    from . import stitch

    lines = stitch.stitch(_images(views, files))
    if not lines:
        raise ValueError("No staves were found in these pictures.")
    lay = stitch.layout(lines)
    height, width = lay.pages[0].shape[:2]
    return Clean(
        pages=[files.put(stitch.encode_png(p)) for p in lay.pages],
        width=width,
        height=height,
        systems=[
            PageBox(page=s.page, box=(s.box.x0, s.box.y0, s.box.x1, s.box.y1)) for s in lay.systems
        ],
        staves=[
            {
                "page": s.page,
                "system": s.system,
                "box": [s.box.x0, s.box.y0, s.box.x1, s.box.y1],
                "grand": s.grand,
            }
            for s in lay.staves
        ],
        views=len(views.views),
    )


def page_staves(clean: Clean) -> list[PageStaff]:
    from . import stitch

    return [
        stitch.PageStaff(s["page"], s["system"], stitch.Box(*s["box"]), s["grand"])
        for s in clean.staves
    ]


def _gray(data: bytes) -> Image:
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("a clean-copy page can't be read")
    return img


def read_notes(clean: Clean, files: FileStore) -> list[str]:
    from . import omr

    staves = page_staves(clean)
    return [
        omr.read_page(_gray(files.get(sha)), [s for s in staves if s.page == i])
        for i, sha in enumerate(clean.pages)
    ]


def read_text(clean: Clean, views: Views, files: FileStore) -> PageText:
    from . import stitch, text

    pages = [_gray(files.get(sha)) for sha in clean.pages]
    chords, bars = text.read_chords(pages, page_staves(clean))
    title, composer, part = text.read_header(stitch.decode_image(files.get(views.views[0])))
    return PageText(title=title, composer=composer, part_name=part, chords=chords, systems=bars)


def fix_chords(page: PageText, fixes: list[ChordFix]) -> PageText:
    """The player's chord fixes: one chord (its line is the system, its index the order in
    it) or, without them, every chord read the same way."""
    if not fixes:
        return page
    marks = []
    per_system: dict[int, int] = {}
    for mark in page.chords:
        index = per_system.get(mark.system, 0)
        per_system[mark.system] = index + 1
        new = mark.text
        for fix in fixes:
            if fix.original != mark.text:
                continue
            if fix.line is not None and (fix.line != mark.system or fix.index != index):
                continue
            new = fix.to.strip()
        if new:
            marks.append(mark.model_copy(update={"text": new}))
    return page.model_copy(update={"chords": marks})


def build_score(notes: list[str], page: PageText, page_fix: str | None) -> Read:
    from . import score, text

    instrument = page_fix or text.part_instrument(page.part_name) or "concert"
    built = score.build(
        notes,
        page.chords,
        title=page.title,
        composer=page.composer,
        page_instrument=None if instrument == "concert" else instrument,
    )
    return Read(
        xml=built.xml,
        moved=built.moved.name if (built.moved.steps or built.moved.semitones) else "P1",
        measures=built.measures,
        chord_beats=built.chord_beats,
        page_instrument=instrument,
        part_name=page.part_name,
    )


def make_song(
    clean: Clean,
    page: PageText,
    read: Read,
    views: Views,
    corrections: Corrections,
    meta: Meta,
) -> Song:
    from . import build

    return build.build_song(
        clean,
        page,
        read,
        corrections,
        source=meta.source,
        source_name=meta.source_name,
        fingerprint=meta.fingerprint,
        fallback_title=views.title or meta.fallback_title,
    )


def _view(song: Song, view_settings: ViewSettings) -> Song:
    return apply_instrument(
        song,
        view_settings.instrument,
        comfortable_low=view_settings.comfortable_low,
        comfortable_high=view_settings.comfortable_high,
    )


SHEET_MUSIC = Pipeline(
    "sheet_music",
    [
        Step("views", VIEWS_VERSION, ("source", "files"), get_views, Views),
        Step("clean", CLEAN_VERSION, ("views", "files"), make_clean, Clean),
        Step("notes", NOTES_VERSION, ("clean", "files"), read_notes, list[str]),
        Step("text", TEXT_VERSION, ("clean", "views", "files"), read_text, PageText),
        Step("fix", FIX_VERSION, ("text", "chord_fixes"), fix_chords, PageText),
        Step("score", SCORE_VERSION, ("notes", "fix", "page_fix"), build_score, Read),
        Step(
            "song",
            SONG_VERSION,
            ("clean", "fix", "score", "views", "corrections", "meta"),
            make_song,
            Song,
        ),
        Step("view", VIEW_VERSION, ("song", "view_settings"), _view, Song),
    ],
)

LABELS = {
    "views": "Getting the screenshots",
    "clean": "Joining the screenshots into pages",
    "notes": "Reading the notes",
    "text": "Reading the chord names and title",
    "fix": "Applying your chord fixes",
    "score": "Putting the score together",
    "song": "Finding the key",
    "view": "Writing it for your instrument",
}


def run_sheet_music(
    source: SheetMusicSource,
    *,
    corrections: Corrections | None = None,
    view: ViewSettings | None = None,
    cache: Cache | None = None,
    on_step: StepEvent | None = None,
) -> RunResult:
    corrections = corrections or Corrections()
    first = source.items[0].name if source.items else None
    meta = Meta(
        source=source.kind,
        source_name=source.name,
        fingerprint=source.fingerprint(),
        fallback_title=PurePath(first).stem if first and source.kind != "link" else None,
    )
    inputs = {
        "source": source,
        "files": source.files,
        "chord_fixes": list[ChordFix](corrections.chords),
        "page_fix": corrections.page_instrument,
        "corrections": corrections,
        "meta": meta,
        "view_settings": view or ViewSettings(),
    }
    result = SHEET_MUSIC.run(inputs, cache=cache, on_step=on_step)
    clean: Clean = result["clean"]
    source.files.put_index(source.fingerprint(), clean.model_dump_json())
    return result


def analyze_sheet_music(
    source: SheetMusicSource,
    *,
    corrections: Corrections | None = None,
    view: ViewSettings | None = None,
    cache: Cache | None = None,
    on_step: StepEvent | None = None,
) -> Song:
    """Screenshots, a video or a link in, the finished Song out (written for the instrument)."""
    result = run_sheet_music(
        source, corrections=corrections, view=view, cache=cache, on_step=on_step
    )
    song: Song = result["view"]
    return song.model_copy(update={"versions": SHEET_MUSIC.versions})


def files_for(home: str | Path) -> FileStore:
    return FileStore(Path(home) / "sheetmusic")


def clean_copy(source: SheetMusicSource) -> Clean:
    """The piece's clean copy, made again from its inputs when it isn't saved."""
    saved = source.files.get_index(source.fingerprint())
    if saved is not None:
        clean = Clean.model_validate_json(saved)
        if all(source.files.has(sha) for sha in clean.pages):
            return clean
    clean = make_clean(get_views(source, source.files), source.files)
    source.files.put_index(source.fingerprint(), clean.model_dump_json())
    return clean


def clean_page(source: SheetMusicSource, index: int) -> bytes:
    """One page of the clean copy as PNG; IndexError past the last page."""
    clean = clean_copy(source)
    if not 0 <= index < len(clean.pages):
        raise IndexError(index)
    return source.files.get(clean.pages[index])


def clean_pdf(source: SheetMusicSource) -> bytes:
    from . import stitch

    clean = clean_copy(source)
    return stitch.clean_copy_pdf([_gray(source.files.get(sha)) for sha in clean.pages])
