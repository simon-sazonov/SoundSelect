"""How an import becomes jobs: what each pasted text, file and link is, and which tool reads it.

Each item becomes one song. Kinds of input that a later phase reads (photos, audio, video,
links) are accepted now and get a job that says it can't be read yet, so the front end handles
every kind the same way and nothing in the API changes when the readers arrive.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

from pydantic import Field

from .core.song import Corrections, Model
from .sheets.readers import PDF_SUFFIXES, PHOTO_SUFFIXES, TEXT_SUFFIXES

InputKind = Literal["text", "pdf", "photo", "audio", "video", "link"]
JobKind = Literal["chord_sheet", "sheet_music", "song"]
LinkMode = Literal["auto", "sound", "sheet_music"]

AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".oga", ".opus", ".aac", ".aif", ".aiff"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"II*\x00", b"MM\x00*")

NOT_YET: dict[str, str] = {
    "photo": "Photos can't be read yet: photo reading is the next build phase.",
    "audio": "Songs from audio files come in a later build phase.",
    "video": "Sheet music videos come in a later build phase.",
    "link": "Links (YouTube and others) come in a later build phase.",
    "group": "Stacking several files into one song comes with photo reading.",
}


class InputRef(Model):
    """One input of a job, as stored in the library."""

    kind: InputKind
    name: str | None = Field(None, description="File name, when the input was a file.")
    sha: str | None = Field(None, description="SHA-256 of the stored bytes (files, pasted text).")
    size: int | None = Field(None, description="Size in bytes.")
    url: str | None = Field(None, description="The link, for links.")


class ImportOptions(Model):
    """Options for one import. Title, artist, key and capo apply when it holds one song."""

    instrument: str | None = Field(
        None, description="Instrument to write for; empty means your default."
    )
    title: str | None = None
    artist: str | None = None
    key: str | None = Field(None, description="The concert key, when you know it: 'Bb', 'Gm'.")
    capo: int | None = Field(None, ge=0, le=12)
    groups: list[list[int]] | None = Field(
        None,
        description="Files that together make one song, as lists of file positions (from 0); "
        "for photos of a song that runs over two pages. Read from the photo phase on.",
    )
    link_mode: LinkMode = Field(
        "auto",
        description="Whether a link is read for its sound (song tool) or the sheet music it "
        "shows. Read from the phases that add links.",
    )

    def corrections(self) -> Corrections:
        return Corrections(title=self.title, artist=self.artist, key=self.key, capo=self.capo)

    @property
    def has_corrections(self) -> bool:
        return any(v is not None for v in (self.title, self.artist, self.key, self.capo))


@dataclass(frozen=True)
class Unreadable:
    """A file nothing can read, with the reason."""

    name: str
    message: str


@dataclass
class JobPlan:
    """One song to make: its inputs, the tool that reads them, or why nothing can yet."""

    inputs: list[InputRef]
    name: str
    kind: JobKind | None
    not_yet: str | None = None


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    for encoding in ("utf-8", "cp1251"):
        try:
            head.decode(encoding)
            return True
        except UnicodeDecodeError as exc:
            if encoding == "utf-8" and exc.start >= len(head) - 3:
                return True  # a character cut off at the end of the sample
    return False


def file_kind(name: str | None, head: bytes) -> InputKind | None:
    """What a file is, from its name and first bytes; None when nothing can read it."""
    suffix = PurePath(name or "").suffix.lower()
    if head.startswith(b"%PDF-") or suffix in PDF_SUFFIXES:
        return "pdf"
    if suffix in PHOTO_SUFFIXES or head.startswith(_IMAGE_MAGIC):
        return "photo"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in TEXT_SUFFIXES and _looks_like_text(head):
        return "text"
    return None


def unreadable_message(name: str | None) -> str:
    suffix = PurePath(name or "").suffix.lower()
    what = f"{suffix} files" if suffix else "this kind of file"
    return f"SoundSelect can't read {what}. Save the sheet as a PDF or plain text."


def text_name(text: str) -> str:
    """A short name for pasted text: its first line."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return "Pasted text"
    return first if len(first) <= 60 else first[:57].rstrip() + "..."


def job_kind(kind: InputKind) -> JobKind | None:
    return "chord_sheet" if kind in ("text", "pdf") else None


def plan_jobs(
    texts: list[InputRef],
    files: list[InputRef | Unreadable],
    links: list[InputRef],
    groups: list[list[int]] | None = None,
) -> list[JobPlan]:
    """One job per song, in the order given: pasted texts, then files, then links.

    ``files`` holds an InputRef for each file, or why nothing can read it.
    ``groups`` stacks files into one song (from the photo phase on); a file in no group is
    a song of its own.
    """
    plans: list[JobPlan] = [JobPlan([t], t.name or "Pasted text", "chord_sheet") for t in texts]

    grouped: dict[int, list[int]] = {}
    for group in groups or []:
        if len(group) > 1:
            for i in group:
                grouped[i] = group
    done: set[int] = set()
    for i, f in enumerate(files):
        if i in done:
            continue
        group = grouped.get(i)
        if group:
            done.update(group)
            refs = [r for r in (files[j] for j in group) if isinstance(r, InputRef)]
            names = ", ".join(r.name or "file" for r in refs)
            plans.append(JobPlan(refs, names, None, NOT_YET["group"]))
            continue
        if isinstance(f, Unreadable):
            plans.append(JobPlan([], f.name, None, f.message))
            continue
        kind = job_kind(f.kind)
        plans.append(JobPlan([f], f.name or "File", kind, None if kind else NOT_YET[f.kind]))

    for link in links:
        plans.append(JobPlan([link], link.url or "Link", None, NOT_YET["link"]))
    return plans


def check_groups(groups: list[list[int]] | None, n_files: int) -> str | None:
    """Why the groups don't fit the files, or None when they do."""
    seen: set[int] = set()
    for group in groups or []:
        for i in group:
            if not 0 <= i < n_files:
                return f"group refers to file {i}, but there are {n_files} files"
            if i in seen:
                return f"file {i} is in two groups"
            seen.add(i)
    return None
