"""From every note heard in the voice to one line of melody.

The note finder hears overtones as extra notes an octave or a fifth above the sung one, the
singer's vibrato as quick neighbour notes, and short blips from consonants and breath. Each
is cleaned up here: dropping overtone ghosts took the research test from 9 to 28 notes right
out of 30.
"""

from __future__ import annotations

from .model import NoteEvent

LOWEST = 40  # E2: below a bass singer's usual range, what's left is the bass guitar leaking in
HIGHEST = 88  # E6
MIN_SECONDS = 0.08
GHOSTS = (12, 19, 24, 28)  # octave, octave and a fifth, two octaves, two octaves and a third
VIBRATO_SECONDS = 0.15


def _overlaps(a: NoteEvent, b: NoteEvent) -> bool:
    return a.start < b.end and b.start < a.end


def drop_ghosts(notes: list[NoteEvent]) -> list[NoteEvent]:
    """Drop notes sitting on an overtone of a louder note that sounds at the same time."""
    keep = []
    for n in notes:
        ghost = any(
            o is not n
            and (n.pitch - o.pitch) in GHOSTS
            and o.strength >= 0.8 * n.strength
            and _overlaps(n, o)
            for o in notes
        )
        if not ghost and LOWEST <= n.pitch <= HIGHEST and n.end - n.start >= MIN_SECONDS:
            keep.append(n)
    return keep


def one_line(notes: list[NoteEvent]) -> list[NoteEvent]:
    """Where notes overlap, the louder and higher one wins: the lead is usually both."""
    out: list[NoteEvent] = []
    for n in sorted(notes, key=lambda e: (e.start, -e.pitch)):
        if out and n.start < out[-1].end - 0.05:
            prev = out[-1]
            if n.strength + 0.004 * n.pitch > prev.strength + 0.004 * prev.pitch:
                cut = prev.model_copy(update={"end": n.start})
                out.pop()
                if cut.end - cut.start >= MIN_SECONDS:
                    out.append(cut)
                out.append(n)
            elif n.end > prev.end + MIN_SECONDS:  # the loser outlasts the winner: keep its tail
                out.append(n.model_copy(update={"start": prev.end}))
            continue
        if out and n.start < out[-1].end:
            out[-1] = out[-1].model_copy(update={"end": n.start})
        out.append(n)
    return [n for n in out if n.end - n.start >= MIN_SECONDS]


def merge_wobbles(notes: list[NoteEvent]) -> list[NoteEvent]:
    """Fold a short note a half or whole step from its neighbour (vibrato, a slide into the
    note) into that neighbour, and join a note to its own repeat across a tiny gap."""
    out = list(notes)
    changed = True
    while changed:
        changed = False
        for i in range(len(out) - 1):
            a, b = out[i], out[i + 1]
            touching = b.start - a.end < 0.04
            if not touching:
                continue
            same = a.pitch == b.pitch and b.start - a.end < 0.02 and b.strength < 0.6
            short_a = a.end - a.start < VIBRATO_SECONDS and abs(a.pitch - b.pitch) <= 2
            short_b = b.end - b.start < VIBRATO_SECONDS and abs(a.pitch - b.pitch) <= 2
            if not (same or short_a or short_b):
                continue
            keeper = b if short_a and not short_b else a
            merged = keeper.model_copy(
                update={
                    "start": a.start,
                    "end": b.end,
                    "strength": round(max(a.strength, b.strength), 4),
                }
            )
            out[i : i + 2] = [merged]
            changed = True
            break
    return out


def clean_melody(notes: list[NoteEvent]) -> list[NoteEvent]:
    """One line of melody from every note heard, in time order."""
    return merge_wobbles(one_line(drop_ghosts(notes)))
