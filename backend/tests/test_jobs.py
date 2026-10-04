"""Jobs: making a song step by step, reusing songs already made, failing in words."""

import dataclasses
import time

import pytest

from soundselect import service
from soundselect.imports import ImportOptions
from soundselect.jobs import JobQueue, run_job
from soundselect.pipeline import registry


def import_one(lib, text=None, files=None, **options):
    batch = service.start_import(
        lib,
        texts=[text] if text else None,
        files=files,
        options=ImportOptions(**options),
    )
    return batch.jobs[0]


def test_job_makes_a_song(library, sheet_text):
    job = import_one(library, sheet_text)
    run_job(library, job.id)
    done = library.job(job.id)
    assert (done.status, done.progress, done.step, done.reused) == ("done", 1.0, None, False)
    assert done.step_count == 7 and done.started_at and done.finished_at
    song = service.stored_song(library, done.song_id)
    assert song.identity.title == "I Found a Love"
    assert song.view.written_key.tonic == "G"  # alto sax, the default
    run_job(library, job.id)  # a job queued twice runs once
    assert library.count_songs() == 1


def test_steps_are_reported(library, sheet_text, monkeypatch):
    job = import_one(library, sheet_text)
    seen = []
    update = library.update_job

    def spy(job_id, **fields):
        if fields.get("step_label"):
            seen.append(fields["step_label"])
        update(job_id, **fields)

    monkeypatch.setattr(library, "update_job", spy)
    run_job(library, job.id)
    assert seen[0] == "Reading the sheet" and seen[-1] == "Writing it for your instrument"
    assert len(seen) == 7


def test_same_sheet_twice_is_reused(library, sheet_text):
    first = import_one(library, sheet_text)
    run_job(library, first.id)
    again = import_one(library, sheet_text)
    run_job(library, again.id)
    job = library.job(again.id)
    assert job.reused and job.song_id == library.job(first.id).song_id
    # with a correction it is a song of its own
    fixed = import_one(library, sheet_text, key="C")
    run_job(library, fixed.id)
    assert not library.job(fixed.id).reused
    assert library.count_songs() == 2


def test_options_reach_the_song(library, sheet_text):
    job = import_one(library, sheet_text, instrument="tenor_sax", title="Mine", key="C", capo=0)
    run_job(library, job.id)
    song = service.stored_song(library, library.job(job.id).song_id)
    assert song.identity.title == "Mine"
    assert song.key.concert.tonic == "C" and song.key.basis == "correction"
    assert song.view.instrument == "tenor_sax" and song.view.written_key.tonic == "D"


def test_failures_are_explained(library, data_dir, monkeypatch):
    job = import_one(library, files=[("scan.jpg", b"\xff\xd8\xff not really a photo")])
    run_job(library, job.id)
    failed = library.job(job.id)
    assert failed.status == "failed"
    assert failed.error == "This file isn't a picture that can be opened."

    def broken(*args, **kwargs):
        raise ZeroDivisionError("division by zero")

    spec = dataclasses.replace(registry.CHORD_SHEET_SPEC, make=broken)
    monkeypatch.setitem(registry.PIPELINES, "chord_sheet", spec)
    job = import_one(library, "Am C G\nSome words")
    run_job(library, job.id)
    failed = library.job(job.id)
    assert failed.status == "failed"
    assert failed.error == (
        "Something went wrong reading this (ZeroDivisionError: division by zero)."
    )


def test_immediate_queue(library, sheet_text):
    queue = JobQueue(library, immediate=True)
    job = import_one(library, sheet_text)
    queue.enqueue([job.id])
    assert library.job(job.id).status == "done"
    assert queue.running


def wait_for(check, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_worker_threads(library, sheet_text, data_dir):
    queue = JobQueue(library)
    pdf = (data_dir / "pdf" / "two_columns.pdf").read_bytes()
    jobs = [import_one(library, sheet_text), import_one(library, files=[("song.pdf", pdf)])]
    queue.enqueue([j.id for j in jobs])  # queued before the workers start: they wait
    assert library.job(jobs[0].id).status == "queued" and not queue.running
    queue.start(2)
    try:
        assert queue.running
        assert wait_for(lambda: all(library.job(j.id).status == "done" for j in jobs))
    finally:
        queue.stop()
    assert not queue.running


def test_interrupted_jobs_go_back_in_the_queue(library, sheet_text):
    job = import_one(library, sheet_text)
    library.update_job(job.id, status="running", step="key", step_label="Finding the key")
    queue = JobQueue(library, immediate=True)
    assert queue.recover() == 1
    assert library.job(job.id).status == "done"


@pytest.mark.parametrize("workers", [0, -1])
def test_no_workers(library, workers):
    queue = JobQueue(library)
    queue.start(workers)
    assert not queue.running


def test_queued_job_missing_from_the_queue_runs_on_start(library, sheet_text):
    """A batch saved but never put in the queue (the app stopped in between) still runs."""
    job = import_one(library, sheet_text)  # saved as queued, never enqueued
    queue = JobQueue(library)
    queue.start(1)
    try:
        assert wait_for(lambda: library.job(job.id).status == "done")
    finally:
        queue.stop()


def test_same_sheet_twice_at_once_makes_one_song(library, sheet_text):
    """Two workers given the same sheet at the same time: one song, the other job reuses it."""
    import threading

    jobs = [import_one(library, sheet_text), import_one(library, sheet_text)]
    start = threading.Barrier(2)

    def work(job_id):
        start.wait()
        run_job(library, job_id)

    threads = [threading.Thread(target=work, args=(j.id,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    done = [library.job(j.id) for j in jobs]
    assert library.count_songs() == 1
    assert [d.status for d in done] == ["done", "done"]
    assert sorted(d.reused for d in done) == [False, True]
    assert done[0].song_id == done[1].song_id


def test_add_song_once(library, found_a_love):
    first, reused = library.add_song_once(found_a_love, pipeline="chord_sheet", inputs=[])
    assert not reused
    again, reused = library.add_song_once(found_a_love, pipeline="chord_sheet", inputs=[])
    assert (again, reused) == (first, True)
    assert library.count_songs() == 1
