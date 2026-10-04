"""Finding a song's key from what is heard: the melody's notes (how long each pitch class is
held) and the band's sound (how strongly each pitch class rings), compared with the classic
Krumhansl-Kessler key profiles. Chord recognition comes in a later phase and will add its
evidence here."""

from __future__ import annotations

import math

import numpy as np

from ..core.keys import Key
from ..core.song import KeyCandidate, KeyName, KeyResult
from .model import Beats, Rhythm

MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
SHARPNESS = 25.0  # turns correlations into probabilities
MELODY_WEIGHT = 0.5


def melody_profile(rhythm: Rhythm) -> np.ndarray:
    weights = np.zeros(12)
    for n in rhythm.notes:
        weights[n.pitch % 12] += n.length * (0.5 + n.confidence)
    return weights


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    denom = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 0 else 0.0


def rank_keys(profile: np.ndarray) -> list[tuple[float, Key]]:
    """(probability, key) for all 24 keys, best first."""
    scored = []
    for mode, template in (("major", MAJOR), ("minor", MINOR)):
        for tonic in range(12):
            scored.append((_corr(profile, np.roll(template, tonic)), Key.from_pc(tonic, mode)))
    top = max(s for s, _ in scored)
    weights = [math.exp(SHARPNESS * (s - top)) for s, _ in scored]
    total = sum(weights)
    ranked = [(w / total, k) for (_, k), w in zip(scored, weights, strict=True)]
    return sorted(ranked, key=lambda x: -x[0])


def song_key(rhythm: Rhythm, beats: Beats, corrected: str | None = None) -> KeyResult | None:
    """The key in concert pitch: the player's correction, or the best guess from the sound."""
    if corrected:
        k = Key.parse(corrected).normalized()
        return KeyResult(
            concert=KeyName.of(k), confidence=1.0, signature_confidence=1.0, basis="correction"
        )
    melody = melody_profile(rhythm)
    band = np.asarray(beats.chroma, dtype=float)
    parts = []
    if melody.sum() > 0:
        parts.append(MELODY_WEIGHT * melody / melody.sum())
    if band.sum() > 0:
        parts.append((1 - MELODY_WEIGHT if parts else 1.0) * band / band.sum())
    if not parts:
        return None
    ranked = rank_keys(sum(parts))
    p, best = ranked[0]
    rel = best.relative
    signature = p + sum(
        q for q, k in ranked[1:] if k.tonic.pc == rel.tonic.pc and k.mode == rel.mode
    )
    return KeyResult(
        concert=KeyName.of(best),
        confidence=round(p, 3),
        signature_confidence=round(min(1.0, signature), 3),
        runners_up=[
            KeyCandidate(key=KeyName.of(k), probability=round(q, 3)) for q, k in ranked[1:4]
        ],
        basis="melody",
    )
