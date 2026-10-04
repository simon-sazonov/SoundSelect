"""Spotting sheet music in a picture: five evenly spaced long lines. A guitar tab has six, so a
staff with a sixth line at the same spacing doesn't count."""

from __future__ import annotations

import cv2
import numpy as np

from .staves import find_staves
from .stitch import sheet_region

MAX_WIDTH = 1600  # wider pictures are halved first; staff lines stay several pixels apart


def has_staves(data: bytes) -> bool:
    buf = np.frombuffer(data, np.uint8)
    gray = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return False
    if gray.shape[1] > MAX_WIDTH:
        gray = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    gray = sheet_region(gray)  # without a video player's dark frame
    staves, spacing = find_staves(gray)
    if not staves or spacing is None:
        return False
    rows = gray.astype(np.float32)
    real = 0
    for st in staves:
        width = st.x1 - st.x0
        if width < 0.3 * gray.shape[1]:
            continue
        sixth = False
        for y in (st.top - spacing, st.bottom + spacing):
            yi = round(y)
            if 0 <= yi < gray.shape[0]:
                band = rows[max(0, yi - 1) : yi + 2, st.x0 : st.x1].min(axis=0)
                sixth |= bool((band < 128).mean() > 0.8)
        real += not sixth
    return real >= 1
