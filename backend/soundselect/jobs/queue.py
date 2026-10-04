"""The job queue: Huey, keeping its queue in a SQLite file in the library folder.

``soundselect serve`` runs workers as threads inside the web app, so one command starts
everything. ``soundselect worker`` runs them as a process of their own (the heavy audio worker
of Phase 4 runs this way). Jobs wait in the file, so a job queued before the app stopped runs
when it starts again. Tests run jobs at once, in the caller, with ``immediate=True``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from huey import SqliteHuey
from huey.consumer import Consumer

from ..store import Library
from .work import run_job

log = logging.getLogger("soundselect.jobs")

_LIBRARIES: dict[str, Library] = {}


def _library(home: str) -> Library:
    lib = _LIBRARIES.get(home)
    if lib is None:
        lib = _LIBRARIES[home] = Library(home)
    return lib


def _run(home: str, job_id: str) -> None:
    run_job(_library(home), job_id)


class _InProcessConsumer(Consumer):
    """Workers as threads in the web app's process; the web server keeps its own signals."""

    def _set_signal_handlers(self) -> None:
        pass


class JobQueue:
    def __init__(self, lib: Library, *, immediate: bool = False) -> None:
        self.lib = lib
        self.huey = SqliteHuey(
            "soundselect",
            filename=os.fspath(Path(lib.home) / "queue.db"),
            immediate=immediate,
            results=False,
        )
        self._task = self.huey.task(name="run_job")(_run)
        self._consumer: Consumer | None = None
        if immediate:
            _LIBRARIES[os.fspath(lib.home)] = lib

    @property
    def immediate(self) -> bool:
        return self.huey.immediate

    @property
    def running(self) -> bool:
        return self.immediate or self._consumer is not None

    def enqueue(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            self._task(os.fspath(self.lib.home), job_id)

    def recover(self) -> int:
        """Jobs left running when the app last stopped go back in the queue."""
        stuck = self.lib.jobs_with_status("running")
        for job in stuck:
            self.lib.update_job(job.id, status="queued", step=None, step_label=None, progress=0.0)
        self.enqueue([job.id for job in stuck])
        return len(stuck)

    def _consumer_options(self, workers: int) -> dict:
        return {
            "workers": workers,
            "worker_type": "thread",
            "periodic": False,
            "initial_delay": 0.05,
            "backoff": 1.5,
            "max_delay": 0.5,
        }

    def start(self, workers: int = 2) -> None:
        """Start worker threads in this process."""
        if self.immediate or self._consumer is not None or workers < 1:
            return
        recovered = self.recover()
        if recovered:
            log.info("put %d interrupted job(s) back in the queue", recovered)
        self._consumer = _InProcessConsumer(self.huey, **self._consumer_options(workers))
        self._consumer.start()

    def stop(self) -> None:
        if self._consumer is not None:
            self._consumer.stop(graceful=True)
            self._consumer = None

    def run_forever(self, workers: int = 2) -> None:
        """Run workers in this process until it is stopped (``soundselect worker``)."""
        self.recover()
        self.huey.create_consumer(**self._consumer_options(workers)).run()
