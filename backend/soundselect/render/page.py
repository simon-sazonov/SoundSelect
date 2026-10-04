"""The song page: what a chord sheet becomes, as one HTML page that also prints to PDF.

Order, as the plan sets it: the key (for the instrument and in concert pitch) with the key's
pentatonic on the staff right under it, the other whole-song scales, the chord chart with the
instrument's chords over the lyrics, each chord's scale and notes, then any notes to the player.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cache

from jinja2 import Environment, PackageLoader, Template, select_autoescape
from markupsafe import Markup

from .. import __version__
from ..core.chords import parse_chord
from ..core.keys import Key
from ..core.names import NameSystem, chord_root_hint, key_name, note_name, scale_name
from ..core.pitch import Pitch
from ..core.scales import LABELS
from ..core.song import Line, ScaleInfo, ScaleSpelling, Song
from .chart import line_rows, section_title
from .musicxml import scale_measure, score_xml
from .scores import chord_score
from .staff import draw, music_font_css

CHART_WIDTH = 72  # letters per chart line before it wraps


@cache
def _env() -> Environment:
    return Environment(
        loader=PackageLoader("soundselect.render", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


@dataclass
class KeyView:
    name: str
    letters: str | None  # the key in letters, when the name is in another system
    signature: str


@dataclass
class ChartChord:
    col: int
    label: str
    bad: bool = False


@dataclass
class RowView:
    chords: list[ChartChord]
    lyrics: str
    width: int
    repeat: int | None = None  # on a line's last row: play the line this many times


@dataclass
class SectionView:
    label: str | None
    repeat: int | None
    lines: list[list[RowView]] = field(default_factory=list)


@dataclass
class ScaleView:
    label: str
    letters: str | None  # "G major pentatonic: G A B D E G", when names are not letters
    reason: str
    names: str
    svg: Markup


@dataclass
class ChordView:
    written: str
    concert: str
    hint: str | None
    scale_label: str
    scale_names: str
    tones: str
    clashes: str
    count: int
    svg: Markup  # the chord's notes, then its scale


def _shown(names: NameSystem) -> NameSystem:
    """The system for text lines: names switched off still show letters."""
    return "letters" if names == "none" else names


def _names(notes: list[str], names: NameSystem) -> str:
    if names == "both":
        russian = "  ".join(note_name(Pitch.parse(n), "russian") for n in notes)
        return f"{_letters(notes)} · {russian}"
    return "  ".join(note_name(Pitch.parse(n), _shown(names)) for n in notes)


def _letters(notes: list[str]) -> str:
    return " ".join(Pitch.parse(n).display() for n in notes)


def _display_chord(symbol: str | None) -> str:
    c = parse_chord(symbol) if symbol else None
    return c.display() if c else (symbol or "")


def _key_view(key: Key, names: NameSystem) -> KeyView:
    name = key_name(key, _shown(names))
    letters = key.display() if names not in ("letters", "none", "both") else None
    return KeyView(name, letters, key.signature_text())


def _scale_label(kind: str, spelling: ScaleSpelling, names: NameSystem) -> str:
    return scale_name(LABELS[kind], Pitch.parse(spelling.root), _shown(names))


def _scale_view(scale: ScaleInfo, names: NameSystem, written: bool, fifths: int) -> ScaleView:
    spelling = scale.written if written and scale.written else scale.concert
    xml = score_xml([scale_measure(spelling.staff, names)], key_fifths=fifths)
    letters = None
    if names not in ("letters", "none"):
        root = Pitch.parse(spelling.root).display()
        letters = f"{root} {LABELS[scale.kind]}: {_letters(spelling.notes)}"
    return ScaleView(
        label=_scale_label(scale.kind, spelling, names),
        letters=letters,
        reason=scale.reason,
        names=_names(spelling.notes, names),
        svg=Markup(draw(xml, wrap=False)),
    )


def _line_rows(line: Line, written: bool) -> list[RowView]:
    rows = [
        RowView(
            [ChartChord(m.col, m.label, not m.readable) for m in row.chords],
            row.lyrics,
            row.width,
        )
        for row in line_rows(line, written=written, width=CHART_WIDTH, label=_display_chord)
    ]
    if rows and line.repeat:
        rows[-1].repeat = line.repeat
    return rows


def _chord_view(song: Song, index: int, names: NameSystem, written: bool) -> ChordView:
    info = song.chords[index]
    xml = chord_score(song, info, names=names, view="written" if written else "concert")
    shown = info.written if written and info.written else info.concert
    scale = info.scales[0] if info.scales else None
    spelling = None
    if scale:
        spelling = scale.written if written and scale.written else scale.concert
    chord = parse_chord(shown.symbol)
    return ChordView(
        written=_display_chord(shown.symbol),
        concert=_display_chord(info.concert.symbol),
        hint=chord_root_hint(chord, names) if chord else None,
        scale_label=_scale_label(scale.kind, spelling, names) if scale and spelling else "",
        scale_names=_names(spelling.notes, names) if spelling else "",
        tones=_names(shown.tones, names),
        clashes=_names(info.clashes.written if written else info.clashes.concert, names),
        count=info.count,
        svg=Markup(draw(xml, wrap=False)),
    )


def song_context(song: Song, names: NameSystem = "russian", *, written: bool = True) -> dict:
    """Everything the page template shows, worked out from the Song result."""
    view = song.view
    written = written and view is not None
    concert_key = song.key.concert.to_key() if song.key else None
    written_key = view.written_key.to_key() if written and view and view.written_key else None
    fifths = (written_key or concert_key).fifths if (written_key or concert_key) else 0

    scales = [_scale_view(s, names, written, fifths) for s in song.scales]
    headline = scales[0] if scales and song.scales[0].role == "headline" else None
    others = scales[1:] if headline else scales

    sections = []
    for section in song.form:
        sv = SectionView(section_title(section), section.repeat)
        sv.lines = [_line_rows(line, written) for line in section.lines]
        sections.append(sv)

    chords = [_chord_view(song, i, names, written) for i in range(len(song.chords))]

    key = song.key
    return {
        "song": song,
        "title": song.identity.title or "Untitled song",
        "artist": song.identity.artist,
        "instrument": view.name if written and view else "concert pitch",
        "concert_key": _key_view(concert_key, names) if concert_key else None,
        "written_key": _key_view(written_key, names) if written_key else None,
        "respelled": bool(written and view and view.respelled),
        "sure": round(key.confidence * 100) if key and key.basis == "chords" else None,
        "signature_sure": (
            round(key.signature_confidence * 100)
            if key and key.basis == "chords" and key.signature_confidence > key.confidence + 0.05
            else None
        ),
        "key_basis": key.basis if key else None,
        "headline": headline,
        "scales": others,
        "sections": sections,
        "chords": chords,
        "notes": song.notes,
        "names": names,
        "music_font_css": Markup(music_font_css()),
        "version": __version__,
        "today": date.today().isoformat(),
    }


def song_page(
    song: Song,
    names: NameSystem = "russian",
    *,
    written: bool = True,
    head: Markup | None = None,
    before: Markup | None = None,
) -> str:
    """The whole song page as one self-contained HTML document.

    ``head`` adds to the page's head and ``before`` goes above the song; the app's screens
    use them for their bar of buttons, which never prints.
    """
    context = song_context(song, names, written=written)
    return _env().get_template("song.html").render(**context, footer=True, head=head, before=before)


def song_body(song: Song, names: NameSystem = "russian", *, written: bool = True) -> Markup:
    """The song's part of a page, without the page around it (for songbooks)."""
    context = song_context(song, names, written=written)
    return Markup(_env().get_template("_song_body.html").render(**context, footer=False))


def template(name: str) -> Template:
    return _env().get_template(name)
