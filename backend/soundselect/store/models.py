"""What the library hands out: jobs, batches and song summaries, as the API shows them."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ..core.song import KeyName, Model, SourceKind
from ..imports import ImportOptions, InputRef, JobKind

JobStatus = Literal["queued", "running", "done", "failed"]
FINISHED: tuple[JobStatus, ...] = ("done", "failed")


class JobInfo(Model):
    """One song being made: which step it is on, and the song once it's ready."""

    id: str
    batch_id: str
    position: int = Field(description="Place in the batch, from 0.")
    name: str = Field(description="File name, link, or the first line of pasted text.")
    kind: JobKind | None = Field(description="The tool that reads it; null when none can yet.")
    inputs: list[InputRef]
    status: JobStatus
    step: str | None = Field(None, description="The step running now, e.g. 'key'.")
    step_label: str | None = Field(None, description="That step in words: 'Finding the key'.")
    step_number: int = Field(0, description="The running step's number, from 1.")
    step_count: int = 0
    progress: float = Field(0.0, description="0 to 1.")
    song_id: str | None = None
    reused: bool = Field(False, description="The song was already in the library.")
    error: str | None = Field(None, description="Why it failed, in words for the player.")
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    rev: int = Field(description="Goes up with every change; the event streams use it.")

    @property
    def finished(self) -> bool:
        return self.status in FINISHED


class BatchInfo(Model):
    """One import: a job for each song, filled in song by song."""

    id: str
    created_at: datetime
    status: Literal["working", "done"] = Field(
        description="'done' once every job has finished, even when some failed."
    )
    total: int
    done: int
    failed: int
    options: ImportOptions
    jobs: list[JobInfo]


class SongSummary(Model):
    """A song in the library list."""

    id: str
    title: str | None
    artist: str | None
    source: SourceKind
    source_name: str | None
    key: KeyName | None = Field(description="Concert key.")
    written_key: KeyName | None = Field(description="Key as written for the instrument.")
    instrument: str
    pentatonic: list[str] = Field(
        description="The key's pentatonic as written for the instrument, without octaves."
    )
    warnings: int = Field(description="How many notes to the player are warnings.")
    created_at: datetime
    updated_at: datetime


class SongList(Model):
    songs: list[SongSummary]
    total: int = Field(description="Songs matching the search, beyond this page too.")
