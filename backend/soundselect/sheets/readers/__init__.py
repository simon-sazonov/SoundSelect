"""Reader plug-ins: each turns one kind of input into lines of text with their positions.

Adding a source means adding one reader here and nothing else. Text arrives in Phase 0, PDF in
Phase 1 and photos (with groups of several files that make one song) in Phase 2.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath

from ..model import SheetText

TEXT_SUFFIXES = {".txt", ".text", ".cho", ".chopro", ".chordpro", ".crd", ".pro", ".md", ""}
PDF_SUFFIXES = {".pdf"}
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}


class UnsupportedInput(ValueError):
    """The input type has no reader yet."""


@dataclass(frozen=True)
class SheetInput:
    """One sheet to read: pasted text, or a file's bytes with its name."""

    data: str | bytes
    name: str | None = None
    kind: str | None = None
    parts: tuple[SheetInput, ...] = ()  # a group: inputs that make one song together

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> SheetInput:
        p = Path(path)
        return cls(p.read_bytes(), p.name)

    @property
    def raw(self) -> bytes:
        if self.parts:  # a group is known by what its parts contain, in order
            return b"".join(hashlib.sha256(p.raw).digest() for p in self.parts)
        return self.data.encode("utf-8") if isinstance(self.data, str) else self.data

    def fingerprint(self, reader_kind: str) -> str:
        """The song's identity: the same contents under another name is the same song."""
        h = hashlib.sha256()
        h.update(reader_kind.encode())
        h.update(b"\0")
        h.update(self.raw)
        return h.hexdigest()

    def cache_key(self) -> str:
        """What saved step results are keyed on: the contents, and also the name and kind,
        since the name becomes the title when the sheet has none."""
        h = hashlib.sha256()
        for part in (self.kind or "", self.name or ""):
            h.update(part.encode())
            h.update(b"\0")
        h.update(self.raw)
        return h.hexdigest()


def detect_kind(inp: SheetInput) -> str:
    if inp.kind:
        return inp.kind
    if isinstance(inp.data, str):
        return "text"
    suffix = PurePath(inp.name or "").suffix.lower()
    if suffix in PDF_SUFFIXES or inp.data[:5] == b"%PDF-":
        return "pdf"
    if suffix in PHOTO_SUFFIXES:
        return "photo"
    if suffix in TEXT_SUFFIXES:
        return "text"
    raise UnsupportedInput(f"can't tell what kind of sheet {inp.name!r} is")


Reader = Callable[[SheetInput], SheetText]
READERS: dict[str, Reader] = {}


def register(kind: str) -> Callable[[Reader], Reader]:
    def add(fn: Reader) -> Reader:
        READERS[kind] = fn
        return fn

    return add


def read_sheet(inp: SheetInput) -> SheetText:
    kind = detect_kind(inp)
    reader = READERS.get(kind)
    if reader is None:
        raise UnsupportedInput(f"reading {kind} sheets is not built yet")
    return reader(inp)


from . import pdf, photo, text  # noqa: E402,F401  (registers the readers)
