"""Which pipeline makes a song from which inputs, with each step named for the player.

A job, a correction and a refresh all go through here, so a song is always remade by the same
pipeline that first made it. Sheet music (Phase 3) and songs from audio (Phase 4) add theirs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..core.song import Corrections, Song
from ..imports import InputRef
from ..settings import ViewSettings
from ..sheets.readers import SheetInput, detect_kind
from ..sheets.readers.photo import group_input
from ..sheets.readers.text import decode_text
from .chord_sheet import CHORD_SHEET, analyze_sheet
from .runner import Cache, Pipeline, StepEvent

ReadInput = Callable[[InputRef], bytes]


@dataclass(frozen=True)
class PipelineSpec:
    name: str
    pipeline: Pipeline
    labels: Mapping[str, str]
    source: Callable[[list[InputRef], ReadInput], Any]  # the pipeline's input, from stored inputs
    identity: Callable[[Any], str]  # what that input contains, as a fingerprint
    make: Callable[..., Song]  # the pipeline's input in, the finished Song out

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
    if not inputs:
        raise ValueError("a chord sheet is read from at least one input")
    if len(inputs) > 1:  # a group: files that make one song together
        return group_input([_one_source(ref, read) for ref in inputs])
    return _one_source(inputs[0], read)


def _one_source(ref: InputRef, read: ReadInput) -> SheetInput:
    data = read(ref)
    if ref.kind == "text" and ref.name is None:
        # pasted text, or a file sent without a name (which may be in cp1251)
        return SheetInput(decode_text(data), kind="text")
    return SheetInput(data, ref.name, kind=ref.kind)


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
)

PIPELINES: dict[str, PipelineSpec] = {CHORD_SHEET_SPEC.name: CHORD_SHEET_SPEC}


def get_pipeline(name: str) -> PipelineSpec:
    try:
        return PIPELINES[name]
    except KeyError:
        raise ValueError(f"no pipeline named {name!r}") from None
