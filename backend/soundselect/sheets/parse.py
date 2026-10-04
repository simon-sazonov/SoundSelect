"""Parsing chords: pairing chord lines with their lyrics and reading every chord symbol.

H is B natural, as on Russian and German sheets; when a sheet uses H anywhere, its plain B means
B♭. Text in a chord line that is not a chord is kept, marked unreadable and reported, so it can
be checked (later, a photo's unreadable chord line gets a second read).
"""

from __future__ import annotations

from ..core.chords import parse_chord
from ..core.song import ChordFix, Notice, SourceRef
from .lines import clean_chord_text, repeat_count
from .model import ParsedChord, ParsedLine, ParsedSection, ParsedSheet, SortedSheet, Token

VERSION = "2"


def _chord(token: Token, uses_h: bool) -> ParsedChord | None:
    if token.kind == "chord":
        c = parse_chord(clean_chord_text(token.text), b_is_flat=uses_h)
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


def _chords(tokens: list[Token], uses_h: bool) -> list[ParsedChord]:
    return [c for t in tokens if (c := _chord(t, uses_h)) is not None]


def parse_sheet(sorted_sheet: SortedSheet, fixes: list[ChordFix] | None = None) -> ParsedSheet:
    uses_h = sorted_sheet.uses_h
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
                        chords=_chords(line.tokens, uses_h),
                        repeat=repeat,
                        index=line.index,
                        source=line.source,
                    )
                )
        elif line.kind == "chords":
            nxt = lines[i + 1] if i + 1 < len(lines) else None
            chords = _chords(line.tokens, uses_h)
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
                    chords=_chords(line.tokens, uses_h),
                    repeat=line.repeat,
                    index=line.index,
                    source=line.source,
                )
            )
        i += 1

    if not sections[0].lines:
        sections = sections[1:]
    sheet = ParsedSheet(sections=sections, meta=sorted_sheet.meta)
    if fixes:
        sheet = apply_chord_fixes(sheet, fixes, uses_h)
    return sheet.model_copy(update={"notices": _notices(sheet)})


def apply_chord_fixes(sheet: ParsedSheet, fixes: list[ChordFix], uses_h: bool) -> ParsedSheet:
    """Apply the player's chord corrections: one occurrence, or every occurrence of a chord."""
    sheet = sheet.model_copy(deep=True)
    all_lines = [line for s in sheet.sections for line in s.lines]
    for fix in fixes:
        replacement = None
        if fix.to.strip():
            c = parse_chord(fix.to, b_is_flat=uses_h)
            replacement = c.symbol if c else None
            if replacement is None:
                continue
        targets: list[tuple[ParsedLine, int]] = []
        if fix.line is not None and fix.index is not None:
            if 0 <= fix.line < len(all_lines) and 0 <= fix.index < len(all_lines[fix.line].chords):
                targets.append((all_lines[fix.line], fix.index))
        else:
            orig = parse_chord(fix.original, b_is_flat=uses_h)
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
