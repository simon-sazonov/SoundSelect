"""Parsing chords: pairing chord lines with their lyrics and reading every chord symbol.

H is B natural, as on Russian and German sheets; when a sheet uses H anywhere, its plain B means
B♭. A Russian sheet without H may still mean B♭ by B: when its chords fit that reading clearly
better, B is read as B♭ and a notice says so. English sheets, and sheets that write B♭ or A♯
themselves, keep B as B natural. A correction can set the reading either way.

Text in a chord line that is not a chord is kept, marked unreadable and reported, so it can be
checked (later, a photo's unreadable chord line gets a second read).
"""

from __future__ import annotations

import re

from ..core.chords import parse_chord
from ..core.keyfind import find_key
from ..core.keys import Key
from ..core.pitch import Pitch
from ..core.song import ChordFix, Notice, SourceRef
from .lines import clean_chord_text, repeat_count
from .model import (
    ParsedChord,
    ParsedLine,
    ParsedSection,
    ParsedSheet,
    SheetMeta,
    SortedSheet,
    Token,
)

VERSION = "3"

B_FLAT_GAIN = 0.5  # key-fit gain per chord that B♭ needs before a sheet's B is read as B♭
_EXPLICIT_B_FLAT_RE = re.compile(r"(?:^|/)(?:[BВ][b♭]|A[#♯])")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
B_FLAT_GUESS = Notice(
    level="info",
    code="b_flat_guess",
    message="This sheet's B is read as B♭ (си-бемоль), the Russian way: its chords fit that much "
    "better than B (си). If that's wrong, set “B on the sheet” to B (си) under Fix.",
)


def reads_differently(text: str) -> bool:
    """Whether a chord means something else when a plain B is B♭ (B as root or bass)."""
    core = clean_chord_text(text)
    plain, flat = parse_chord(core), parse_chord(core, b_is_flat=True)
    return plain is not None and flat is not None and plain.symbol != flat.symbol


def _key_fit(texts: list[str], b_is_flat: bool) -> float:
    chords = [c for c in (parse_chord(t, b_is_flat=b_is_flat) for t in texts) if c]
    finding = find_key(chords)
    return finding.best.score if finding else 0.0


def b_reading(sorted_sheet: SortedSheet, corrected: bool | None = None) -> tuple[bool, bool]:
    """What a plain B on the sheet means: (B means B♭, guessed from the chords)."""
    if corrected is not None:
        return corrected, False
    if sorted_sheet.uses_h:
        return True, False
    lines = sorted_sheet.lines
    texts = [
        clean_chord_text(t.text)
        for line in lines
        if line.kind in ("chords", "section", "lyrics")
        for t in line.tokens
        if t.kind == "chord"
    ]
    differing = [t for t in texts if reads_differently(t)]
    if not differing or any(_EXPLICIT_B_FLAT_RE.search(t) for t in texts):
        return False, False  # no B to read, or the sheet spells B♭ itself
    words = (line.text for line in lines if line.kind in ("lyrics", "header", "meta", "section"))
    if not any(_CYRILLIC_RE.search(w) for w in words):
        return False, False  # English sheets mean B natural
    gain = (_key_fit(texts, True) - _key_fit(texts, False)) / len(differing)
    guess = gain >= B_FLAT_GAIN
    return guess, guess


def _flat_stated_key(meta: SheetMeta) -> SheetMeta:
    """A stated key written with a Latin B, on a sheet whose B means B♭."""
    stated = meta.stated_key
    if not stated or stated.strip()[:1] not in ("B", "b"):
        return meta
    try:
        key = Key.parse(stated)
    except ValueError:
        return meta
    if key.tonic.letter != "B" or key.tonic.alter != 0:
        return meta
    flat = Key(Pitch("B", -1), key.mode)
    return meta.model_copy(update={"stated_key": f"{flat.tonic} {flat.mode}"})


def _chord(token: Token, b_is_flat: bool) -> ParsedChord | None:
    if token.kind == "chord":
        c = parse_chord(clean_chord_text(token.text), b_is_flat=b_is_flat)
        if c is not None:
            return ParsedChord(text=token.text, symbol=c.symbol, pos=token.pos)
        return ParsedChord(text=token.text, symbol=None, pos=token.pos, readable=False)
    if token.kind == "nc":
        return ParsedChord(text=token.text, symbol=None, pos=token.pos)
    if token.kind == "other":
        return ParsedChord(text=token.text, symbol=None, pos=token.pos, readable=False)
    return None  # bar lines and repeat marks


def _union(a: SourceRef | None, b: SourceRef | None) -> SourceRef | None:
    """Where a chord line and its lyrics sit together on the page."""
    if a is None or b is None or a.page != b.page or a.box is None or b.box is None:
        return a or b
    box = (min(a.box[0], b.box[0]), min(a.box[1], b.box[1]))
    box += (max(a.box[2], b.box[2]), max(a.box[3], b.box[3]))
    return SourceRef(page=a.page, box=box)


