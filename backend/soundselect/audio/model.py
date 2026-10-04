"""What each song step hands to the next. Large audio stays in files (see ``files``); these
small results are what the step runner saves."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse

from pydantic import Field

from ..core.song import Model

AUDIO_VERSION = "1"  # bump when decoding changes what the stored audio holds

_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(url: str) -> str | None:
    """The video id of a YouTube or YouTube Music link, whatever form the link takes."""
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    candidate: str | None = None
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if parts.path == "/watch":
            candidate = (parse_qs(parts.query).get("v") or [None])[0]
        else:
            bits = parts.path.strip("/").split("/")
            if len(bits) >= 2 and bits[0] in ("shorts", "embed", "live", "v"):
                candidate = bits[1]
    return candidate if candidate and _YOUTUBE_ID.match(candidate) else None


@dataclass(frozen=True)
class SongSource:
    """A recording to make a song from: a stored audio file or a link."""

    kind: Literal["audio", "link"]
    data: bytes | None = None
    name: str | None = None
    url: str | None = None

    @property
    def identity(self) -> str:
        """What the recording is: its bytes for a file, the video for a link."""
        if self.kind == "audio":
            assert self.data is not None
            return "audio:" + hashlib.sha256(self.data).hexdigest()
        assert self.url is not None
        video = youtube_id(self.url)
        return f"youtube:{video}" if video else "link:" + self.url.strip()

    @property
    def fingerprint(self) -> str:
        if self.kind == "audio":
            return self.identity.removeprefix("audio:")
        return hashlib.sha256(self.identity.encode()).hexdigest()

    @property
    def folder(self) -> str:
        """The folder name for this recording's separated audio."""
        return hashlib.sha256(self.identity.encode()).hexdigest()[:32]

    def cache_key(self) -> str:
        return hashlib.sha256(self.identity.encode()).hexdigest()


class Recording(Model):
    """The recording, opened: how long it is and what it says about itself."""

    seconds: float
    title: str | None = None
    artist: str | None = None
    source_name: str | None = None
    file: str | None = Field(None, description="Downloaded file (links), in the song's folder.")


class Tuning(Model):
    cents: float = Field(description="How far the recording sits from A = 440 Hz, in cents.")
    confidence: float = 0.0


class Separation(Model):
    engine: str
    voice_share: float = Field(description="0-1: how much of the sound is the voice.")
    melody_from: Literal["voice", "mix"]


class NoteEvent(Model):
    start: float = Field(description="Seconds.")
    end: float
    pitch: int = Field(description="MIDI number, concert pitch.")
    strength: float = Field(description="0-1: how clearly the note sounds.")


class Notes(Model):
    events: list[NoteEvent] = Field(default_factory=list)


class Beats(Model):
    tempo: float | None = None
    beat_times: list[float] = Field(default_factory=list)
    downbeats: list[float] = Field(default_factory=list)
    beats_per_bar: int = 4
    chroma: list[float] = Field(
        default_factory=lambda: [0.0] * 12,
        description="How strongly each pitch class sounds in the band (C first).",
    )


class TimedNote(Model):
    pitch: int
    start: float = Field(description="Beats from the start of the first bar.")
    length: float = Field(description="Beats.")
    confidence: float


class Rhythm(Model):
    notes: list[TimedNote] = Field(default_factory=list)
    tempo: float | None = None
    time_signature: str = "4/4"
    first_bar: float = Field(0.0, description="Seconds where the first bar starts.")
