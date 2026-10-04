"""The chord sheet pipeline: read, sort lines, parse chords, apply capo, find the key, assemble
the Song, then the music core writes it for the player's instrument."""

from __future__ import annotations

import os

from ..core.song import ChordFix, Corrections, KeyResult, Song
from ..core.view import VERSION as VIEW_VERSION
from ..core.view import apply_instrument
from ..settings import ViewSettings
from ..sheets import analyze, capo, lines, parse
from ..sheets.model import ParsedSheet, SheetText, SortedSheet
from ..sheets.readers import SheetInput, read_sheet
from .runner import Cache, Pipeline, RunResult, Step, StepEvent

READ_VERSION = "1"


def _view(song: Song, view_settings: ViewSettings) -> Song:
    return apply_instrument(
        song,
        view_settings.instrument,
        comfortable_low=view_settings.comfortable_low,
        comfortable_high=view_settings.comfortable_high,
    )


CHORD_SHEET = Pipeline(
    "chord_sheet",
    [
        Step("read", READ_VERSION, ("source",), read_sheet, SheetText),
        Step("sort", lines.VERSION, ("read",), lines.sort_lines, SortedSheet),
        Step("parse", parse.VERSION, ("sort", "chord_fixes"), parse.parse_sheet, ParsedSheet),
        Step("capo", capo.VERSION, ("parse", "capo_fix"), capo.apply_capo, ParsedSheet),
        Step("key", analyze.KEY_VERSION, ("capo", "key_fix"), analyze.sheet_key, KeyResult | None),
        Step(
            "song",
            analyze.SONG_VERSION,
            ("read", "capo", "key", "corrections"),
            analyze.build_song,
            Song,
        ),
        Step("view", VIEW_VERSION, ("song", "view_settings"), _view, Song),
    ],
)


def run_chord_sheet(
    source: SheetInput,
    *,
    corrections: Corrections | None = None,
    view: ViewSettings | None = None,
    cache: Cache | None = None,
    on_step: StepEvent | None = None,
) -> RunResult:
    corrections = corrections or Corrections()
    inputs = {
        "source": source,
        "chord_fixes": list[ChordFix](corrections.chords),
        "capo_fix": corrections.capo,
        "key_fix": corrections.key,
        "corrections": corrections,
        "view_settings": view or ViewSettings(),
    }
    return CHORD_SHEET.run(inputs, cache=cache, on_step=on_step)


def analyze_sheet(
    source: SheetInput | str | os.PathLike[str],
    *,
    corrections: Corrections | None = None,
    view: ViewSettings | None = None,
    cache: Cache | None = None,
    on_step: StepEvent | None = None,
) -> Song:
    """A chord sheet in, the finished Song out (written for the player's instrument).

    ``source`` is a sheet input, pasted text, or a file path.
    """
    if isinstance(source, os.PathLike):
        source = SheetInput.from_path(source)
    elif isinstance(source, str):
        source = SheetInput(source)
    result = run_chord_sheet(
        source, corrections=corrections, view=view, cache=cache, on_step=on_step
    )
    song: Song = result["view"]
    return song.model_copy(update={"versions": CHORD_SHEET.versions})
