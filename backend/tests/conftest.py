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
