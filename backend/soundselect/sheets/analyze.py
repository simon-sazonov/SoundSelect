"""Finding a chord sheet's key and assembling its Song result (in concert pitch)."""

from __future__ import annotations

from collections import Counter
from pathlib import PurePath

from ..core.chords import Chord, parse_chord
from ..core.keyfind import find_key
from ..core.keys import Key
from ..core.song import (
    ChordInfo,
    ChordPlacement,
    Corrections,
    Identity,
    KeyCandidate,
    KeyName,
    KeyResult,
    Line,
    Notice,
    Section,
    Song,
    Timing,
)
from ..core.view import chord_spelling
from .model import ParsedSheet, SheetText

KEY_VERSION = "1"
SONG_VERSION = "2"
UNCLEAR_KEY = 0.6


def sheet_key(sheet: ParsedSheet, corrected: str | None = None) -> KeyResult | None:
    """The key in concert pitch: the player's correction, or the best guess from the chords."""
    if corrected:
        k = Key.parse(corrected).normalized()
        return KeyResult(
            concert=KeyName.of(k), confidence=1.0, signature_confidence=1.0, basis="correction"
        )
    chords = [c for c in (parse_chord(p.symbol) for p in sheet.chords() if p.symbol) if c]
    stated = None
    if sheet.meta.stated_key:
        try:
            stated = Key.parse(sheet.meta.stated_key)
        except ValueError:
            stated = None
    finding = find_key(chords, stated=stated)
    if finding is None:
        return None
    best = finding.key.normalized()
    basis = (
        "stated"
        if stated and stated.tonic.pc == best.tonic.pc and stated.mode == best.mode
        else "chords"
    )
    return KeyResult(
        concert=KeyName.of(best),
        confidence=round(finding.confidence, 3),
        signature_confidence=round(min(1.0, finding.signature_confidence), 3),
        runners_up=[
            KeyCandidate(key=KeyName.of(g.key.normalized()), probability=round(g.probability, 3))
            for g in finding.ranked[1:4]
        ],
        basis=basis,
    )


def _key_notices(key: KeyResult | None) -> list[Notice]:
    if key is None or key.basis == "correction":
        return []
    k = key.concert.to_key()
    if key.signature_confidence < UNCLEAR_KEY:
        other = key.runners_up[0].key.to_key().display() if key.runners_up else "another key"
        return [
            Notice(
                level="warning",
                code="key_unclear",
                message=f"The key is unclear: {k.display()} or {other}? "
                "Check it and correct it if needed.",
            )
        ]
    if key.confidence < UNCLEAR_KEY:
        rel = k.relative.display()
        return [
            Notice(
                level="info",
                code="mode_unclear",
                message=f"{k.display()} or {rel}: the chords fit both. They share the same "
                "pentatonic notes, so the scales hold either way.",
            )
        ]
    return []


def build_song(
    text: SheetText,
    sheet: ParsedSheet,
    key: KeyResult | None,
    corrections: Corrections | None = None,
    versions: dict[str, str] | None = None,
) -> Song:
    """Assemble the concert-pitch Song: identity, form, chords (spelled to fit the key), notes."""
    corrections = corrections or Corrections()
    key_obj = key.concert.to_key() if key else None

    spelled: dict[str, Chord] = {}
    counts: Counter[str] = Counter()
    order: list[str] = []

    def spell(symbol: str) -> str:
        if symbol not in spelled:
            c = parse_chord(symbol)
            assert c is not None
            spelled[symbol] = c.respell(key_obj) if key_obj else c
        return spelled[symbol].symbol

    form = []
    for section in sheet.sections:
        lines = []
        for line in section.lines:
            placements = []
            for pc in line.chords:
                symbol = spell(pc.symbol) if pc.symbol else None
                if symbol:
                    if symbol not in counts:
                        order.append(symbol)
                    counts[symbol] += 1
                placements.append(
                    ChordPlacement(chord=symbol, text=pc.text, pos=pc.pos, readable=pc.readable)
                )
            lines.append(
                Line(lyrics=line.lyrics, chords=placements, repeat=line.repeat, source=line.source)
            )
        form.append(
            Section(kind=section.kind, label=section.label, repeat=section.repeat, lines=lines)
        )

    chords = []
    by_symbol = {c.symbol: c for c in spelled.values()}
    for symbol in order:
        c = by_symbol[symbol]
        chords.append(
            ChordInfo(
                symbol=symbol, family=c.family, count=counts[symbol], concert=chord_spelling(c)
            )
        )

    fallback_title = PurePath(text.source_name).stem if text.source_name else None
    identity = Identity(
        title=corrections.title or sheet.meta.title or fallback_title,
        artist=corrections.artist or sheet.meta.artist,
        source=text.source,
        source_name=text.source_name,
        fingerprint=text.fingerprint,
    )
    timing = None
    if sheet.meta.tempo or sheet.meta.time_signature:
        timing = Timing(tempo=sheet.meta.tempo, time_signature=sheet.meta.time_signature)
    return Song(
        identity=identity,
        key=key,
        form=form,
        chords=chords,
        timing=timing,
        corrections=corrections,
        notes=[*text.notices, *sheet.notices, *_key_notices(key)],
        source_pages=text.pages,
        versions=dict(versions or {}),
    )
