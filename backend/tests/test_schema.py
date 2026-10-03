import json
from pathlib import Path

from soundselect.core.song import Song

SCHEMA = Path(__file__).parents[2] / "docs" / "song.schema.json"


def test_schema_file_is_up_to_date():
    """docs/song.schema.json is the contract for the front end; regenerate it with
    ``uv run soundselect schema --out docs/song.schema.json`` after changing the Song model."""
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == Song.model_json_schema()
