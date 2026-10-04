"""Downloading with yt-dlp, the picture or the sound of a link, into a folder."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Want = Literal["video", "audio"]

# Picture only, no sound, one file (no merging, so ffmpeg is not needed): mp4 up to 1080p.
VIDEO_FORMAT = (
    "bestvideo[height<=1080][ext=mp4][vcodec^=avc1]/bestvideo[height<=1080][ext=mp4]/"
    "bestvideo[height<=1080]/best[height<=1080]/best"
)
AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio/best"
MAX_SECONDS = 60 * 60


class LinkError(ValueError):
    """The link can't be fetched; the message says why, in words for the player."""


@dataclass(frozen=True)
class LinkInfo:
    url: str
    id: str | None
    title: str | None
    uploader: str | None
    duration: float | None
    path: Path | None = None  # the downloaded file, once downloaded


def links_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def _yt_dlp() -> Any:
    try:
        import yt_dlp
    except ImportError as exc:
        raise LinkError(
            "Links need yt-dlp. Install the sheet music tools: uv sync --extra sheetmusic"
        ) from exc
    return yt_dlp


def _check_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        raise LinkError(f"{url!r} isn't a web link (it should start with https://).")
    return url


def _options(**extra: Any) -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        **extra,
    }


def _explain(exc: Exception) -> LinkError:
    text = str(exc)
    if "Sign in to confirm" in text or "not a bot" in text:
        why = "YouTube asked to confirm this isn't a bot; this works best from a home connection"
    elif "Private video" in text or "unavailable" in text.lower():
        why = "the video is private or no longer available"
    elif "Unsupported URL" in text:
        why = "this site isn't supported"
    else:
        why = re.sub(r"^ERROR:\s*", "", text.strip().splitlines()[-1] if text.strip() else "")
        why = why[:200] or type(exc).__name__
    return LinkError(f"The link couldn't be fetched: {why}.")


def _info(raw: dict[str, Any], url: str, path: Path | None = None) -> LinkInfo:
    duration = raw.get("duration")
    return LinkInfo(
        url=url,
        id=raw.get("id"),
        title=raw.get("title"),
        uploader=raw.get("uploader") or raw.get("channel"),
        duration=float(duration) if duration else None,
        path=path,
    )


def info(url: str) -> LinkInfo:
    """What a link points at, without downloading it."""
    url = _check_url(url)
    yt_dlp = _yt_dlp()
    try:
        with yt_dlp.YoutubeDL(_options(skip_download=True)) as ydl:
            raw = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise _explain(exc) from exc
    return _info(raw or {}, url)


def download(url: str, folder: str | os.PathLike[str], want: Want = "video") -> LinkInfo:
    """Download a link's picture (``video``, no sound) or sound (``audio``) into ``folder``."""
    url = _check_url(url)
    yt_dlp = _yt_dlp()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)

    def too_long(raw: dict[str, Any], *, incomplete: bool) -> str | None:
        duration = raw.get("duration")
        if duration and duration > MAX_SECONDS:
            return "longer than an hour"
        return None

    opts = _options(
        format=VIDEO_FORMAT if want == "video" else AUDIO_FORMAT,
        outtmpl=str(folder / f"{want}.%(ext)s"),
        match_filter=too_long,
        overwrites=True,
    )
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise _explain(exc) from exc
    if raw is None:
        raise LinkError("The link couldn't be fetched: it is longer than an hour.")
    files = sorted(p for p in folder.glob(f"{want}.*") if not p.name.endswith(".part"))
    if not files:
        raise LinkError("The link couldn't be fetched: the download came back empty.")
    return _info(raw, url, files[0])
