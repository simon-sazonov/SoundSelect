"""Phase 3: sheet music from screenshots or a video, stitched in order and re-engraved as one PDF.

Importing this package only registers the pipeline; OpenCV, homr, RapidOCR and music21 load
when a piece is read. Research and test results: research/sheet-video-to-pdf in the project
files.
"""

from __future__ import annotations


def _register() -> None:
    from ..pipeline import registry

    register = getattr(registry, "register_pipeline", None)
    if register is not None:  # the registry hook lands with the shared Phase 2/3 changes
        from .spec import make_spec

        register(make_spec())


_register()