def _chords(tokens: list[Token], b_is_flat: bool) -> list[ParsedChord]:
    return [c for t in tokens if (c := _chord(t, b_is_flat)) is not None]


def parse_sheet(
    sorted_sheet: SortedSheet,
    fixes: list[ChordFix] | None = None,
    b_fix: bool | None = None,
) -> ParsedSheet:
    """``b_fix`` is the player's word on what a plain B means (None: read it from the sheet)."""
    b_is_flat, guessed = b_reading(sorted_sheet, b_fix)
    sections: list[ParsedSection] = [ParsedSection()]
    lines = sorted_sheet.lines
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.kind == "section":
            sections.append(
                ParsedSection(kind=line.section or "other", label=line.label, repeat=line.repeat)
            )
            if line.tokens:  # chords on the label line itself: "Intro: C G x2"
                repeat = next(
                    (repeat_count(t.text) for t in line.tokens if t.kind == "repeat"), None
                )
                sections[-1].lines.append(
                    ParsedLine(
                        chords=_chords(line.tokens, b_is_flat),
                        repeat=repeat,
                        index=line.index,
                        source=line.source,
                    )
                )
        elif line.kind == "chords":
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            chords = _chords(line.tokens, b_is_flat)
            if nxt is not None and nxt.kind == "lyrics" and not nxt.tokens:
                sections[-1].lines.append(
                    ParsedLine(
                        lyrics=nxt.lyrics or "",
                        chords=chords,
                        repeat=nxt.repeat or line.repeat,
                        index=line.index,
                        source=_union(line.source, nxt.source),
                    )
                )
                i += 1
            else:
                sections[-1].lines.append(
                    ParsedLine(
                        chords=chords, repeat=line.repeat, index=line.index, source=line.source
                    )
                )
        elif line.kind == "lyrics":
            sections[-1].lines.append(
                ParsedLine(
                    lyrics=line.lyrics or "",
                    chords=_chords(line.tokens, b_is_flat),
                    repeat=line.repeat,
                    index=line.index,
                    source=line.source,
                )
            )
        i += 1

    if not sections[0].lines:
        sections = sections[1:]
    meta = _flat_stated_key(sorted_sheet.meta) if b_is_flat else sorted_sheet.meta
    sheet = ParsedSheet(sections=sections, meta=meta)
    if fixes:
        sheet = apply_chord_fixes(sheet, fixes, b_is_flat)
    notices = ([B_FLAT_GUESS] if guessed else []) + _notices(sheet)
    return sheet.model_copy(update={"notices": notices})


def apply_chord_fixes(sheet: ParsedSheet, fixes: list[ChordFix], b_is_flat: bool) -> ParsedSheet:
    """Apply the player's chord corrections: one occurrence, or every occurrence of a chord."""
    sheet = sheet.model_copy(deep=True)
    all_lines = [line for s in sheet.sections for line in s.lines]
    for fix in fixes:
        replacement = None
        if fix.to.strip():
            c = parse_chord(fix.to, b_is_flat=b_is_flat)
            replacement = c.symbol if c else None
            if replacement is None:
                continue
        targets: list[tuple[ParsedLine, int]] = []
        if fix.line is not None and fix.index is not None:
            if 0 <= fix.line < len(all_lines) and 0 <= fix.index < len(all_lines[fix.line].chords):
                targets.append((all_lines[fix.line], fix.index))
        else:
            orig = parse_chord(fix.original, b_is_flat=b_is_flat)
            for line in all_lines:
                for k, pc in enumerate(line.chords):
                    if pc.text == fix.original or (orig and pc.symbol == orig.symbol):
                        targets.append((line, k))
        for line, k in sorted(targets, key=lambda t: -t[1]):
            if replacement is None:
                del line.chords[k]
            else:
                line.chords[k] = line.chords[k].model_copy(
                    update={"symbol": replacement, "readable": True}
                )
    return sheet


def _notices(sheet: ParsedSheet) -> list[Notice]:
    notices = []
    n = 0
    for section in sheet.sections:
        for line in section.lines:
            bad = [c.text for c in line.chords if not c.readable]
            if bad:
                words = ", ".join(f"'{b}'" for b in bad)
                notices.append(
                    Notice(
                        level="warning",
                        code="unreadable_chord",
                        line=n,
                        message=f"Line {n + 1}: couldn't read {words} as a chord.",
                    )
                )
            n += 1
    if not any(c.symbol for c in sheet.chords()):
        notices.append(Notice(level="warning", code="no_chords", message="No chords were found."))
    return notices
