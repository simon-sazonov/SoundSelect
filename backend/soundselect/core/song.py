"""The Song result: the one shape every tool produces and every screen, export and API answer uses.

Pitches are spelled note names in ASCII (``Bb``, ``F#4``), so C# and Db stay different; display
names (letters, Russian, ...) are added only when asked for, in ``names``. Anything that differs
between concert pitch and the player's instrument comes as a ``concert``/``written`` pair.

Parts that later phases fill in (melody, timing, source pages) already have their place.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .chords import ChordFamily
from .keys import Key
from .scales import ScaleKind, ScaleRole

SCHEMA_VERSION = 1

SourceKind = Literal["text", "pdf", "photo", "screenshots", "audio", "link", "video"]
SectionKind = Literal[
    "intro",
    "verse",
    "pre_chorus",
    "chorus",
    "bridge",
    "solo",
    "instrumental",
    "interlude",
    "outro",
    "coda",
    "other",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identity(Model):
    title: str | None = None
    artist: str | None = None
    source: SourceKind = Field(description="What the song was read from.")
    source_name: str | None = Field(None, description="File name or link, when there is one.")
    fingerprint: str = Field(description="SHA-256 of the input, used to spot repeats.")


class KeyName(Model):
    tonic: str = Field(description="Spelled tonic, e.g. 'Bb'.")
    mode: Literal["major", "minor"]
    fifths: int = Field(description="Key signature: sharps positive, flats negative.")

    @classmethod
    def of(cls, key: Key) -> KeyName:
        return cls(tonic=str(key.tonic), mode=key.mode, fifths=key.fifths)

    def to_key(self) -> Key:
        from .pitch import Pitch

        return Key(Pitch.parse(self.tonic), self.mode)


class KeyCandidate(Model):
    key: KeyName
    probability: float


class KeyResult(Model):
    concert: KeyName = Field(description="The song's key in concert pitch.")
    confidence: float = Field(description="0-1: how sure this exact key is.")
    signature_confidence: float = Field(
        description="0-1: how sure the key signature is (this key or its relative major/minor, "
        "which share the pentatonic notes)."
    )
    runners_up: list[KeyCandidate] = Field(default_factory=list)
    basis: Literal["chords", "stated", "melody", "signature", "correction"] = "chords"


class InstrumentView(Model):
    instrument: str = Field(description="Instrument id, e.g. 'alto_sax'.")
    name: str = Field(description="Display name, e.g. 'Alto sax in E♭'.")
    interval: str = Field(
        description="Interval from concert to written pitch: 'M6' for alto sax, or 'd7' when the "
        "written key is respelled to avoid more than six sharps."
    )
    respelled: bool = False
    written_key: KeyName | None = None
    comfortable_low: str = Field(description="Lowest comfortable written note, e.g. 'C4'.")
    comfortable_high: str = Field(description="Highest comfortable written note, e.g. 'C6'.")


class Spelled(Model):
    """The same pitches in concert pitch and as written for the instrument."""

    concert: list[str] = Field(default_factory=list)
    written: list[str] = Field(default_factory=list)


class ChordSpelling(Model):
    symbol: str = Field(description="ASCII chord symbol, e.g. 'Bb/D'.")
    root: str
    quality: str = Field(description="Normalized suffix, e.g. 'm7', 'maj7', 'sus4'.")
    bass: str | None = None
    tones: list[str] = Field(description="Chord notes from the root up.")


class ScaleSpelling(Model):
    root: str
    notes: list[str] = Field(description="Scale notes without octaves.")
    staff: list[str] = Field(
        default_factory=list,
        description="The notes with octaves as drawn on the staff, rising one octave.",
    )


class ScaleInfo(Model):
    kind: ScaleKind
    role: ScaleRole = Field(
        description="'headline' is the key's pentatonic, shown first; 'song' other whole-song "
        "scales; 'chord' the scale offered over a chord; 'alternative' another option."
    )
    reason: str
    concert: ScaleSpelling
    written: ScaleSpelling | None = None


class ChordInfo(Model):
    symbol: str = Field(description="Concert-pitch symbol; lines refer to chords by it.")
    family: ChordFamily
    count: int = Field(description="How many times the chord appears.")
    concert: ChordSpelling
    written: ChordSpelling | None = None
    scales: list[ScaleInfo] = Field(
        default_factory=list, description="The scale offered over this chord first, then options."
    )
    clashes: Spelled = Field(
        default_factory=Spelled,
        description="Notes of the key's pentatonic that rub against this chord.",
    )


class SourceRef(Model):
    page: int
    box: tuple[float, float, float, float] | None = Field(
        None, description="x0, y0, x1, y1 on the page image, in pixels."
    )


class ChordPlacement(Model):
    chord: str | None = Field(
        description="Concert symbol (a key into Song.chords); null for 'N.C.' (no chord)."
    )
    written: str | None = None
    text: str = Field(description="The chord exactly as it appears in the source.")
    readable: bool = Field(True, description="False when the text could not be read as a chord.")
    pos: int | None = Field(None, description="Letter position in the line, for sheets.")
    beat: float | None = Field(None, description="Beat from the start, for songs.")


class Line(Model):
    lyrics: str = ""
    chords: list[ChordPlacement] = Field(default_factory=list)
    repeat: int | None = Field(None, description="Play the line this many times ('x2').")
    source: SourceRef | None = None


class Section(Model):
    kind: SectionKind = "other"
    label: str | None = Field(None, description="The label as written, e.g. 'Припев'.")
    repeat: int | None = Field(None, description="Play the section this many times ('x2').")
    lines: list[Line] = Field(default_factory=list)


class MelodyNote(Model):
    concert: str | None = Field(description="Concert pitch with octave; null for a rest.")
    written: str | None = None
    start: float = Field(description="Start in beats from the beginning.")
    length: float = Field(description="Length in beats.")
    confidence: float | None = None
    out_of_range: bool = False


class Melody(Model):
    notes: list[MelodyNote] = Field(default_factory=list)
    octave_shift: int = Field(0, description="Octaves the melody was moved to fit the range.")
    source: Literal["audio", "sheet_music"]


class Timing(Model):
    tempo: float | None = Field(None, description="Beats per minute.")
    time_signature: str | None = None
    beat_times: list[float] | None = Field(None, description="Beat times in seconds (songs).")
    downbeats: list[float] | None = None


class ChordFix(Model):
    """Replace a chord: one occurrence (line and index) or, without them, every occurrence."""

    original: str = Field(description="The chord as it was read.")
    to: str = Field(description="The right chord, as on the sheet; empty to remove it.")
    line: int | None = Field(None, description="Line number counted across the whole song.")
    index: int | None = Field(None, description="Which chord in that line, from 0.")


class Corrections(Model):
    """The player's edits, kept apart from what was computed."""

    title: str | None = None
    artist: str | None = None
    key: str | None = Field(None, description="Concert key, e.g. 'Bb major' or 'Gm'.")
    capo: int | None = Field(None, description="Capo fret (or half steps) instead of the sheet's.")
    chords: list[ChordFix] = Field(default_factory=list)
    melody_octave: int | None = None
    page_instrument: str | None = Field(
        None,
        description="Sheet music: the instrument the page is written for ('alto_sax', or "
        "'concert' for concert pitch), instead of what was read from its part name.",
    )


