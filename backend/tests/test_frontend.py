"""The front end in frontend/: every screen address gets its page, and its files are served."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from soundselect.api import create_app

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOUNDSELECT_FRONTEND", str(FRONTEND))
    with TestClient(
        create_app(tmp_path / "library", immediate=True, allowed_hosts=["testserver"])
    ) as c:
        yield c


@pytest.mark.parametrize(
    "path",
    ["/", "/import", "/library", "/settings", "/batches/abc", "/songs/abc", "/songs/abc/stand"],
)
def test_every_screen_is_the_app(app_client, path):
    res = app_client.get(path)
    assert res.status_code == 200
    assert '<script type="module" src="/app/app.js">' in res.text


@pytest.mark.parametrize(
    "path",
    [
        "/app/app.js",
        "/app/music.js",
        "/app/api.js",
        "/app/art.js",
        "/app/styles.css",
        "/app/fonts/fonts.css",
        "/app/fonts/jost-latin.woff2",
        "/app/manifest.webmanifest",
        "/sw.js",
    ],
)
def test_files(app_client, path):
    assert app_client.get(path).status_code == 200


def test_music_font(app_client):
    res = app_client.get("/music-font.css")
    assert res.status_code == 200 and "Leipzig" in res.text


def test_api_still_answers(app_client):
    assert app_client.get("/api/v1/health").json()["status"] == "ok"


def test_off_serves_the_simple_screens(tmp_path, monkeypatch):
    monkeypatch.setenv("SOUNDSELECT_FRONTEND", "off")
    with TestClient(create_app(tmp_path, immediate=True, allowed_hosts=["testserver"])) as c:
        assert "/app/app.js" not in c.get("/").text
