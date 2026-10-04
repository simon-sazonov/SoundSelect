"""The web app: the API under ``/api/v1``, the simple screens, and the job workers.

``soundselect serve`` runs it on this computer only (localhost). Workers run as threads inside
it unless told to run apart (``--workers 0`` with ``soundselect worker``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from ..jobs import JobQueue
from ..store import Library
from .errors import add_error_handlers
from .routes import router

# Where the front end runs while it's being built (Vite's dev server)
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

DESCRIPTION = """
SoundSelect's back end. Every screen talks to it through these calls.

Songs come back as the **Song result** (see the `Song` schema): concert pitch and written for
the instrument, with the key's pentatonic first. Errors come as
`{"detail": {"code": ..., "message": ...}}`, with a message that can be shown as it is.
"""


def create_app(
    home: str | os.PathLike[str] | None = None,
    *,
    workers: int = 0,
    immediate: bool = False,
    screens: bool = True,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    """The app for the library in ``home``. ``workers`` worker threads run jobs inside the
    app; ``immediate`` runs each job at once instead, before the request returns (tests)."""
    library = Library(home)
    queue = JobQueue(library, immediate=immediate)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        queue.start(workers)
        try:
            yield
        finally:
            queue.stop()

    app = FastAPI(
        title="SoundSelect",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.library = library
    app.state.queue = queue
    add_error_handlers(app)
    app.include_router(router, prefix="/api/v1")

    origins = cors_origins
    if origins is None:
        extra = os.environ.get("SOUNDSELECT_CORS_ORIGINS", "")
        origins = DEV_ORIGINS + [o.strip() for o in extra.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    if screens:
        from ..web import add_screens

        add_screens(app)
    return app


def openapi_json(app: FastAPI | None = None) -> str:
    """The API description, as kept in docs/openapi.json."""
    import json
    import tempfile

    if app is None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Path(tmp), screens=False, cors_origins=[])
            spec = app.openapi()
    else:
        spec = app.openapi()
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"
