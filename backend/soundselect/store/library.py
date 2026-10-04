"""The library: songs, imports and their jobs, saved step outputs and your settings.

Everything lives in one folder (``~/.soundselect`` unless ``SOUNDSELECT_HOME`` says otherwise):
the SQLite database, the inputs as they arrived (stored once, named by their SHA-256), page
images drawn from PDFs, and the job queue. Moving to the home server means copying this folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..core.song import Corrections, KeyName, Song
from ..imports import ImportOptions, InputKind, InputRef, JobPlan
from ..settings import Settings
from .db import connect, migrate, now, transaction
from .models import BatchInfo, JobInfo

DEFAULT_HOME = Path("~/.soundselect")


def default_home() -> Path:
    return Path(os.environ.get("SOUNDSELECT_HOME") or DEFAULT_HOME).expanduser()


def new_id() -> str:
    return secrets.token_hex(6)


class StepCache:
    """Saved step outputs in the library database (the step runner's cache)."""

    def __init__(self, db: Path) -> None:
        self.db = db

    def get(self, key: str) -> Any | None:
        with connect(self.db) as conn:
            row = conn.execute("SELECT value FROM step_outputs WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: Any) -> None:
        with connect(self.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO step_outputs (key, value, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), now()),
            )


@dataclass
class SongRecord:
    id: str
    pipeline: str
    inputs: list[InputRef]
    corrections: Corrections
    song: Song | None  # None when the saved result is in a shape this version can't load
    created_at: str
    updated_at: str


@dataclass
class SongRow:
    id: str
    title: str | None
    artist: str | None
    source: str
    source_name: str | None
    key: KeyName | None
    warnings: int
    created_at: str
    updated_at: str


def _search_text(song: Song) -> str:
    parts = [song.identity.title, song.identity.artist, song.identity.source_name]
    parts += [line.lyrics for line in song.lines()]
    return "\n".join(p for p in parts if p).casefold()


def _like(word: str) -> str:
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class Library:
    def __init__(self, home: str | os.PathLike[str] | None = None) -> None:
        self.home = Path(home).expanduser() if home is not None else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = self.home / "library.db"
        self.inputs_dir = self.home / "inputs"
        self.pages_dir = self.home / "pages"
        migrate(self.db)
        self.cache = StepCache(self.db)

    # Settings

    def settings(self) -> Settings:
        with connect(self.db) as conn:
            row = conn.execute("SELECT value FROM settings WHERE id = 1").fetchone()
        if row:
            try:
                return Settings.model_validate_json(row[0])
            except ValidationError:
                pass  # saved by another version; fall back to the defaults
        return Settings()

    def save_settings(self, settings: Settings) -> Settings:
        with connect(self.db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (id, value) VALUES (1, ?)",
                (settings.model_dump_json(),),
            )
        return settings

    # Inputs: stored once each, named by their SHA-256

    def input_path(self, sha: str) -> Path:
        return self.inputs_dir / sha[:2] / sha

    def store_input(self, data: bytes, kind: InputKind, name: str | None = None) -> InputRef:
        sha = hashlib.sha256(data).hexdigest()
        path = self.input_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{sha}.{secrets.token_hex(4)}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        with connect(self.db) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO inputs (sha, kind, name, size, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (sha, kind, name, len(data), now()),
            )
        return InputRef(kind=kind, name=name, sha=sha, size=len(data))

    def read_input(self, ref: InputRef) -> bytes:
        if ref.sha is None:
            raise ValueError("this input has no stored bytes")
        return self.input_path(ref.sha).read_bytes()

    # Batches and jobs

    def create_batch(self, plans: list[JobPlan], options: ImportOptions) -> BatchInfo:
        """Save an import as a batch with a job per song. Jobs nothing can read yet are failed
        at once with the reason; the others wait in the queue."""
        batch_id = new_id()
        created = now()
        # title, artist, key and capo belong to a single song, not to every song in a batch
        per_job = options if len(plans) == 1 else ImportOptions(instrument=options.instrument)
        with connect(self.db) as conn, transaction(conn):
            conn.execute(
                "INSERT INTO batches (id, created_at, options) VALUES (?, ?, ?)",
                (batch_id, created, options.model_dump_json()),
            )
            for position, plan in enumerate(plans):
                readable = plan.kind is not None and plan.not_yet is None
                conn.execute(
                    "INSERT INTO jobs (id, batch_id, position, name, kind, inputs, options, "
                    "status, error, created_at, finished_at, progress) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        new_id(),
                        batch_id,
                        position,
                        plan.name,
                        plan.kind,
                        json.dumps([r.model_dump(mode="json") for r in plan.inputs]),
                        per_job.model_dump_json(),
                        "queued" if readable else "failed",
                        None if readable else plan.not_yet,
                        created,
                        None if readable else created,
                        0.0 if readable else 1.0,
                    ),
                )
        batch = self.batch(batch_id)
        assert batch is not None
        return batch

    def batch(self, batch_id: str) -> BatchInfo | None:
        with connect(self.db) as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if row is None:
                return None
            jobs = [
                _job(r)
                for r in conn.execute(
                    "SELECT * FROM jobs WHERE batch_id = ? ORDER BY position", (batch_id,)
                )
            ]
        done = sum(1 for j in jobs if j.status == "done")
        failed = sum(1 for j in jobs if j.status == "failed")
        return BatchInfo(
            id=row["id"],
            created_at=row["created_at"],
            status="done" if done + failed == len(jobs) else "working",
            total=len(jobs),
            done=done,
            failed=failed,
            options=ImportOptions.model_validate_json(row["options"]),
            jobs=jobs,
        )

    def job(self, job_id: str) -> JobInfo | None:
        with connect(self.db) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job(row) if row else None

    def job_options(self, job_id: str) -> ImportOptions:
        with connect(self.db) as conn:
            row = conn.execute("SELECT options FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return ImportOptions.model_validate_json(row[0])

    def claim_job(self, job_id: str, **fields: Any) -> bool:
        """Mark a waiting job as running, with ``fields``; False when it isn't waiting (it
        finished already, or another worker took it first)."""
        sets = "".join(f", {k} = ?" for k in fields)
        values = [int(v) if isinstance(v, bool) else v for v in fields.values()]
        with connect(self.db) as conn:
            cur = conn.execute(
                f"UPDATE jobs SET status = 'running'{sets}, rev = rev + 1 "
                "WHERE id = ? AND status = 'queued'",
                (*values, job_id),
            )
        return cur.rowcount == 1

    def update_job(self, job_id: str, **fields: Any) -> None:
        """Change a job; every change raises its ``rev`` so the event streams send it."""
        if not fields:
            return
        names = ", ".join(f"{k} = ?" for k in fields)
        values = [int(v) if isinstance(v, bool) else v for v in fields.values()]
        with connect(self.db) as conn:
            conn.execute(f"UPDATE jobs SET {names}, rev = rev + 1 WHERE id = ?", (*values, job_id))

    def jobs_with_status(self, *statuses: str) -> list[JobInfo]:
        marks = ", ".join("?" for _ in statuses)
        with connect(self.db) as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({marks}) ORDER BY created_at, position",
                statuses,
            ).fetchall()
        return [_job(r) for r in rows]

    def job_revs(self, job_ids: list[str]) -> dict[str, int]:
        marks = ", ".join("?" for _ in job_ids)
        with connect(self.db) as conn:
            rows = conn.execute(f"SELECT id, rev FROM jobs WHERE id IN ({marks})", job_ids)
            return {r["id"]: r["rev"] for r in rows}

    # Songs

    def add_song(self, song: Song, *, pipeline: str, inputs: list[InputRef]) -> Song:
        with connect(self.db) as conn:
            return self._insert_song(conn, song, pipeline=pipeline, inputs=inputs)

    def add_song_once(
        self, song: Song, *, pipeline: str, inputs: list[InputRef]
    ) -> tuple[str, bool]:
        """Save a new song unless one was already made from the same contents. The id comes
        back, with True when it is the song already there. Checking and saving happen in one
        write transaction, so two workers given the same sheet make one song."""
        with connect(self.db) as conn, transaction(conn):
            row = conn.execute(
                "SELECT id FROM songs WHERE fingerprint = ? ORDER BY created_at LIMIT 1",
                (song.identity.fingerprint,),
            ).fetchone()
            if row is not None:
                return row[0], True
            saved = self._insert_song(conn, song, pipeline=pipeline, inputs=inputs)
        assert saved.id is not None
        return saved.id, False

    def _insert_song(
        self, conn: sqlite3.Connection, song: Song, *, pipeline: str, inputs: list[InputRef]
    ) -> Song:
        song_id = new_id()
        song = song.model_copy(update={"id": song_id})
        stamp = now()
        conn.execute(
            "INSERT INTO songs (id, created_at, updated_at, pipeline, inputs, fingerprint, "
            "title, artist, sort_title, source, source_name, key, warnings, search, "
            "corrections, song) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                song_id,
                stamp,
                stamp,
                pipeline,
                json.dumps([r.model_dump(mode="json") for r in inputs]),
                song.identity.fingerprint,
                *self._song_columns(song),
            ),
        )
        return song

    def save_song(self, song: Song) -> Song:
        """Save a recomputed song (after a correction or a refresh) under its id."""
        if song.id is None:
            raise ValueError("song has no id")
        with connect(self.db) as conn:
            cur = conn.execute(
                "UPDATE songs SET title = ?, artist = ?, sort_title = ?, source = ?, "
                "source_name = ?, key = ?, warnings = ?, search = ?, corrections = ?, song = ?, "
                "updated_at = ? WHERE id = ?",
                (*self._song_columns(song), now(), song.id),
            )
        if cur.rowcount == 0:
            raise KeyError(song.id)
        return song

    @staticmethod
    def _song_columns(song: Song) -> tuple[Any, ...]:
        ident = song.identity
        return (
            ident.title,
            ident.artist,
            (ident.title or "￿").casefold(),
            ident.source,
            ident.source_name,
            song.key.concert.model_dump_json() if song.key else None,
            sum(1 for n in song.notes if n.level == "warning"),
            _search_text(song),
            song.corrections.model_dump_json(),
            song.model_dump_json(),
        )

    def song_record(self, song_id: str) -> SongRecord | None:
        with connect(self.db) as conn:
            row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
        if row is None:
            return None
        try:
            song: Song | None = Song.model_validate_json(row["song"])
        except ValidationError:
            song = None
        return SongRecord(
            id=row["id"],
            pipeline=row["pipeline"],
            inputs=[InputRef.model_validate(r) for r in json.loads(row["inputs"])],
            corrections=Corrections.model_validate_json(row["corrections"]),
            song=song,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def find_song(self, fingerprint: str) -> str | None:
        """The song already made from these exact contents, if any."""
        with connect(self.db) as conn:
            row = conn.execute(
                "SELECT id FROM songs WHERE fingerprint = ? ORDER BY created_at LIMIT 1",
                (fingerprint,),
            ).fetchone()
        return row[0] if row else None

    def list_songs(
        self, query: str | None = None, *, sort: str = "recent", limit: int = 50, offset: int = 0
    ) -> tuple[list[SongRow], int]:
        """Songs matching every word of the query (title, artist, file name, lyrics)."""
        where, args = [], []
        for word in (query or "").casefold().split():
            where.append("search LIKE ? ESCAPE '\\'")
            args.append(_like(word))
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        order = "sort_title, updated_at DESC" if sort == "title" else "updated_at DESC"
        with connect(self.db) as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM songs {clause}", args).fetchone()[0]
            rows = conn.execute(
                f"SELECT {_ROW_COLUMNS} FROM songs {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return [_song_row(r) for r in rows], total

    def song_row(self, song_id: str) -> SongRow | None:
        with connect(self.db) as conn:
            row = conn.execute(f"SELECT {_ROW_COLUMNS} FROM songs WHERE id = ?", (song_id,))
            found = row.fetchone()
        return _song_row(found) if found else None

    def delete_song(self, song_id: str) -> bool:
        with connect(self.db) as conn:
            cur = conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
        return cur.rowcount > 0

    def count_songs(self) -> int:
        with connect(self.db) as conn:
            return conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]


def _job(row: sqlite3.Row) -> JobInfo:
    return JobInfo(
        id=row["id"],
        batch_id=row["batch_id"],
        position=row["position"],
        name=row["name"],
        kind=row["kind"],
        inputs=[InputRef.model_validate(r) for r in json.loads(row["inputs"])],
        status=row["status"],
        step=row["step"],
        step_label=row["step_label"],
        step_number=row["step_number"],
        step_count=row["step_count"],
        progress=row["progress"],
        song_id=row["song_id"],
        reused=bool(row["reused"]),
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        rev=row["rev"],
    )


_ROW_COLUMNS = "id, title, artist, source, source_name, key, warnings, created_at, updated_at"


def _song_row(row: sqlite3.Row) -> SongRow:
    return SongRow(
        id=row["id"],
        title=row["title"],
        artist=row["artist"],
        source=row["source"],
        source_name=row["source_name"],
        key=KeyName.model_validate_json(row["key"]) if row["key"] else None,
        warnings=row["warnings"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
