"""What the chord sheet steps hand to each other. Each is saved by the step runner."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..core.song import Model, Notice, SectionKind, SourceKind, SourcePage, SourceRef


class TextLine(Model):
    text: str
    source: SourceRef | None = None


class SheetText(Model):
    """Step 1 (read): the sheet as lines of text, with where each line sits on a page."""

    lines: list[TextLine]
    source: SourceKind
    source_name: str | None = None
    fingerprint: str
    pages: list[SourcePage] = Field(default_factory=list)
    notices: list[Notice] = Field(default_factory=list, description="What the reader skipped.")


TokenKind = Literal["chord", "nc", "repeat", "bar", "other"]
LineKind = Literal["blank", "header", "meta", "section", "chords", "lyrics", "tab", "diagram"]


class Token(Model):
    text: str
    pos: int
    kind: TokenKind


class SortedLine(Model):
    kind: LineKind
    text: str
    index: int = Field(description="Line number in the source text, from 0.")
    tokens: list[Token] = Field(default_factory=list)
    lyrics: str | None = None
    section: SectionKind | None = None
    label: str | None = None
    repeat: int | None = None
    source: SourceRef | None = None


class SheetMeta(Model):
    title: str | None = None
    artist: str | None = None
    capo: int = 0
    tuning: int = Field(0, description="Half steps the tuning sounds above standard (-1: Eb).")
    tuning_text: str | None = None
    stated_key: str | None = None
    tempo: float | None = None
    time_signature: str | None = None


class SortedSheet(Model):
    """Step 2 (sort): every line marked as header, meta, section label, chords, lyrics or tab."""

    lines: list[SortedLine]
    meta: SheetMeta
    uses_h: bool = Field(False, description="The sheet writes B natural as H, so B means B♭.")


class ParsedChord(Model):
    text: str
    symbol: str | None = Field(description="Canonical symbol; None for N.C. or unreadable text.")
    pos: int
    readable: bool = True


class ParsedLine(Model):
    lyrics: str = ""
    chords: list[ParsedChord] = Field(default_factory=list)
    repeat: int | None = None
    source: SourceRef | None = None
    index: int = Field(description="Line number in the source text.")


class ParsedSection(Model):
    kind: SectionKind = "other"
    label: str | None = None
    repeat: int | None = None
    lines: list[ParsedLine] = Field(default_factory=list)


class ParsedSheet(Model):
    """Steps 3 and 4 (parse chords, apply capo): sections of lines with chord symbols."""

    sections: list[ParsedSection]
    meta: SheetMeta
    notices: list[Notice] = Field(default_factory=list)

    def chords(self) -> list[ParsedChord]:
        return [c for s in self.sections for line in s.lines for c in line.chords]
