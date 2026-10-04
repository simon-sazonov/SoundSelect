"""Reading the notes with homr, handing it the staff positions the stitching already found.

homr's own staff finder is slower and misses staves in small video pictures (82% of notes
right at 480p against 94% with our positions), and its ``--read-staff-positions`` option
crashes in 0.7, so its note reader is called directly here.

homr is AGPL-3.0, which is fine for personal use. It downloads its models (about 300 MB) the
first time it runs.
"""

from __future__ import annotations

import contextlib
import io
import threading
from collections.abc import Sequence

import cv2
import numpy as np

from .staves import Image
from .stitch import PageStaff

_lock = threading.Lock()  # homr keeps its models in module globals


class OmrUnavailable(RuntimeError):
    """homr isn't installed."""


def omr_available() -> bool:
    try:
        import homr  # noqa: F401
    except ImportError:
        return False
    return True


def prepare_models() -> None:
    """Download homr's models now instead of during the first piece (needs the internet)."""
    from homr.main import download_weights

    download_weights(False, False, False)


def read_page(page: Image, staves: Sequence[PageStaff]) -> str:
    """The notes on one clean-copy page as MusicXML (one part per system shape), read staff by
    staff at the given positions. Staves of one system are read together as one grand staff."""
    try:
        from homr.color_adjust import apply_clahe
        from homr.debug import Debug
        from homr.model import MultiStaff, Staff, StaffPoint
        from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
        from homr.resize import resize_image
        from homr.staff_parsing import parse_staffs
        from homr.transformer.configs import Config
    except ImportError as exc:
        raise OmrUnavailable(
            "Reading notes needs homr. Install the sheet music tools: uv sync --extra sheetmusic"
        ) from exc

    raw = cv2.cvtColor(page, cv2.COLOR_GRAY2BGR) if page.ndim == 2 else page
    image = resize_image(raw)
    fy, fx = image.shape[0] / raw.shape[0], image.shape[1] / raw.shape[1]

    systems: dict[int, list[PageStaff]] = {}
    for st in staves:
        systems.setdefault(st.system, []).append(st)
    multi = []
    for _, group in sorted(systems.items()):
        parts = []
        for st in sorted(group, key=lambda s: s.box.y0):
            b = st.box
            x0, x1 = b.x0 * fx, b.x1 * fx
            y0, y1 = b.y0 * fy, b.y1 * fy
            ys = [y0 + i * (y1 - y0) / 4 for i in range(5)]
            points = [StaffPoint(float(x), list(ys), 0) for x in np.arange(x0, x1, 10.0)]
            parts.append(Staff(points))
        multi.append(MultiStaff(parts, []))

    # homr prints its progress for every staff; keep the app's console readable
    quiet = io.StringIO()
    with _lock, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        prepare_models()
        config = Config()
        config.use_gpu_inference = False
        debug = Debug(image, "page.png", False)
        result = parse_staffs(debug, multi, apply_clahe(image), config=config, selected_staff=-1)
        xml = generate_xml(XmlGeneratorArguments(False, None, None), result, "")
        return xml.to_string()
