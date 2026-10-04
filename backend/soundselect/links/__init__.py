"""Links: fetching a video's picture or sound with yt-dlp, shared by the sheet music tool
(Phase 3) and the song tool (Phase 4).

YouTube needs a JavaScript runtime for yt-dlp since 2025.11 (Deno, installed with the
``yt-dlp[default]`` extra's helpers or on its own). Home internet addresses work best;
YouTube often blocks data-centre ones.
"""

from .download import LinkError, LinkInfo, download, info, links_available

__all__ = ["LinkError", "LinkInfo", "download", "info", "links_available"]