class Notice(Model):
    level: Literal["info", "warning"] = "info"
    code: str
    message: str
    line: int | None = None


class SourcePage(Model):
    index: int
    image: str | None = None
    width: int | None = None
    height: int | None = None


class SheetMusicInfo(Model):
    """What a piece of sheet music was read from and how (Phase 3)."""

    page_instrument: str = Field(
        "concert",
        description="The instrument the page is written for: 'concert' for concert pitch, or "
        "e.g. 'alto_sax'. A page already written for alto is not transposed twice.",
    )
    part_name: str | None = Field(None, description="The part name as read on the page.")
    systems: int = Field(description="Lines of music (systems) kept after joining the views.")
    measures: int = Field(description="Bars read.")
    views: int = Field(description="Screenshots, or views taken from the video, that were used.")


class Song(Model):
    kind: Literal["song"] = "song"
    schema_version: int = SCHEMA_VERSION
    id: str | None = None
    identity: Identity
    key: KeyResult | None = None
    view: InstrumentView | None = None
    form: list[Section] = Field(default_factory=list)
    chords: list[ChordInfo] = Field(default_factory=list)
    scales: list[ScaleInfo] = Field(
        default_factory=list,
        description="Whole-song scales; the first, role 'headline', is the key's pentatonic.",
    )
    melody: Melody | None = None
    timing: Timing | None = None
    corrections: Corrections = Field(default_factory=Corrections)
    notes: list[Notice] = Field(default_factory=list, description="Notes to the player.")
    source_pages: list[SourcePage] = Field(default_factory=list)
    sheet_music: SheetMusicInfo | None = Field(None, description="Present for sheet music.")
    versions: dict[str, str] = Field(
        default_factory=dict, description="Version of each step that produced this result."
    )
    names: dict[str, str] | None = Field(
        None,
        description="Display names for every pitch in the song, keyed by its text without "
        "octave ('Bb' -> 'си♭'); present when names were asked for.",
    )
    name_system: str | None = None

    def lines(self) -> list[Line]:
        """All lines in order, across sections (line numbers in corrections count these)."""
        return [line for section in self.form for line in section.lines]

    def chord_info(self, symbol: str) -> ChordInfo | None:
        return next((c for c in self.chords if c.symbol == symbol), None)

    @property
    def headline(self) -> ScaleInfo | None:
        return next((s for s in self.scales if s.role == "headline"), None)
