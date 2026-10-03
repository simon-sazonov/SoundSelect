"""The song as plain text: what the command line prints, and the .txt export."""

from __future__ import annotations

from ..core.chords import parse_chord
from ..core.keys import Key
from ..core.names import NameSystem, chord_root_hint, key_name, note_name, scale_name
from ..core.pitch import Pitch
from ..core.scales import LABELS
from ..core.song import ScaleInfo, ScaleSpelling, Song
from .chart import chart_text


def _shown(names: NameSystem) -> NameSystem:
    return "letters" if names == "none" else names


def _in_letters(names: NameSystem) -> bool:
    return names in ("letters", "none")


def _notes(notes: list[str], names: NameSystem) -> str:
    letters = " ".join(Pitch.parse(n).display() for n in notes)
    if _in_letters(names):
        return letters
    if names == "both":
        return f"{letters}  ({' '.join(note_name(Pitch.parse(n), 'russian') for n in notes)})"
    text = " ".join(note_name(Pitch.parse(n), names) for n in notes)
    return f"{text}  ({letters})"


def _key(key: Key, names: NameSystem) -> str:
    name = key_name(key, _shown(names))
    if _in_letters(names) or names == "both":
        return f"{name} ({key.signature_text()})"
    return f"{name} ({key.display()}, {key.signature_text()})"


def _spelling(scale: ScaleInfo, written: bool) -> ScaleSpelling:
    return scale.written if written and scale.written else scale.concert


def _scale_label(scale: ScaleInfo, written: bool, names: NameSystem) -> str:
    spelling = _spelling(scale, written)
    return scale_name(LABELS[scale.kind], Pitch.parse(spelling.root), _shown(names))


def _display(symbol: str) -> str:
    chord = parse_chord(symbol)
    return chord.display() if chord else symbol


def song_text(
    song: Song, names: NameSystem = "russian", *, written: bool = True, chart: bool = True
) -> str:
    """Key, pentatonic, scales, chords and (with ``chart``) the chord chart, as text."""
    view = song.view if written else None
    written = view is not None
    out: list[str] = []
    title = song.identity.title or "Untitled song"
    out.append(f"{title} · {song.identity.artist}" if song.identity.artist else title)

    if song.key:
        if view and view.written_key:
            out.append(f"Key for {view.name}: {_key(view.written_key.to_key(), names)}")
        concert = f"Concert key: {_key(song.key.concert.to_key(), names)}"
        if song.key.basis == "chords":
            concert += f", {round(song.key.confidence * 100)}% sure"
        elif song.key.basis == "stated":
            concert += ", as written on the sheet"
        elif song.key.basis == "correction":
            concert += ", as you set it"
        out.append(concert)

    headline = song.headline
    if headline:
        out += ["", f"Your pentatonic: {_scale_label(headline, written, names)}"]
        out.append(f"  {_notes(_spelling(headline, written).notes, names)}")
    others = [s for s in song.scales if s is not headline]
    if others:
        out += ["", "More scales for the whole song:"]
        for s in others:
            out.append(
                f"  {_scale_label(s, written, names)}: {_notes(_spelling(s, written).notes, names)}"
            )

    if song.chords:
        heading = f"Chords for {view.name}" if view else "Chords (concert pitch)"
        out += ["", f"{heading}, with the scale to play over each:"]
        rows = []
        for info in song.chords:
            shown = info.written if written and info.written else info.concert
            chord = parse_chord(shown.symbol)
            hint = chord_root_hint(chord, names) if chord else None
            name = _display(shown.symbol) + (f" {hint}" if hint else "")
            concert = f"(concert {_display(info.concert.symbol)})" if written else ""
            scale = f"{_scale_label(info.scales[0], written, names)}" if info.scales else ""
            clashes = info.clashes.written if written else info.clashes.concert
            clash = f"; clashes with your pentatonic: {_notes(clashes, names)}" if clashes else ""
            rows.append((name, concert, scale + clash))
        w1 = max(len(r[0]) for r in rows)
        w2 = max(len(r[1]) for r in rows)
        for name, concert, rest in rows:
            out.append(f"  {name.ljust(w1)}  {concert.ljust(w2)}  {rest}".rstrip())

    if chart and song.form:
        out += ["", chart_text(song, written=written, label=_display).rstrip()]

    if song.notes:
        out += ["", "Notes:"]
        out += [f"  - {n.message}" for n in song.notes]
    return "\n".join(out) + "\n"
