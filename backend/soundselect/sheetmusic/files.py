"""Pictures the sheet music steps make (video views, clean-copy pages), kept once each by their
SHA-256 in the library folder, so a saved step output can point at them by name."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path


class MissingFile(FileNotFoundError):
    """A picture a saved step output points at is gone (the library folder was cleaned)."""


class FileStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def cache_key(self) -> str:
        # Where pictures are kept doesn't change what a step makes from them.
        return "sheetmusic-files"

    def path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha

    def put(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self.path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{sha}.{secrets.token_hex(4)}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return sha

    def get(self, sha: str) -> bytes:
        try:
            return self.path(sha).read_bytes()
        except FileNotFoundError:
            raise MissingFile(f"picture {sha[:12]} is missing from the library folder") from None

    def has(self, sha: str) -> bool:
        return self.path(sha).exists()

    def index_path(self, name: str) -> Path:
        return self.root / "index" / f"{name}.json"

    def put_index(self, name: str, text: str) -> None:
        path = self.index_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{name}.{secrets.token_hex(4)}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def get_index(self, name: str) -> str | None:
        try:
            return self.index_path(name).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
