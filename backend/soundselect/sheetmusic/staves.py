"""Finding staves in a picture: five evenly spaced long lines make a staff, and staves joined
by a line at their left edge make one system (a piano's two hands, for example).

Lines are found in a grayscale row profile after keeping only long horizontal runs, so
anti-aliased lines that blur over two pixel rows in a video frame still count.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

Image = np.ndarray


@dataclass(frozen=True)
class Staff:
    ys: tuple[float, float, float, float, float]  # the five lines, top to bottom
    x0: int
    x1: int

    @property
    def top(self) -> float:
        return self.ys[0]

    @property
    def bottom(self) -> float:
        return self.ys[-1]


def to_gray(img: Image) -> Image:
    """The darkest channel: colored notes stay dark, pale colored highlights fade to paper."""
    return img.min(axis=2) if img.ndim == 3 else img


def _line_candidates(gray: Image) -> list[dict[str, float]]:
    ink = 255.0 - gray.astype(np.float32)
    ink = np.clip(ink - np.median(ink), 0, None)  # paper becomes 0
    length = max(25, gray.shape[1] // 12)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1))
    opened = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
    profile = opened.sum(axis=1)
    if profile.max() <= 0:
        return []
    high = np.percentile(profile[profile > 0], 98)
    rows = np.where(profile > 0.2 * high)[0]
    groups: list[list[int]] = []
    for r in rows:
        if groups and r - groups[-1][-1] <= 1:
            groups[-1].append(int(r))
        else:
            groups.append([int(r)])
    lines = []
    for g in groups:
        idx = np.array(g)
        weights = profile[idx]
        cols = np.where(opened[idx].max(axis=0) > 0)[0]
        lines.append(
            {
                "y": float((idx * weights).sum() / weights.sum()),
                "x0": float(cols.min()),
                "x1": float(cols.max()),
            }
        )
    return lines


def find_staves(gray: Image) -> tuple[list[Staff], float | None]:
    """The staves in a grayscale picture, top to bottom, and the usual line spacing."""
    lines = _line_candidates(gray)
    if len(lines) < 5:
        return [], None
    ys = np.array([ln["y"] for ln in lines])
    gaps = np.diff(ys)
    gaps = gaps[gaps > 2]
    if not len(gaps):
        return [], None
    hist = np.bincount(np.round(gaps * 2).astype(int))  # half-pixel bins
    spacing = float(np.convolve(hist, [1, 1, 1], "same").argmax() / 2.0)
    near = gaps[np.abs(gaps - spacing) <= max(1.0, 0.15 * spacing)]
    if len(near):
        spacing = float(np.median(near))
    tol = max(1.2, 0.2 * spacing)
    staves: list[Staff] = []
    i, last_bottom = 0, -1e9
    while i < len(lines):
        if ys[i] < last_bottom + 0.6 * spacing:
            i += 1
            continue
        idx = [i]
        for _ in range(4):
            target = ys[idx[-1]] + spacing
            j = int(np.argmin(np.abs(ys - target)))
            if abs(ys[j] - target) > tol or j <= idx[-1]:
                break
            idx.append(j)
        if len(idx) == 5:
            x0 = np.array([lines[j]["x0"] for j in idx])
            x1 = np.array([lines[j]["x1"] for j in idx])
            even = np.abs(x0 - np.median(x0)).max() < 4 * spacing
            if even and np.abs(x1 - np.median(x1)).max() < 4 * spacing:
                five = tuple(float(ys[j]) for j in idx)
                staves.append(Staff(five, int(np.median(x0)), int(np.median(x1))))  # type: ignore[arg-type]
                last_bottom = ys[idx[-1]]
                i = idx[-1] + 1
                continue
        i += 1
    return staves, spacing


def joined(gray: Image, a: Staff, b: Staff, spacing: float) -> bool:
    """Whether a line at the staves' left edge runs from staff a down to staff b."""
    x = min(a.x0, b.x0)
    y0, y1 = int(a.bottom + 1), int(b.top - 1)
    if y1 <= y0:
        return True
    band = gray[y0:y1, max(0, x - int(spacing)) : x + int(spacing) + 1]
    if band.size == 0:
        return False
    return bool((band < 160).mean(axis=0).max() > 0.9)


def find_systems(gray: Image) -> tuple[list[list[Staff]], float | None]:
    """Staves grouped into systems (a melody line is a system of one staff)."""
    staves, spacing = find_staves(gray)
    systems: list[list[Staff]] = []
    for staff in staves:
        if systems and spacing and joined(gray, systems[-1][-1], staff, spacing):
            systems[-1].append(staff)
        else:
            systems.append([staff])
    return systems, spacing
