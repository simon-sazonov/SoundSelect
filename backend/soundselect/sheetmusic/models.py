"""What the sheet music steps save. Kept free of heavy imports, so the pipeline can be
registered without loading OpenCV, homr or music21."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..core.song import Model

SourceKind = Literal["screenshots", "video", "link"]


class Views(Model):
    views: list[str] = Field(description="SHA-256 of each view picture in the file store.")
    title: str | None = Field(None, description="The video's title, for a link.")


class PageBox(Model):
    page: int
    box: tuple[float, float, float, float]


class Clean(Model):
    """The clean copy: the joined views laid out on A4 pages."""

    pages: list[str] = Field(description="SHA-256 of each page picture (PNG) in the file store.")
    width: int
    height: int
    systems: list[PageBox]
    staves: list[dict[str, Any]]  # page, system, box (x0, y0, x1, y1), grand
    views: int


class ChordMark(Model):
    text: str = Field(description="The chord name as read (♭ and ♯ written as b and #).")
    measure: int = Field(description="Bar number from 1, counted across the whole piece.")
    position: float = Field(description="Where in the bar it sits, 0 (start) to 1 (end).")
    system: int


class SystemBars(Model):
    first: int = Field(description="Number of the system's first bar.")
    count: int


class PageText(Model):
    title: str | None = None
    composer: str | None = None
    part_name: str | None = None
    chords: list[ChordMark] = Field(default_factory=list)
    systems: list[SystemBars] = Field(default_factory=list)


class Read(Model):
    """The piece as read: concert-pitch MusicXML and what it was moved by."""

    xml: str
    moved: str = Field(description="Interval from the page to concert pitch, e.g. '-M6'.")
    measures: int
    chord_beats: list[float | None]
    page_instrument: str = "concert"
    part_name: str | None


class Meta(Model):
    source: SourceKind
    source_name: str | None
    fingerprint: str
    fallback_title: str | None
