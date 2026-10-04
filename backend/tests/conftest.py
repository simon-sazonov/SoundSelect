from functools import cache
from pathlib import Path

import pytest

from soundselect.core.song import Song
from soundselect.pipeline.chord_sheet import analyze_sheet

DATA = Path(__file__).parent / "data"


@cache
def _song(name: str) -> Song:
    return analyze_sheet(DATA / name)


@pytest.fixture
def data_dir() -> Path:
    return DATA


@pytest.fixture
def found_a_love() -> Song:
    """The sample sheet, analyzed once and written for alto sax."""
    return _song("found_a_love.txt")


@pytest.fixture
def russian_song() -> Song:
    return _song("russian_h.txt")


@pytest.fixture
def sheet_text() -> str:
    """The sample sheet as pasted text."""
    return (DATA / "found_a_love.txt").read_text(encoding="utf-8")


@pytest.fixture
def library(tmp_path):
    """An empty library in a folder of its own."""
    from soundselect.store import Library

    return Library(tmp_path / "library")


@pytest.fixture
def client(tmp_path):
    """The web app on an empty library; each job runs at once, inside the request."""
    from fastapi.testclient import TestClient

    from soundselect.api import create_app

    with TestClient(
        create_app(tmp_path / "library", immediate=True, allowed_hosts=["testserver"])
    ) as test_client:
        yield test_client


@pytest.fixture
def without_song(monkeypatch):
    """The app as it is without the song tool (Phase 4), for tests of what isn't built yet."""
    from soundselect.pipeline import registry

    monkeypatch.delitem(registry.PIPELINES, "song", raising=False)


@pytest.fixture
def without_sheet_music(monkeypatch):
    """The app as it is without the sheet music tool (Phase 3), for tests of what isn't built."""
    from soundselect.pipeline import registry

    monkeypatch.delitem(registry.PIPELINES, "sheet_music", raising=False)
