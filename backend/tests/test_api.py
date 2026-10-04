"""The web API the front end talks to: every call, its answers and its errors."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

from soundselect.api import create_app, openapi_json
from soundselect.jobs import run_job
from soundselect.render.pdf import pdf_available

API = "/api/v1"


def import_text(client, text, **fields):
    res = client.post(f"{API}/imports", data={"text": text, **fields})
    assert res.status_code == 202, res.text
    return res.json()


@pytest.fixture
def song_id(client, sheet_text):
    return import_text(client, sheet_text)["jobs"][0]["song_id"]


def events(body: str) -> list[tuple[str, dict]]:
    found = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            found.append((fields["event"], json.loads(fields["data"])))
    return found


def test_import_text(client, sheet_text):
    batch = import_text(client, sheet_text)
    assert batch["status"] == "done" and batch["total"] == 1 and batch["done"] == 1
    job = batch["jobs"][0]
    assert job["status"] == "done" and job["kind"] == "chord_sheet" and job["song_id"]
    assert client.get(f"{API}/batches/{batch['id']}").json() == batch
    assert client.get(f"{API}/jobs/{job['id']}").json() == job


def test_import_files_and_links(client, data_dir):
    pdf = (data_dir / "pdf" / "two_columns.pdf").read_bytes()
    res = client.post(
        f"{API}/imports",
        files=[
            ("files", ("two_columns.pdf", pdf, "application/pdf")),
            ("files", ("river_song.cho", (data_dir / "river_song.cho").read_bytes(), "text/plain")),
            ("files", ("photo.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")),
        ],
        data={"link": "https://youtu.be/xyz", "instrument": "tenor_sax"},
    )
    assert res.status_code == 202, res.text
    batch = res.json()
    statuses = [(j["name"], j["status"]) for j in batch["jobs"]]
    assert statuses == [
        ("two_columns.pdf", "done"),
        ("river_song.cho", "done"),
        ("photo.jpg", "failed"),
        ("https://youtu.be/xyz", "failed"),
    ]
    assert batch["options"]["instrument"] == "tenor_sax"
    song = client.get(f"{API}/songs/{batch['jobs'][0]['song_id']}").json()
    assert song["identity"]["source"] == "pdf"


def test_empty_file_field(client, sheet_text):
    """A form sent with its file field left empty, as browsers send it."""
    body = (
        '--x\r\nContent-Disposition: form-data; name="text"\r\n\r\n'
        f"{sheet_text}\r\n"
        '--x\r\nContent-Disposition: form-data; name="files"; filename=""\r\n'
        "Content-Type: application/octet-stream\r\n\r\n\r\n--x--\r\n"
    )
    res = client.post(
        f"{API}/imports",
        content=body.encode(),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert res.status_code == 202, res.text
    assert [j["status"] for j in res.json()["jobs"]] == ["done"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "Nothing to import"),
        ({"text": "Am C", "groups": "[[0"}, "import options can't be used"),
        ({"text": "Am C", "key": "Q"}, "as a key"),
        ({"text": "Am C", "instrument": "kazoo"}, "Unknown instrument"),
    ],
)
def test_import_errors(client, data, message):
    res = client.post(f"{API}/imports", data=data)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "bad_request" and message in detail["message"]


def test_import_checks_its_fields(client):
    res = client.post(f"{API}/imports", data={"text": "Am C", "capo": "13"})
    assert res.status_code == 422


def test_batch_events_follow_the_work(tmp_path, sheet_text):
    """Jobs that wait for a worker: the stream sends each change, then ends."""
    app = create_app(tmp_path, workers=0)  # nothing runs the jobs but this test
    with TestClient(app) as client:
        batch = import_text(client, sheet_text)
        job = batch["jobs"][0]
        assert job["status"] == "queued"
        lib = app.state.library
        worker = threading.Timer(0.4, run_job, args=(lib, job["id"]))
        worker.start()
        res = client.get(f"{API}/batches/{batch['id']}/events")
        worker.join()
    assert res.headers["content-type"].startswith("text/event-stream")
    found = events(res.text)
    jobs = [data for kind, data in found if kind == "job"]
    assert jobs[0]["status"] == "queued" and jobs[-1]["status"] == "done"
    assert [kind for kind, _ in found][-2:] == ["batch", "end"]
    assert found[-1][1] == {"status": "done"}
    revs = [j["rev"] for j in jobs]
    assert revs == sorted(set(revs))  # each change once, in order


def test_job_events(client, sheet_text):
    job = import_text(client, sheet_text)["jobs"][0]
    found = events(client.get(f"{API}/jobs/{job['id']}/events").text)
    assert [kind for kind, _ in found] == ["job", "end"]
    assert found[0][1]["song_id"] == job["song_id"]


@pytest.mark.parametrize("path", ["batches/nope", "batches/nope/events", "jobs/nope/events"])
def test_missing_batches_and_jobs(client, path):
    res = client.get(f"{API}/{path}")
    assert res.status_code == 404 and res.json()["detail"]["code"] == "not_found"


def test_library(client, sheet_text, data_dir):
    love = import_text(client, sheet_text)["jobs"][0]["song_id"]
    russian = import_text(client, (data_dir / "russian_h.txt").read_text(encoding="utf-8"))
    russian = russian["jobs"][0]["song_id"]
    listed = client.get(f"{API}/songs").json()
    assert listed["total"] == 2 and [s["id"] for s in listed["songs"]] == [russian, love]
    first = listed["songs"][1]
    assert first["written_key"]["tonic"] == "G" and first["pentatonic"] == ["G", "A", "B", "D", "E"]
    assert [s["id"] for s in client.get(f"{API}/songs?q=лето").json()["songs"]] == [russian]
    by_title = client.get(f"{API}/songs?sort=title&limit=1&offset=1").json()
    assert by_title["total"] == 2 and by_title["songs"][0]["id"] == russian
    tenor = client.get(f"{API}/songs?instrument=tenor_sax").json()["songs"][1]
    assert tenor["written_key"]["tonic"] == "C"
    assert client.get(f"{API}/songs?limit=0").status_code == 422


def test_song(client, song_id):
    song = client.get(f"{API}/songs/{song_id}").json()
    assert song["id"] == song_id and song["view"]["instrument"] == "alto_sax"
    assert song["names"]["Bb"] == "си♭"  # the default note names
    letters = client.get(f"{API}/songs/{song_id}?names=letters&instrument=tenor_sax").json()
    assert letters["names"]["Bb"] == "B♭" and letters["view"]["written_key"]["tonic"] == "C"
    assert client.get(f"{API}/songs/{song_id}?instrument=kazoo").status_code == 400
    assert client.get(f"{API}/songs/{song_id}?names=klingon").status_code == 422
    missing = client.get(f"{API}/songs/nope")
    assert missing.status_code == 404 and missing.json()["detail"]["message"]


def test_corrections(client, song_id):
    res = client.patch(f"{API}/songs/{song_id}", json={"key": "C", "title": "Fixed"})
    assert res.status_code == 200, res.text
    song = res.json()
    assert song["key"]["concert"]["tonic"] == "C" and song["identity"]["title"] == "Fixed"
    assert song["view"]["written_key"]["tonic"] == "A"
    assert client.get(f"{API}/songs/{song_id}").json()["corrections"]["key"] == "C"
    cleared = client.patch(f"{API}/songs/{song_id}", json={"key": None}).json()
    assert cleared["corrections"]["key"] is None and cleared["corrections"]["title"] == "Fixed"
    bad = client.patch(f"{API}/songs/{song_id}", json={"key": "H-moll-ish"})
    assert bad.status_code == 400 and "as a key" in bad.json()["detail"]["message"]
    assert client.patch(f"{API}/songs/{song_id}", json={"capo": 20}).status_code == 422
    assert client.patch(f"{API}/songs/nope", json={}).status_code == 404


def test_delete(client, song_id):
    assert client.delete(f"{API}/songs/{song_id}").status_code == 204
    assert client.get(f"{API}/songs/{song_id}").status_code == 404
    assert client.delete(f"{API}/songs/{song_id}").status_code == 404


def test_scores(client, song_id):
    res = client.get(f"{API}/songs/{song_id}/score?part=headline")
    assert res.status_code == 200 and res.headers["content-type"].startswith(
        "application/vnd.recordare.musicxml+xml"
    )
    assert "<score-partwise" in res.text
    svg = client.get(f"{API}/songs/{song_id}/score?part=headline&format=svg")
    assert svg.headers["content-type"].startswith("image/svg+xml") and "<svg" in svg.text
    chord = client.get(f"{API}/songs/{song_id}/score?part=chord&chord=Gm")
    assert chord.status_code == 200 and "<harmony" in chord.text
    assert client.get(f"{API}/songs/{song_id}/score?part=chord&chord=Q").status_code == 404
    assert client.get(f"{API}/songs/{song_id}/score?part=melody").status_code == 422


@pytest.mark.parametrize(
    ("fmt", "media", "start"),
    [
        ("json", "application/json", b"{"),
        ("txt", "text/plain", b"I Found a Love"),
        ("html", "text/html", b"<!doctype html>"),
        ("musicxml", "application/vnd.recordare.musicxml+xml", b"<?xml"),
    ],
)
def test_exports(client, song_id, fmt, media, start):
    res = client.get(f"{API}/songs/{song_id}/export?format={fmt}")
    assert res.status_code == 200 and res.headers["content-type"].startswith(media)
    assert res.content.lstrip().startswith(start)
    assert f'filename="I Found a Love.{fmt}"' in res.headers["content-disposition"]


@pytest.mark.skipif(not pdf_available(), reason="PDF output needs the Pango library")
def test_pdf_export(client, song_id):
    res = client.get(f"{API}/songs/{song_id}/export")
    assert res.status_code == 200 and res.content.startswith(b"%PDF")


def test_midi_comes_later(client, song_id):
    res = client.get(f"{API}/songs/{song_id}/export?format=midi")
    assert res.status_code == 501 and res.json()["detail"]["code"] == "not_built"


def test_source_pages(client, data_dir, song_id):
    pdf = (data_dir / "pdf" / "russian_two_pages.pdf").read_bytes()
    res = client.post(f"{API}/imports", files=[("files", ("russian.pdf", pdf, "application/pdf"))])
    pdf_song = res.json()["jobs"][0]["song_id"]
    pages = client.get(f"{API}/songs/{pdf_song}/pages").json()
    assert [p["index"] for p in pages["pages"]] == [0, 1]
    assert pages["pages"][1]["image"] == f"/api/v1/songs/{pdf_song}/pages/1.png"
    assert {line["page"] for line in pages["lines"]} == {0, 1}
    image = client.get(pages["pages"][1]["image"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert client.get(f"{API}/songs/{pdf_song}/pages/9.png").status_code == 404
    song = client.get(f"{API}/songs/{pdf_song}").json()
    assert song["source_pages"][0]["image"] == f"/api/v1/songs/{pdf_song}/pages/0.png"
    assert client.get(f"{API}/songs/{song_id}/pages").json() == {"pages": [], "lines": []}


def test_songbook(client, sheet_text, data_dir):
    pdf = (data_dir / "pdf" / "found_a_love_mono.pdf").read_bytes()
    res = client.post(
        f"{API}/imports",
        data={"text": (data_dir / "russian_h.txt").read_text(encoding="utf-8")},
        files=[("files", ("love.pdf", pdf, "application/pdf"))],
    )
    batch = res.json()
    html = client.get(f"{API}/batches/{batch['id']}/songbook?format=html&names=letters")
    assert html.status_code == 200
    assert "2 songs, written for Alto sax" in html.text
    assert html.text.count('<article class="song"') == 2
    if pdf_available():
        book = client.get(f"{API}/batches/{batch['id']}/songbook")
        assert book.content.startswith(b"%PDF")
        assert 'filename="Songbook.pdf"' in book.headers["content-disposition"]
    failed = client.post(f"{API}/imports", data={"link": "https://youtu.be/x"}).json()
    assert client.get(f"{API}/batches/{failed['id']}/songbook").status_code == 404
    tenor = client.post(f"{API}/imports", data={"text": sheet_text, "instrument": "tenor_sax"})
    book = client.get(f"{API}/batches/{tenor.json()['id']}/songbook?format=html").text
    assert "written for Tenor sax" in book


def test_settings(client, song_id):
    settings = client.get(f"{API}/settings").json()
    assert settings["instrument"] == "alto_sax" and settings["names"] == "russian"
    changed = {**settings, "instrument": "tenor_sax", "names": "letters"}
    assert client.put(f"{API}/settings", json=changed).json() == changed
    song = client.get(f"{API}/songs/{song_id}").json()
    assert song["view"]["instrument"] == "tenor_sax" and song["names"]["Bb"] == "B♭"
    bad = {**settings, "comfortable_low": "C4", "comfortable_high": "E4"}
    assert client.put(f"{API}/settings", json=bad).status_code == 422
    kazoo = {**settings, "instrument": "kazoo"}
    assert client.put(f"{API}/settings", json=kazoo).status_code == 422


def test_instruments(client):
    found = {i["id"]: i for i in client.get(f"{API}/instruments").json()}
    assert found["alto_sax"]["interval"] == "M6" and found["alto_sax"]["name"] == "Alto sax in E♭"
    assert "concert" in found


def test_health(client, song_id):
    health = client.get(f"{API}/health").json()
    assert health["status"] == "ok" and health["songs"] == 1 and health["jobs_waiting"] == 0
    assert health["workers"] is True and health["tools"]["pdf_reading"] is True
    assert health["tools"]["photo_reading"] is False


def test_search_comes_later(client):
    res = client.get(f"{API}/search?q=yesterday")
    assert res.status_code == 501 and "song tool" in res.json()["detail"]["message"]


def test_front_end_dev_server_may_call(client):
    res = client.get(f"{API}/health", headers={"Origin": "http://localhost:5173"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = client.get(f"{API}/health", headers={"Origin": "http://example.com"})
    assert "access-control-allow-origin" not in other.headers


def test_published_description_is_current():
    """docs/openapi.json is what the front end builds against; regenerate it with
    `soundselect openapi --out docs/openapi.json` when the API changes."""
    from pathlib import Path

    kept = Path(__file__).parents[2] / "docs" / "openapi.json"
    assert kept.read_text(encoding="utf-8") == openapi_json()
