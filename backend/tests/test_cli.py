import json

from typer.testing import CliRunner

from soundselect import __version__
from soundselect.cli import app
from soundselect.core.song import Song

runner = CliRunner()


def test_sheet_summary(data_dir):
    result = runner.invoke(app, ["sheet", str(data_dir / "found_a_love.txt")])
    assert result.exit_code == 0, result.output
    assert "Key for Alto sax in E♭: соль мажор" in result.output
    assert "Your pentatonic: Major pentatonic on соль" in result.output
    assert "D/F♯" in result.output


def test_sheet_outputs(data_dir, tmp_path):
    out = tmp_path / "song.json"
    page = tmp_path / "song.html"
    xml = tmp_path / "song.musicxml"
    result = runner.invoke(
        app,
        ["sheet", str(data_dir / "found_a_love.txt"), "--json", str(out), "--html", str(page),
         "--musicxml", str(xml), "--names", "letters", "--quiet"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    song = Song.model_validate_json(out.read_text(encoding="utf-8"))
    assert song.view.written_key.tonic == "G"
    assert song.names["Bb"] == "B♭"
    assert "G major pentatonic" in page.read_text(encoding="utf-8")
    assert xml.read_text(encoding="utf-8").startswith("<?xml")


def test_batch_into_a_folder(data_dir, tmp_path):
    files = [str(data_dir / n) for n in ("found_a_love.txt", "russian_h.txt", "chord_list.txt")]
    result = runner.invoke(app, ["sheet", *files, "--out", str(tmp_path), "-f", "json,txt", "-q"])
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "chord_list.json", "chord_list.txt", "found_a_love.json", "found_a_love.txt",
        "russian_h.json", "russian_h.txt",
    ]  # fmt: skip


def test_key_and_instrument_options(data_dir):
    result = runner.invoke(
        app,
        [
            "sheet",
            str(data_dir / "found_a_love.txt"),
            "--key",
            "Gm",
            "-i",
            "tenor_sax",
            "-n",
            "letters",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Key for Tenor sax in B♭: A minor" in result.output
    assert "Concert key: G minor (2 flats), as you set it" in result.output


def test_pasted_text():
    result = runner.invoke(app, ["sheet", "-", "-n", "letters"], input="Am F C G\n")
    assert result.exit_code == 0, result.output
    assert "Untitled song" in result.output
    assert "F♯ minor pentatonic" in result.output


def test_chords_command():
    result = runner.invoke(app, ["chords", "Em", "C", "G", "D", "--concert", "-n", "letters"])
    assert result.exit_code == 0, result.output
    assert "Concert key: E minor" in result.output
    assert "Your pentatonic: E minor pentatonic" in result.output


def test_errors(data_dir, tmp_path):
    missing = runner.invoke(app, ["sheet", str(tmp_path / "nope.txt")])
    assert missing.exit_code == 1
    bad_key = runner.invoke(app, ["sheet", str(data_dir / "found_a_love.txt"), "--key", "Xq"])
    assert bad_key.exit_code == 2
    two_files_one_html = runner.invoke(
        app, ["sheet", str(data_dir / "found_a_love.txt"), str(data_dir / "chord_list.txt"),
              "--html", str(tmp_path / "x.html")],
    )  # fmt: skip
    assert two_files_one_html.exit_code == 2


def test_info_commands(tmp_path):
    assert __version__ in runner.invoke(app, ["version"]).output
    assert "Alto sax in E♭" in runner.invoke(app, ["instruments"]).output
    assert "си-бемоль" in runner.invoke(app, ["names"]).output
    schema = runner.invoke(app, ["schema"])
    assert json.loads(schema.output)["title"] == "Song"
