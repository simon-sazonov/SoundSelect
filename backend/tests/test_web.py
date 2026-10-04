"""The simple screens served by the back end: each one opens and shows what it should."""

import pytest


def add(client, text):
    res = client.post("/api/v1/imports", data={"text": text})
    return res.json()


def test_home(client, sheet_text):
    page = client.get("/")
    assert page.status_code == 200 and "Make my page" in page.text
    assert "Your songs will show up here." in page.text
    add(client, sheet_text)
    page = client.get("/").text
    assert "I Found a Love" in page and "соль мажор" in page  # written key, Russian names


def test_library(client, sheet_text, data_dir):
    add(client, sheet_text)
    add(client, (data_dir / "russian_h.txt").read_text(encoding="utf-8"))
    page = client.get("/library").text
    assert "2 songs" in page and "keys for Alto sax in E♭" in page
    found = client.get("/library?q=лето").text
    assert "1 song found" in found and "Песня про лето" in found
    assert "No songs found." in client.get("/library?q=nothing-like-this").text
    assert client.get("/library?sort=sideways").status_code == 422


def test_batch(client, sheet_text):
    batch = add(client, sheet_text + "\n")
    page = client.get(f"/batches/{batch['id']}").text
    assert "Done" in page and f"/songs/{batch['jobs'][0]['song_id']}" in page
    failed = client.post("/api/v1/imports", data={"link": "https://youtu.be/x"}).json()
    page = client.get(f"/batches/{failed['id']}").text
    assert "Couldn't read it" in page and "Links (YouTube and others)" in page
    assert "isn't here" in client.get("/batches/nope").text


def test_batch_for_another_instrument(client, sheet_text):
    batch = client.post(
        "/api/v1/imports", data={"text": sheet_text, "instrument": "tenor_sax"}
    ).json()
    page = client.get(f"/batches/{batch['id']}").text
    assert f"/songs/{batch['jobs'][0]['song_id']}?instrument=tenor_sax" in page
    default = client.post("/api/v1/imports", data={"text": "C G\nla", "instrument": "alto_sax"})
    page = client.get(f"/batches/{default.json()['id']}").text
    assert "?instrument=" not in page


def test_song(client, sheet_text):
    song_id = add(client, sheet_text)["jobs"][0]["song_id"]
    page = client.get(f"/songs/{song_id}").text
    assert "Fix what was read wrong" in page and "Major pentatonic on соль" in page
    assert '<option value="Bb major">си-бемоль мажор</option>' in page
    assert "<svg" in page  # the staff
    letters = client.get(f"/songs/{song_id}?names=letters&view=concert").text
    assert "B♭ major pentatonic" in letters
    tenor = client.get(f"/songs/{song_id}?instrument=tenor_sax").text
    assert "Key for Tenor sax in B♭" in tenor
    redirect = client.get(f"/songs/{song_id}?instrument=kazoo", follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers["location"] == f"/songs/{song_id}"
    assert "isn't here" in client.get("/songs/nope").text


def test_song_shows_saved_fixes(client, sheet_text):
    song_id = add(client, sheet_text)["jobs"][0]["song_id"]
    client.patch(f"/api/v1/songs/{song_id}", json={"key": "C major", "capo": 3})
    page = client.get(f"/songs/{song_id}").text
    assert '<option value="C major" selected>' in page
    assert 'value="3"' in page and "Undo all my fixes" in page


@pytest.mark.parametrize("path", ["/settings", "/library"])
def test_screens_open(client, path):
    assert client.get(path).status_code == 200


def test_api_docs(client):
    assert client.get("/api/v1/docs").status_code == 200
    assert client.get("/api/v1/openapi.json").json()["info"]["title"] == "SoundSelect"


def test_without_screens(tmp_path):
    from fastapi.testclient import TestClient

    from soundselect.api import create_app

    with TestClient(create_app(tmp_path, screens=False)) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/v1/health").status_code == 200
