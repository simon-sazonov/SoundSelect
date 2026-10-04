"""The music core step: from a concert-pitch Song to what the player reads.

It writes the key, every chord and every scale for the chosen instrument, puts the key's
pentatonic first, offers a scale for each chord and marks where the key's pentatonic clashes.
It never cares whether the Song came from a sheet or a recording.
"""

from __future__ import annotations

from .chords import Chord, parse_chord
from .instruments import DEFAULT_INSTRUMENT, Instrument, Transposition, get_instrument
from .keys import Key
from .names import NameSystem, names_table
from .pitch import Interval, Pitch
from .ranges import place_ascending
from .scales import Scale, ScaleChoice, chord_scales, clashes, song_scales
from .song import (
    ChordInfo,
    ChordSpelling,
    InstrumentView,
    KeyName,
    Melody,
    ScaleInfo,
    ScaleSpelling,
    Song,
    Spelled,
)

VERSION = "1"


def concert_chord(symbol: str) -> Chord:
    """Chord symbols stored in a Song are canonical: B means B natural."""
    c = parse_chord(symbol)
    if c is None:
        raise ValueError(f"not a chord symbol: {symbol!r}")
    return c


def chord_spelling(c: Chord) -> ChordSpelling:
    return ChordSpelling(
        symbol=c.symbol,
        root=str(c.root),
        quality=c.quality,
        bass=str(c.bass) if c.bass else None,
        tones=[str(t) for t in c.tones],
    )


def _scale_info(choice: ScaleChoice, tr: Transposition, low: Pitch, high: Pitch) -> ScaleInfo:
    scale = choice.scale
    written = scale.transpose(tr.interval)
    staff = place_ascending(written.notes, low, high, floor=tr.instrument.lowest)
    concert_staff = [n.transpose(-tr.interval) for n in staff]
    return ScaleInfo(
        kind=scale.kind,
        role=choice.role,
        reason=choice.reason,
        concert=ScaleSpelling(
            root=str(scale.root),
            notes=[str(n) for n in scale.notes],
            staff=[str(n) for n in concert_staff],
        ),
        written=ScaleSpelling(
            root=str(written.root),
            notes=[str(n) for n in written.notes],
            staff=[str(n) for n in staff],
        ),
    )


def _bluesy(song: Song, key: Key) -> bool:
    """A major key whose own chord appears as a seventh chord (A7 in A major)."""
    if key.mode != "major":
        return False
    return any(
        c.family == "dominant" and Pitch.parse(c.concert.root).pc == key.tonic.pc
        for c in song.chords
    )


def apply_instrument(
    song: Song,
    instrument: str | Instrument = DEFAULT_INSTRUMENT,
    *,
    comfortable_low: str | None = None,
    comfortable_high: str | None = None,
) -> Song:
    """Fill in the instrument view: written key, chords, scales and clash marks."""
    inst = get_instrument(instrument) if isinstance(instrument, str) else instrument
    low = Pitch.parse(comfortable_low) if comfortable_low else inst.comfortable_low
    high = Pitch.parse(comfortable_high) if comfortable_high else inst.comfortable_high
    key = song.key.concert.to_key() if song.key else None
    tr = Transposition.for_key(inst, key)

    view = InstrumentView(
        instrument=inst.id,
        name=inst.display_name,
        interval=tr.interval.name,
        respelled=tr.respelled,
        written_key=KeyName.of(tr.written_key) if tr.written_key else None,
        comfortable_low=str(low),
        comfortable_high=str(high),
    )

    scales: list[ScaleInfo] = []
    headline: Scale | None = None
    if key is not None:
        choices = song_scales(key, bluesy=_bluesy(song, key))
        headline = choices[0].scale
        scales = [_scale_info(c, tr, low, high) for c in choices]

    chords: list[ChordInfo] = []
    written_symbols: dict[str, str] = {}
    for info in song.chords:
        c = concert_chord(info.symbol)
        wc = c.transpose(tr.interval)
        written_symbols[info.symbol] = wc.symbol
        clash = clashes(c, headline.notes) if headline else []
        chords.append(
            info.model_copy(
                update={
                    "written": chord_spelling(wc),
                    "scales": [_scale_info(s, tr, low, high) for s in chord_scales(c, key)],
                    "clashes": Spelled(
                        concert=[str(n) for n in clash],
                        written=[str(n.transpose(tr.interval)) for n in clash],
                    ),
                }
            )
        )

    form = []
    for section in song.form:
        lines = []
        for line in section.lines:
            placements = [
                pl.model_copy(
                    update={"written": written_symbols.get(pl.chord) if pl.chord else None}
                )
                for pl in line.chords
            ]
            lines.append(line.model_copy(update={"chords": placements}))
        form.append(section.model_copy(update={"lines": lines}))

    versions = dict(song.versions)
    versions["view"] = VERSION
    update: dict[str, object] = {
        "view": view,
        "scales": scales,
        "chords": chords,
        "form": form,
        "versions": versions,
    }
    if song.melody is not None:
        update["melody"] = _written_melody(song.melody, tr.interval, low, high)
    return song.model_copy(update=update)


def _written_melody(melody: Melody, interval: Interval, low: Pitch, high: Pitch) -> Melody:
    """Each note written for the instrument, moved by the melody's octave shift, and marked
    when it falls outside the comfortable range. Rests stay rests."""
    notes = []
    for n in melody.notes:
        if n.concert is None:
            notes.append(n.model_copy(update={"written": None, "out_of_range": False}))
            continue
        p = Pitch.parse(n.concert).transpose(interval)
        p = p.at_octave((p.octave if p.octave is not None else 4) + melody.octave_shift)
        outside = p.midi < low.midi or p.midi > high.midi
        notes.append(n.model_copy(update={"written": str(p), "out_of_range": outside}))
    return melody.model_copy(update={"notes": notes})


def song_pitches(song: Song) -> list[Pitch]:
    """Every spelled pitch the song shows, concert and written, for building a names table."""
    texts: list[str] = []
    if song.key:
        texts.append(song.key.concert.tonic)
    if song.view and song.view.written_key:
        texts.append(song.view.written_key.tonic)
    for s in song.scales:
        texts += s.concert.notes + (s.written.notes if s.written else [])
    for c in song.chords:
        texts += c.concert.tones + [c.concert.root] + ([c.concert.bass] if c.concert.bass else [])
        if c.written:
            texts += [*c.written.tones, c.written.root]
            texts += [c.written.bass] if c.written.bass else []
        for s in c.scales:
            texts += s.concert.notes + (s.written.notes if s.written else [])
    if song.melody:
        for n in song.melody.notes:
            texts += [t for t in (n.concert, n.written) if t]
    seen: dict[str, Pitch] = {}
    for t in texts:
        pc = Pitch.parse(t).pitch_class()
        seen.setdefault(str(pc), pc)
    return list(seen.values())


def with_names(song: Song, system: NameSystem) -> Song:
    """Add display names for every pitch in the song (never stored; switching costs nothing)."""
    return song.model_copy(
        update={"names": names_table(song_pitches(song), system), "name_system": system}
    )


def transposition_of(song: Song) -> Interval:
    if song.view is None:
        raise ValueError("song has no instrument view")
    return Interval.parse(song.view.interval)
