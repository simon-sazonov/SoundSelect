"""Which pipeline makes a song from which inputs, with each step named for the player.

A job, a correction and a refresh all go through here, so a song is always remade by the same
pipeline that first made it. Sheet music (Phase 3) and songs from audio (Phase 4) register
theirs with ``register_pipeline``. ``route`` decides which pipeline reads each import item.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..core.song import Corrections, Song
from ..imports import NOT_YET, ImageMode, InputKind, InputRef, JobKind, LinkMode, needs_extras
from ..settings import ViewSettings
from ..sheets.readers import READERS, SheetInput, detect_kind, render_source_page
from ..sheets.readers.text import decode_text
from .chord_sheet import CHORD_SHEET, analyze_sheet
from .runner import Cache, Pipeline, StepEvent

ReadInput = Callable[[InputRef], bytes]


def _always() -> bool:
    return True


@dataclass(frozen=True)
class PipelineSpec:
    name: str
    pipeline: Pipeline
    labels: Mapping[str, str]
    source: Callable[[list[InputRef], ReadInput], Any]  # the pipeline's input, from stored inputs
    identity: Callable[[Any], str]  # what that input contains, as a fingerprint
    make: Callable[..., Song]  # the pipeline's input in, the finished Song out
    # PNG of the song's source page at that index (from 0); IndexError past the last page
    pages: Callable[[list[InputRef], ReadInput, int], bytes] | None = None
    available: Callable[[], bool] = _always  # whether the pipeline's engines are installed
    claims: Callable[[bytes], bool] | None = None  # image files: should this pipeline read it?

    def label(self, step: str) -> str:
        return self.labels.get(step, step)

    def fingerprint(self, inputs: list[InputRef], read: ReadInput) -> str:
        """The identity of what the inputs contain, to spot a song already in the library."""
        return self.identity(self.source(inputs, read))

    def analyze(
        self,
        inputs: list[InputRef],
        read: ReadInput,
        *,
        corrections: Corrections | None = None,
        view: ViewSettings | None = None,
        cache: Cache | None = None,
        on_step: StepEvent | None = None,
    ) -> Song:
        return self.make(
            self.source(inputs, read),
            corrections=corrections,
            view=view,
            cache=cache,
            on_step=on_step,
        )


def _sheet_source(inputs: list[InputRef], read: ReadInput) -> SheetInput:
    if len(inputs) != 1:
        raise ValueError("a chord sheet is read from one input")
    ref = inputs[0]
    data = read(ref)
    if ref.kind == "text" and ref.name is None:
        # pasted text, or a file sent without a name (which may be in cp1251)
        return SheetInput(decode_text(data), kind="text")
    return SheetInput(data, ref.name, kind=ref.kind)


def _sheet_pages(inputs: list[InputRef], read: ReadInput, index: int) -> bytes:
    return render_source_page([(ref.kind, read(ref)) for ref in inputs], index)


CHORD_SHEET_SPEC = PipelineSpec(
    name="chord_sheet",
    pipeline=CHORD_SHEET,
    labels={
        "read": "Reading the sheet",
        "sort": "Sorting the lines",
        "parse": "Reading the chords",
        "capo": "Applying the capo",
        "key": "Finding the key",
        "song": "Putting the song together",
        "view": "Writing it for your instrument",
    },
    source=_sheet_source,
    identity=lambda source: source.fingerprint(detect_kind(source)),
    make=analyze_sheet,
    pages=_sheet_pages,
)

PIPELINES: dict[str, PipelineSpec] = {CHORD_SHEET_SPEC.name: CHORD_SHEET_SPEC}


def register_pipeline(spec: PipelineSpec) -> PipelineSpec:
    if spec.name in PIPELINES:
        raise ValueError(f"a pipeline named {spec.name!r} is registered already")
    PIPELINES[spec.name] = spec
    return spec


def get_pipeline(name: str) -> PipelineSpec:
    try:
        return PIPELINES[name]
    except KeyError:
        raise ValueError(f"no pipeline named {name!r}") from None


def ready(name: str) -> bool:
    """Whether the pipeline is built and its engines are installed."""
    spec = PIPELINES.get(name)
    if spec is None:
        return False
    try:
        return bool(spec.available())
    except Exception:
        return False


def groupable() -> set[JobKind]:
    """Job kinds that can read several files as one song or piece."""
    kinds: set[JobKind] = set()
    if "group" in READERS:
        kinds.add("chord_sheet")
    if ready("sheet_music"):
        kinds.add("sheet_music")
    return kinds


def _claims(name: str, data: bytes | None) -> bool:
    spec = PIPELINES.get(name)
    if spec is None or spec.claims is None or data is None:
        return False
    try:
        return bool(spec.claims(data))
    except Exception:
        return False


def route(
    kind: InputKind,
    data: bytes | None = None,
    *,
    image_mode: ImageMode = "auto",
    link_mode: LinkMode = "auto",
) -> JobKind | None:
    """Which job reads an import item; None when nothing here can read it yet."""
    if kind in ("text", "pdf"):
        return "chord_sheet"
    if kind == "photo":
        if image_mode == "sheet_music":
            return "sheet_music" if ready("sheet_music") else None
        if image_mode == "auto" and ready("sheet_music") and _claims("sheet_music", data):
            return "sheet_music"
        return "chord_sheet" if "photo" in READERS else None
    if kind == "video":
        return "sheet_music" if ready("sheet_music") else None
    if kind == "audio":
        return "song" if ready("song") else None
    if kind == "link":
        if link_mode == "sound":
            return "song" if ready("song") else None
        if link_mode == "sheet_music":
            return "sheet_music" if ready("sheet_music") else None
        # Phase 4 decides "auto" by looking at the link, once both pipelines exist
        if ready("sheet_music"):
            return "sheet_music"
        return "song" if ready("song") else None
    return None


_WHAT = {"sheet_music": "Reading sheet music", "song": "Making songs from audio"}


def not_yet_message(
    ref: InputRef, *, image_mode: ImageMode = "auto", link_mode: LinkMode = "auto"
) -> str:
    """Why nothing reads this item yet: a later build phase, or tools to install."""
    wanted: str | None = None
    if (ref.kind == "photo" and image_mode == "sheet_music") or ref.kind == "video":
        wanted = "sheet_music"
    elif ref.kind == "audio":
        wanted = "song"
    elif ref.kind == "link":
        wanted = {"sound": "song", "sheet_music": "sheet_music"}.get(link_mode)
        if wanted is None:
            wanted = next((n for n in ("sheet_music", "song") if n in PIPELINES), None)
    if wanted is not None and wanted in PIPELINES and not ready(wanted):
        return needs_extras(_WHAT[wanted])
    if ref.kind == "photo" and image_mode == "sheet_music":
        return NOT_YET["sheet_music"]
    return NOT_YET[ref.kind]


from .. import audio, sheetmusic  # noqa: E402,F401  (each registers its pipeline once it is built)
