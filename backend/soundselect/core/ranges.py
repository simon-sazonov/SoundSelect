"""Placing notes on the staff in the player's range."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .pitch import Pitch


def place_ascending(
    notes: Sequence[Pitch],
    low: Pitch,
    high: Pitch,
    *,
    floor: Pitch | None = None,
    add_octave: bool = True,
) -> list[Pitch]:
    """Give pitch classes octaves so they rise from the first note.

    The first note sits at the lowest octave at or above ``low``; when the top would go above
    ``high`` everything moves down an octave, as long as nothing drops below ``floor`` (the
    instrument's lowest note). With ``add_octave`` the first note is repeated an octave up at the
    end, as scales are usually written.
    """
    if not notes:
        return []
    first = notes[0]
    octave = (low.octave or 4) - 1
    while first.at_octave(octave).midi < low.midi:
        octave += 1

    def build(o: int) -> list[Pitch]:
        out = [first.at_octave(o)]
        for n in list(notes[1:]) + ([first] if add_octave else []):
            cand = n.at_octave(out[-1].octave - 1)
            while cand.midi <= out[-1].midi:
                cand = cand.at_octave(cand.octave + 1)
            out.append(cand)
        return out

    placed = build(octave)
    if placed[-1].midi > high.midi:
        lower = build(octave - 1)
        if floor is None or lower[0].midi >= floor.midi:
            placed = lower
    return placed


@dataclass(frozen=True, slots=True)
class RangeFit:
    """How a melody was moved by octaves to fit, and which notes are still outside."""

    octaves: int
    notes: list[Pitch]
    out_of_range: list[int]


def fit_melody(
    notes: Sequence[Pitch], low: Pitch, high: Pitch, *, lowest: Pitch, highest: Pitch
) -> RangeFit:
    """Move a melody by whole octaves so most notes sit in the comfortable range ``low``-``high``.

    Ties go to the smallest move. Notes still outside the instrument's own range
    (``lowest``-``highest``) are listed so they can be marked.
    """
    if not notes:
        return RangeFit(0, [], [])

    def shifted(k: int) -> list[Pitch]:
        return [n.at_octave(n.octave + k) for n in notes]

    def score(k: int) -> tuple[int, int, int]:
        moved = shifted(k)
        comfortable = sum(1 for n in moved if low.midi <= n.midi <= high.midi)
        playable = sum(1 for n in moved if lowest.midi <= n.midi <= highest.midi)
        return (playable, comfortable, -abs(k))

    best = max(range(-4, 5), key=score)
    moved = shifted(best)
    outside = [i for i, n in enumerate(moved) if not lowest.midi <= n.midi <= highest.midi]
    return RangeFit(best, moved, outside)
