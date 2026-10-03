"""The chord chart: chords over the lyrics, in columns, the way chord sheets are written.

Each chord keeps its column above its syllable. When a rewritten chord is longer than the
original (F/A becomes D/F#) and would touch the next one, the next chord moves right and the
lyrics get a matching space, so every chord still sits over its syllable. Long lines wrap at a
space with their chords.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core.song import ChordPlacement, Line, Section, Song

SECTION_TITLES = {
    "intro": "Intro",
    "verse": "Verse",
    "pre_chorus": "Pre-chorus",
    "chorus": "Chorus",
    "bridge": "Bridge",
    "solo": "Solo",
    "instrumental": "Instrumental",
    "interlude": "Interlude",
    "outro": "Outro",
    "coda": "Coda",
}


def section_title(section: Section) -> str | None:
    """The section's label as written, or a plain name for its kind ({start_of_chorus})."""
    return section.label or SECTION_TITLES.get(section.kind)


@dataclass
class ChordMark:
    col: int
    label: str
    readable: bool = True


@dataclass
class ChartRow:
    chords: list[ChordMark]
    lyrics: str

    def chord_text(self) -> str:
        out = ""
        for mark in self.chords:
            out = out.ljust(mark.col) + mark.label
        return out

    @property
    def width(self) -> int:
        return max(len(self.chord_text()), len(self.lyrics))


def chord_label(
    pl: ChordPlacement, written: bool = True, label: Callable[[str], str] | None = None
) -> str:
    """What to print for one chord: the instrument's (or concert) symbol, or the source text."""
    symbol = pl.written if written and pl.written else pl.chord
    if not symbol or not pl.readable:
        return pl.text
    return label(symbol) if label else symbol


def line_rows(
    line: Line, *, written: bool = True, width: int = 72, label: Callable[[str], str] | None = None
) -> list[ChartRow]:
    """One line of the chart as rows of chords over lyrics, wrapped at ``width`` letters.

    ``label`` turns an ASCII symbol into display text (``Bb`` into ``B♭``).
    """
    lyrics = line.lyrics.rstrip()
    marks: list[ChordMark] = []
    # Without lyrics, a chord line's indent means nothing (it often held a label: "Intro: Am")
    starts = [pl.pos or 0 for pl in line.chords]
    offset = -min(starts) if starts and not lyrics.strip() else 0
    prev_end = -1
    for pl in sorted(line.chords, key=lambda p: p.pos or 0):
        text = chord_label(pl, written, label)
        col = (pl.pos or 0) + offset
        if col <= prev_end:
            shift = prev_end + 1 - col
            if col < len(lyrics):
                lyrics = lyrics[:col] + " " * shift + lyrics[col:]
            offset += shift
            col += shift
        marks.append(ChordMark(col, text, pl.readable))
        prev_end = col + len(text)
    return _wrap(ChartRow(marks, lyrics), width)


def _wrap(row: ChartRow, width: int) -> list[ChartRow]:
    if row.width <= width:
        return [row]
    cut = _cut_point(row, width)
    if cut is None:
        return [row]
    first = ChartRow([m for m in row.chords if m.col < cut], row.lyrics[:cut].rstrip())
    rest_lyrics = row.lyrics[cut:]
    strip = len(rest_lyrics) - len(rest_lyrics.lstrip(" "))
    shift = cut + strip
    rest = ChartRow(
        [ChordMark(max(0, m.col - shift), m.label, m.readable) for m in row.chords if m.col >= cut],
        rest_lyrics[strip:],
    )
    return [first, *_wrap(rest, width)]


def _cut_point(row: ChartRow, width: int) -> int | None:
    """The last space at or before ``width`` where no chord label is cut in two."""
    for cut in range(min(width, len(row.lyrics)), 0, -1):
        if row.lyrics[cut - 1 : cut] != " " and cut < len(row.lyrics) and row.lyrics[cut] != " ":
            continue
        if any(m.col < cut < m.col + len(m.label) for m in row.chords):
            continue
        if cut > width // 3:
            return cut
    return None


def chart_text(
    song: Song, *, written: bool = True, width: int = 72, label: Callable[[str], str] | None = None
) -> str:
    """The whole chart as plain text, for the terminal or a .txt export."""
    out: list[str] = []
    for section in song.form:
        title = section_title(section)
        if title:
            repeat = f" x{section.repeat}" if section.repeat else ""
            out.append(f"[{title}]{repeat}")
        for line in section.lines:
            for row in line_rows(line, written=written, width=width, label=label):
                chords = row.chord_text()
                if chords:
                    out.append(chords)
                if row.lyrics.strip():
                    out.append(row.lyrics)
            if line.repeat:
                out[-1] += f"  x{line.repeat}"
        out.append("")
    return "\n".join(out).rstrip() + "\n"
