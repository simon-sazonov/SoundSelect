"""Finding a song's key from its chords.

Every one of the 24 major and minor keys gets a score: chords that belong to the key count
fully, common borrowed chords (B♭ in C major, E major in A minor) count partly, and the first
chord, the last chord and dominant-to-tonic moves (G7 to C) add weight. Scores become
probabilities, so the result carries a confidence and the runner-up keys.

Relative keys (C major and A minor) share all their notes and so the same pentatonic; telling
them apart rests on the first and last chords and cadences, which is why the result also
reports how sure the key signature is, separately from major versus minor.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from .chords import Chord
from .keys import Key, Mode
from .pitch import Pitch

_MAJOR_TEMPLATE = {0: "maj", 2: "min", 4: "min", 5: "maj", 7: "maj", 9: "min", 11: "dim"}
_MINOR_TEMPLATE = {0: "min", 2: "dim", 3: "maj", 5: "min", 7: "min", 8: "maj", 10: "maj", 11: "dim"}
# Chords outside the plain template that songs use all the time, with partial credit.
_MAJOR_EXTRA = {
    (10, "maj"): 0.5,  # bVII (B♭ in C)
    (5, "min"): 0.4,  # iv (Fm in C)
    (8, "maj"): 0.4,  # bVI (A♭ in C)
    (3, "maj"): 0.3,  # bIII (E♭ in C)
    (2, "maj"): 0.4,  # II, the dominant of V (D in C)
    (4, "maj"): 0.4,  # III, the dominant of vi (E in C)
    (9, "maj"): 0.3,  # VI, the dominant of ii (A in C)
}
_MINOR_EXTRA = {
    (7, "maj"): 0.9,  # V from harmonic minor (E in A minor)
    (5, "maj"): 0.4,  # IV from dorian (D in A minor)
    (2, "min"): 0.3,  # ii from dorian (Bm in A minor)
}
_MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
_MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10, 11)  # natural minor plus the raised seventh
STATED_BONUS = 4.0
# The first chord is the strongest hint at the tonic. The last one counts half: a whole song
# usually ends on the tonic, but a short loop (Am F C G) just stops wherever it wraps around.
FIRST_WEIGHT = 1.0
LAST_WEIGHT = 0.5


def _kind(chord: Chord) -> str:
    fam = chord.family
    if fam in ("major", "dominant"):
        return "maj"
    if fam == "minor":
        return "min"
    if fam in ("diminished", "half_diminished"):
        return "dim"
    if fam == "augmented":
        return "aug"
    return "neutral"  # suspended and power chords have no third


@dataclass(frozen=True, slots=True)
class KeyGuess:
    key: Key
    score: float
    probability: float


@dataclass(frozen=True, slots=True)
class KeyFinding:
    ranked: tuple[KeyGuess, ...]

    @property
    def best(self) -> KeyGuess:
        return self.ranked[0]

    @property
    def key(self) -> Key:
        return self.ranked[0].key

    @property
    def confidence(self) -> float:
        return self.ranked[0].probability

    @property
    def signature_confidence(self) -> float:
        """How sure the key signature is: the best key plus its relative major or minor."""
        rel = self.key.relative
        return self.confidence + sum(
            g.probability
            for g in self.ranked[1:]
            if g.key.tonic.pc == rel.tonic.pc and g.key.mode == rel.mode
        )


def _chord_score(chord: Chord, tonic: int, mode: Mode) -> float:
    d = (chord.root.pc - tonic) % 12
    kind = _kind(chord)
    template = _MAJOR_TEMPLATE if mode == "major" else _MINOR_TEMPLATE
    extra = _MAJOR_EXTRA if mode == "major" else _MINOR_EXTRA
    scale = {(tonic + s) % 12 for s in (_MAJOR_SCALE if mode == "major" else _MINOR_SCALE)}
    pcs = chord.pitch_classes
    fit = sum(1 for pc in pcs if pc in scale) / len(pcs)
    if kind == "neutral":
        fit_template = 0.8 if chord.root.pc in scale else 0.0
    elif template.get(d) == kind:
        fit_template = 1.0
    else:
        fit_template = extra.get((d, kind), 0.0)
    return 0.5 * fit + fit_template


def _is_tonic(chord: Chord, tonic: int, mode: Mode) -> tuple[bool, bool]:
    """(root is the tonic, chord also has the key's major or minor third)."""
    if chord.root.pc != tonic:
        return False, False
    kind = _kind(chord)
    return True, kind == ("maj" if mode == "major" else "min")


def score_key(chords: Sequence[Chord], tonic: int, mode: Mode) -> float:
    score = sum(_chord_score(c, tonic, mode) for c in chords)
    for edge, weight in ((chords[0], FIRST_WEIGHT), (chords[-1], LAST_WEIGHT)):
        root, quality = _is_tonic(edge, tonic, mode)
        score += weight * ((1.0 if root else 0.0) + (0.5 if quality else 0.0))
    for a, b in pairwise(chords):
        if (a.root.pc - tonic) % 12 == 7 and _kind(a) == "maj":
            root, quality = _is_tonic(b, tonic, mode)
            if root:
                score += (0.4 if a.family == "dominant" else 0.2) + (0.4 if quality else 0.0)
    tonic_chords = sum(1 for c in chords if _is_tonic(c, tonic, mode)[1])
    score += 0.25 * tonic_chords
    return score


def find_key(
    chords: Sequence[Chord], *, stated: Key | None = None, temperature: float = 1.0
) -> KeyFinding | None:
    """Rank all 24 keys for a chord sequence (chord occurrences, in order).

    ``stated`` is a key written on the sheet itself; it gets extra weight but can still lose to
    overwhelming evidence from the chords. Returns None when there are no chords.
    """
    if not chords:
        return None
    spellings = _root_spellings(chords)
    scored: list[tuple[float, Key]] = []
    for mode in ("major", "minor"):
        for pc in range(12):
            s = score_key(chords, pc, mode)
            if stated is not None and stated.tonic.pc == pc and stated.mode == mode:
                s += STATED_BONUS
            prefer = stated.tonic if stated and stated.tonic.pc == pc else spellings.get(pc)
            scored.append((s, Key.from_pc(pc, mode, prefer=prefer)))
    top = max(s for s, _ in scored)
    weights = [math.exp((s - top) / temperature) for s, _ in scored]
    total = sum(weights)
    ranked = sorted(
        (KeyGuess(k, round(s, 3), w / total) for (s, k), w in zip(scored, weights, strict=True)),
        key=lambda g: (-g.score, g.key.mode != "major", g.key.tonic.pc),
    )
    return KeyFinding(tuple(ranked))


def _root_spellings(chords: Sequence[Chord]) -> dict[int, Pitch]:
    """The sheet's most common spelling for each root pitch class."""
    counts: dict[int, Counter[Pitch]] = {}
    for c in chords:
        counts.setdefault(c.root.pc, Counter())[c.root.pitch_class()] += 1
    return {pc: cnt.most_common(1)[0][0] for pc, cnt in counts.items()}
