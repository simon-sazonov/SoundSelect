"""The library database: one SQLite file, shared by the web app and the job workers.

Each call opens its own short connection, so threads and processes never share one. The file
runs in WAL mode, so reading never waits for a job that is writing.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any


def _from_lyrics(title: str, song: Any) -> bool:
    """Whether a title was taken from one of the song's lyric lines (by an earlier version)."""
    part = title.removesuffix("…")
    return any(part in re.sub(r"\s+", " ", line.lyrics) for s in song.form for line in s.lines)


def _name_untitled_sheets(conn: sqlite3.Connection) -> None:
    """Chord sheets saved under their file name (or a lyric line an earlier version took)
    get their first line of words as the title, as new imports do; a title the player typed
    is kept."""
    from ..core.song import Corrections, Song
    from ..sheets.analyze import first_line_title

    rows = conn.execute(
        "SELECT id, title, source_name, corrections, song FROM songs WHERE pipeline = ?",
        ("chord_sheet",),
    ).fetchall()
    for row in rows:
        try:
            song = Song.model_validate_json(row["song"])
            typed = Corrections.model_validate_json(row["corrections"]).title
        except ValueError:
            continue  # saved in a shape this version can't load; it is made again when opened
        stem = PurePath(row["source_name"]).stem if row["source_name"] else None
        title = row["title"]
        if typed or not (title in (None, stem) or _from_lyrics(title, song)):
            continue
        new = first_line_title(song.form) or stem
        if not new or new == title:
            continue
        song.identity.title = new
        conn.execute(
            "UPDATE songs SET title = ?, sort_title = ?, song = ? WHERE id = ?",
            (new, new.casefold(), song.model_dump_json(), row["id"]),
        )


# Each entry moves the database one version up; a new version only ever adds an entry.
# An entry is SQL, or a function for changes SQL can't make.
MIGRATIONS: list[str | Callable[[sqlite3.Connection], None]] = [
    """
    CREATE TABLE inputs (
        sha TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        name TEXT,
        size INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE batches (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        options TEXT NOT NULL
    );
    CREATE TABLE jobs (
        id TEXT PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        name TEXT NOT NULL,
        kind TEXT,
        inputs TEXT NOT NULL,
        options TEXT NOT NULL,
        status TEXT NOT NULL,
        step TEXT,
        step_label TEXT,
        step_number INTEGER NOT NULL DEFAULT 0,
        step_count INTEGER NOT NULL DEFAULT 0,
        progress REAL NOT NULL DEFAULT 0,
        song_id TEXT,
        reused INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        rev INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX jobs_batch ON jobs(batch_id, position);
    CREATE INDEX jobs_status ON jobs(status);
    CREATE TABLE songs (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        pipeline TEXT NOT NULL,
        inputs TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        title TEXT,
        artist TEXT,
        sort_title TEXT NOT NULL,
        source TEXT NOT NULL,
        source_name TEXT,
        key TEXT,
        warnings INTEGER NOT NULL DEFAULT 0,
        search TEXT NOT NULL,
        corrections TEXT NOT NULL,
        song TEXT NOT NULL
    );
    CREATE INDEX songs_fingerprint ON songs(fingerprint);
    CREATE INDEX songs_updated ON songs(updated_at);
    CREATE TABLE step_outputs (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        value TEXT NOT NULL
    );
    """,
    _name_untitled_sheets,
    _name_untitled_sheets,  # again, now passing over lines that are noise
    _name_untitled_sheets,  # again, passing over lines with chords or labels mixed in
]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """A write transaction that takes the write lock at once, so it never has to retry."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(path: Path) -> int:
    """Create or upgrade the database; returns its version."""
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        with transaction(conn):
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise RuntimeError(
                    f"The library at {path} was made by a newer SoundSelect; update SoundSelect."
                )
            for number in range(version, len(MIGRATIONS)):
                step = MIGRATIONS[number]
                if callable(step):
                    step(conn)
                    continue
                for statement in _statements(step):
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")
        return len(MIGRATIONS)


def _statements(script: str) -> list[str]:
    """Split a migration into statements (executescript would commit the transaction)."""
    return [s.strip() for s in script.split(";") if s.strip()]
