"""Running one job: make its song with the right pipeline, reporting each step as it goes.

A failed job says why in words for the player and never stops the rest of its batch.
"""

from __future__ import annotations

import logging

from ..pipeline.registry import get_pipeline
from ..sheets.readers import UnsupportedInput
from ..store import Library
from ..store.db import now

log = logging.getLogger("soundselect.jobs")


def run_job(lib: Library, job_id: str) -> None:
    job = lib.job(job_id)
    if job is None or job.kind is None:
        return  # gone, or nothing reads it
    spec = get_pipeline(job.kind)
    claimed = lib.claim_job(
        job_id,
        started_at=now(),
        step=None,
        step_label=None,
        step_number=0,
        step_count=len(spec.pipeline.steps),
        progress=0.0,
    )
    if not claimed:
        return  # finished already, or another worker has it (a job queued twice runs once)
    options = lib.job_options(job_id)

    def on_step(name: str, phase: str, number: int, total: int) -> None:
        if phase == "start":
            lib.update_job(
                job_id,
                step=name,
                step_label=spec.label(name),
                step_number=number,
                step_count=total,
                progress=round((number - 1) / total, 3),
            )

    def finish(song_id: str, *, reused: bool = False) -> None:
        lib.update_job(
            job_id,
            status="done",
            song_id=song_id,
            reused=reused,
            step=None,
            step_label=None,
            progress=1.0,
            finished_at=now(),
        )

    try:
        if not options.has_corrections:
            existing = lib.find_song(spec.fingerprint(job.inputs, lib.read_input))
            if existing is not None:
                finish(existing, reused=True)
                return
        song = spec.analyze(
            job.inputs,
            lib.read_input,
            corrections=options.corrections(),
            view=lib.settings().view(options.instrument),
            cache=lib.cache,
            on_step=on_step,
        )
        song = lib.add_song(song, pipeline=spec.name, inputs=job.inputs)
        assert song.id is not None
        finish(song.id)
    except UnsupportedInput as exc:
        _fail(lib, job_id, str(exc))
    except Exception as exc:
        log.exception("job %s failed", job_id)
        detail = f"{type(exc).__name__}: {exc}"
        _fail(lib, job_id, f"Something went wrong reading this ({detail[:200]}).")


def _fail(lib: Library, job_id: str, message: str) -> None:
    text = message[:1].upper() + message[1:]
    lib.update_job(
        job_id, status="failed", error=text, step=None, step_label=None, finished_at=now()
    )
