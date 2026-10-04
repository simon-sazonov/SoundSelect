"""Who may talk to the app: requests must name this computer, and changes must come from the
app's own pages (or the front end's dev server).

The app runs on this computer with no sign-in, so a web page open in the browser must not be
able to use it. Checking the Host header stops DNS rebinding (a site whose name is pointed at
127.0.0.1 to read the library). Checking the Origin of POST, PUT, PATCH and DELETE stops
another site from sending a form or a fetch that changes or deletes songs.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def host_name(host: str) -> str:
    """The name in a Host header, without the port: '[::1]:8000' gives '::1'."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host[1:]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class RequestGuard:
    """Turns away requests for another host (400) and changes from another site (403)."""

    def __init__(self, app: ASGIApp, *, hosts: Iterable[str], origins: Iterable[str]) -> None:
        self.app = app
        self.hosts = {h.strip().lower() for h in hosts}
        self.origins = {o.strip().lower().rstrip("/") for o in origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # the app has no websockets
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host = headers.get("host", "")
        if host_name(host) not in self.hosts:
            await _refuse(
                send,
                400,
                "bad_host",
                "SoundSelect only answers requests addressed to this computer "
                "(127.0.0.1 or localhost).",
            )
            return
        origin = headers.get("origin")
        if scope.get("method") in UNSAFE_METHODS and origin is not None:
            own = f"{scope.get('scheme', 'http')}://{host}".lower()
            if origin.lower().rstrip("/") not in self.origins | {own}:
                await _refuse(
                    send,
                    403,
                    "bad_origin",
                    "Changes are only accepted from SoundSelect's own pages.",
                )
                return
        await self.app(scope, receive, send)


async def _refuse(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"detail": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
