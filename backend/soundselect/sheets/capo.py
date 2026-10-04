"""Capo and tuning: turning the guitar shapes a sheet shows into the chords that sound.

"Capo 2" means the written shapes sound two half steps higher, so the real chords move up before
anything else; "tuning: half step down" moves them down one. The interval is spelled so the real
key gets the simplest signature (capo 1 on G shapes gives A♭ major, not G♯ major).
"""

from __future__ import annotations

from ..core.chords import parse_chord
from ..core.keyfind import find_key
from ..core.keys import Key
from ..core.pitch import Interval
from ..core.song import Notice
from .model import ParsedSheet

VERSION = "1"


def _candidates(semitones: int) -> list[Interval]:
    center = round(semitones * 7 / 12)
    out = []
    for steps in (center - 1, center, center + 1):
        candidate = Interval(steps, semitones)
        name = candidate.name.lstrip("-")
        if name[:1] in ("P", "M", "m", "A", "d") and name[:2] not in ("AA", "dd"):
            out.append(candidate)
    return out


def capo_interval(semitones: int, shape_key: Key | None) -> Interval:
    """The interval for a shift in half steps, spelled for the simplest resulting key."""

    def plain(i: Interval) -> int:
        return 0 if i.name.lstrip("-")[0] in ("P", "M", "m") else 1

    candidates = _candidates(semitones)
    if shape_key is None:
        return min(candidates, key=plain)
    return min(candidates, key=lambda i: (abs(shape_key.transpose(i).fifths), plain(i)))


def apply_capo(sheet: ParsedSheet, capo: int | None = None) -> ParsedSheet:
    """Move every chord (and a key written on the sheet) from shapes to sounding chords.

    ``capo`` overrides the sheet's own capo note (a correction).
    """
    frets = sheet.meta.capo if capo is None else capo
    shift = frets + sheet.meta.tuning
    if shift == 0:
        return sheet
    shapes = [c for c in (parse_chord(p.symbol) for p in sheet.chords() if p.symbol) if c]
    finding = find_key(shapes)
    interval = capo_interval(shift, finding.key if finding else None)

    sheet = sheet.model_copy(deep=True)
    for section in sheet.sections:
        for line in section.lines:
            for k, pc in enumerate(line.chords):
                if pc.symbol:
                    moved = parse_chord(pc.symbol).transpose(interval)  # type: ignore[union-attr]
                    line.chords[k] = pc.model_copy(update={"symbol": moved.symbol})
    meta = sheet.meta.model_copy(update={"capo": frets})
    if meta.stated_key:
        try:
            stated = Key.parse(meta.stated_key).transpose(interval).normalized()
            meta = meta.model_copy(update={"stated_key": f"{stated.tonic} {stated.mode}"})
        except ValueError:
            meta = meta.model_copy(update={"stated_key": None})

    parts = []
    if frets:
        parts.append(f"capo on fret {frets}")
    if sheet.meta.tuning:
        parts.append(f"tuning {sheet.meta.tuning_text or sheet.meta.tuning}")
    direction = "higher" if shift > 0 else "lower"
    steps = abs(shift)
    message = (
        f"The sheet has {' and '.join(parts)}: its chords are guitar shapes that sound "
        f"{steps} half step{'s' if steps != 1 else ''} {direction}, so the real chords are used."
    )
    notices = [*sheet.notices, Notice(level="info", code="capo", message=message)]
    return sheet.model_copy(update={"meta": meta, "notices": notices})
