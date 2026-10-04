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


def test_batch_names_stay_inside_the_folder_and_apart(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    for folder in (first, second):
        (folder / "song.txt").write_text("C  G  Am  F\nwords\n", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "sheet",
            str(first / "song.txt"),
            str(second / "song.txt"),
            "--out",
            str(out),
            "-f",
            "txt",
            "-q",
        ],
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in out.iterdir()) == ["song-2.txt", "song.txt"]
    pasted = runner.invoke(
        app,
        ["sheet", "-", "--out", str(out), "-f", "txt", "-q"],
        input="../../Evil/Name\nC  G\nla la\n",
    )
    assert pasted.exit_code == 0, pasted.output
    assert all(p.parent == out for p in out.iterdir())


def test_library_commands(data_dir, tmp_path):
    home = ["--home", str(tmp_path / "lib")]
    empty = runner.invoke(app, ["songs", *home])
    assert empty.exit_code == 0 and "The library is empty." in empty.output
    added = runner.invoke(
        app,
        ["add", str(data_dir / "found_a_love.txt"), str(data_dir / "pdf" / "scanned.pdf"), *home],
    )
    assert added.exit_code == 1  # one of the two couldn't be read
    assert "I Found a Love — Test Band  ·  соль мажор  ·  соль ля си ре ми" in added.output
    assert "scanned.pdf: This PDF is a scan" in added.output
    again = runner.invoke(app, ["add", str(data_dir / "found_a_love.txt"), *home])
    assert again.exit_code == 0 and "(already in the library)" in again.output
    pasted = runner.invoke(app, ["add", "-", "--key", "C", "--title", "Mine", *home], input="C G\n")
    assert pasted.exit_code == 0 and "Mine  ·  ля мажор" in pasted.output
    listed = runner.invoke(app, ["songs", *home])
    assert listed.output.index("Mine") < listed.output.index("I Found a Love")  # newest first
    found = runner.invoke(app, ["songs", "love", "--limit", "1", *home])
    assert "Mine" not in found.output and "I Found a Love" in found.output
    assert "No songs found." in runner.invoke(app, ["songs", "zzz", *home]).output
    tenor = runner.invoke(app, ["add", str(data_dir / "river_song.cho"), "-i", "tenor_sax", *home])
    assert tenor.exit_code == 0 and "ми мажор" in tenor.output  # D major for tenor is E major


def test_add_errors(data_dir, tmp_path):
    home = ["--home", str(tmp_path / "lib")]
    assert runner.invoke(app, ["add", str(tmp_path / "nope.txt"), *home]).exit_code == 2
    two = [str(data_dir / "found_a_love.txt"), str(data_dir / "river_song.cho")]
    assert runner.invoke(app, ["add", *two, "--title", "x", *home]).exit_code == 2
    unknown = runner.invoke(app, ["add", two[0], "-i", "kazoo", *home])
    assert unknown.exit_code == 1 and "Unknown instrument" in unknown.output


def test_openapi_command(tmp_path):
    out = tmp_path / "openapi.json"
    assert runner.invoke(app, ["openapi", "--out", str(out)]).exit_code == 0
    spec = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/v1/imports" in spec["paths"]


def test_serve_and_worker_commands(tmp_path, monkeypatch):
    import uvicorn

    from soundselect.jobs import JobQueue

    started = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.update(app=app, **kw))
    result = runner.invoke(app, ["serve", "--home", str(tmp_path), "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert (started["host"], started["port"]) == ("127.0.0.1", 9000)
    assert started["app"].state.library.home == tmp_path
    assert "anyone who can reach this computer" not in result.output
    shared = runner.invoke(app, ["serve", "--home", str(tmp_path), "--host", "0.0.0.0"])
    assert "anyone who can reach this computer" in shared.output

    ran = {}
    monkeypatch.setattr(JobQueue, "run_forever", lambda self, workers: ran.update(n=workers))
    assert runner.invoke(app, ["worker", "--home", str(tmp_path), "--workers", "3"]).exit_code == 0
    assert ran == {"n": 3}
