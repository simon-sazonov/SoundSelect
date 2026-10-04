"""Hooks for the next phases: pipeline and page registries, import routing, the written melody."""

import dataclasses

import pytest

from soundselect import service
from soundselect.core.song import Melody, MelodyNote
from soundselect.core.view import apply_instrument
from soundselect.imports import MIXED_GROUP, NOT_YET, ImportOptions, InputRef, plan_jobs
from soundselect.pipeline import registry
from soundselect.pipeline.registry import CHORD_SHEET_SPEC, register_pipeline, route
from soundselect.service import NotFound
from soundselect.sheets import readers
from soundselect.sheets.readers import UnsupportedInput, render_source_page

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def fake_spec(name, *, available=True, claims=None, pages=None):
    return dataclasses.replace(
        CHORD_SHEET_SPEC, name=name, available=lambda: available, claims=claims, pages=pages
    )


@pytest.fixture
def sheet_music(monkeypatch):
    """A sheet music pipeline that is built and installed, claiming every image."""
    spec = fake_spec("sheet_music", claims=lambda data: True)
    monkeypatch.setitem(registry.PIPELINES, "sheet_music", spec)
    return spec


def boom(data):
    raise RuntimeError("broken image")


@pytest.fixture
def without_photos(monkeypatch):
    """As before the photo reader was built."""
    monkeypatch.delitem(readers.READERS, "photo")
    monkeypatch.delitem(readers.READERS, "group")


# Routing


def test_route_with_nothing_more_built(without_photos):
    assert route("text") == route("pdf") == "chord_sheet"
    for kind in ("photo", "video", "audio", "link"):
        assert route(kind, PNG) is None, kind
    assert route("photo", PNG, image_mode="sheet_music") is None


@pytest.mark.parametrize(
    ("claims", "auto"),
    [(lambda data: True, "sheet_music"), (lambda data: False, None), (boom, None)],
)
def test_route_images(monkeypatch, without_photos, claims, auto):
    monkeypatch.setitem(registry.PIPELINES, "sheet_music", fake_spec("sheet_music", claims=claims))
    assert route("photo", PNG) == auto
    assert route("photo", PNG, image_mode="sheet_music") == "sheet_music"
    assert route("photo", PNG, image_mode="chord_sheet") is None  # no photo reader yet
    monkeypatch.setitem(readers.READERS, "photo", lambda inp: None)
    assert route("photo", PNG) == (auto or "chord_sheet")
    assert route("photo", PNG, image_mode="chord_sheet") == "chord_sheet"
    assert route("video") == "sheet_music"


def test_route_when_the_tools_are_missing(monkeypatch):
    monkeypatch.setitem(
        registry.PIPELINES, "sheet_music", fake_spec("sheet_music", available=False)
    )
    assert route("photo", PNG, image_mode="sheet_music") is None
    assert route("video") is None
    assert not registry.ready("sheet_music")
    message = registry.not_yet_message(InputRef(kind="video", name="v.mp4"))
    assert "uv sync --all-extras" in message


def test_route_links_and_audio(monkeypatch):
    assert route("link", link_mode="sound") is None
    monkeypatch.setitem(registry.PIPELINES, "song", fake_spec("song"))
    assert route("audio") == "song"
    assert route("link") == "song"
    assert route("link", link_mode="sound") == "song"
    assert route("link", link_mode="sheet_music") is None
    monkeypatch.setitem(registry.PIPELINES, "sheet_music", fake_spec("sheet_music"))
    assert route("link") == "sheet_music"  # until Phase 4 looks at the link
    assert route("link", link_mode="sound") == "song"


def test_register_pipeline(monkeypatch):
    monkeypatch.setattr(registry, "PIPELINES", dict(registry.PIPELINES))
    with pytest.raises(ValueError, match="registered already"):
        register_pipeline(CHORD_SHEET_SPEC)
    spec = register_pipeline(fake_spec("song"))
    assert registry.get_pipeline("song") is spec and registry.ready("song")


def test_groupable(monkeypatch, without_photos, sheet_music):
    assert registry.groupable() == {"sheet_music"}
    monkeypatch.setitem(readers.READERS, "group", lambda inp: None)
    assert registry.groupable() == {"sheet_music", "chord_sheet"}


def test_photos_are_chord_sheets():
    assert route("photo", PNG) == route("photo", PNG, image_mode="chord_sheet") == "chord_sheet"
    assert "chord_sheet" in registry.groupable()


# Source pages


def test_pages_run_across_the_parts(data_dir, monkeypatch):
    monkeypatch.setitem(readers.PAGES, "fake", (lambda data: 1, lambda data, i: b"FAKE"))
    pdf = (data_dir / "pdf" / "russian_two_pages.pdf").read_bytes()
    parts = [("pdf", pdf), ("text", b"Am C"), ("fake", b"x")]
    assert render_source_page(parts, 1).startswith(b"\x89PNG")
    assert render_source_page(parts, 2) == b"FAKE"
    for index in (3, -1):
        with pytest.raises(IndexError):
            render_source_page(parts, index)
    with pytest.raises(UnsupportedInput):
        render_source_page([("text", b"Am C")], 0)


def test_page_image_through_a_pipeline_hook(library, found_a_love, monkeypatch):
    calls = []

    def pages(inputs, read, index):
        calls.append(index)
        if index > 0:
            raise IndexError(index)
        return PNG

    monkeypatch.setitem(registry.PIPELINES, "fake", fake_spec("fake", pages=pages))
    ref = library.store_input(PNG, "photo", "page.png")
    song = library.add_song(found_a_love, pipeline="fake", inputs=[ref])
    path = service.page_image(library, song.id, 0)
    assert path.read_bytes() == PNG and path.parts[-3] == "fake"
    assert service.page_image(library, song.id, 0) == path
    assert calls == [0]  # drawn once, then kept
    with pytest.raises(NotFound, match="no page 2"):
        service.page_image(library, song.id, 1)


# Health


def test_health_tools(client, monkeypatch, without_photos):
    tools = client.get("/api/v1/health").json()["tools"]
    assert tools["photo_reading"] is tools["sheet_music"] is tools["audio"] is False
    assert tools["links"] is False
    monkeypatch.setitem(registry.PIPELINES, "sheet_music", fake_spec("sheet_music"))
    tools = client.get("/api/v1/health").json()["tools"]
    assert tools["sheet_music"] is True and tools["audio"] is False
    assert tools["links"] is True  # yt-dlp comes with the extras


# Planning jobs


def ref(name, kind="photo"):
    return InputRef(kind=kind, name=name, sha=name)


def test_groups_of_one_kind():
    files = [ref("a.png"), ref("b.png"), ref("c.pdf", "pdf")]
    plans = plan_jobs(
        [],
        files,
        [],
        [[1, 0]],
        kinds=["sheet_music", "sheet_music", "chord_sheet"],
        groupable={"sheet_music"},
    )
    assert [(p.kind, [r.name for r in p.inputs]) for p in plans] == [
        ("sheet_music", ["b.png", "a.png"]),  # in group order
        ("chord_sheet", ["c.pdf"]),
    ]


def test_group_refused():
    files = [ref("a.png"), ref("b.jpg")]
    mixed = plan_jobs([], files, [], [[0, 1]], kinds=["sheet_music", "chord_sheet"])
    assert mixed[0].kind is None and mixed[0].not_yet == MIXED_GROUP
    lone = plan_jobs([], files, [], [[0, 1]], kinds=["chord_sheet", "chord_sheet"])
    assert lone[0].not_yet == NOT_YET["group"]  # chord sheets can't be stacked yet
    unread = plan_jobs([], files, [], [[0, 1]], kinds=[None, None])
    assert unread[0].not_yet == NOT_YET["photo"]


def test_sheet_music_images_make_one_piece():
    files = [ref("s1.png"), ref("song.pdf", "pdf"), ref("s2.png"), ref("v.mp4", "video")]
    files.append(ref("v2.mp4", "video"))
    kinds = ["sheet_music", "chord_sheet", "sheet_music", "sheet_music", "sheet_music"]
    plans = plan_jobs([ref("Pasted", "text")], files, [], kinds=kinds)
    assert [(p.name, len(p.inputs)) for p in plans] == [
        ("Pasted", 1),
        ("s1.png and 1 more", 2),
        ("song.pdf", 1),
        ("v.mp4", 1),  # a video is one piece
        ("v2.mp4", 1),
    ]


def test_not_yet_messages():
    links = [InputRef(kind="link", url="https://youtu.be/x")]
    plans = plan_jobs([], [ref("a.mp3", "audio")], links, kinds=[None], link_kinds=[None])
    assert [p.not_yet for p in plans] == [NOT_YET["audio"], NOT_YET["link"]]
    message = registry.not_yet_message(ref("a.png"), image_mode="sheet_music")
    assert message == NOT_YET["sheet_music"]


def test_start_import_routes_screenshots(library, sheet_music):
    files = [(f"s{i}.png", PNG) for i in range(3)]
    batch = service.start_import(library, files=files)
    assert len(batch.jobs) == 1
    job = batch.jobs[0]
    assert job.kind == "sheet_music" and len(job.inputs) == 3 and job.name == "s0.png and 2 more"
    as_photos = service.start_import(
        library, files=files, options=ImportOptions(image_mode="chord_sheet")
    )
    assert [j.inputs[0].kind for j in as_photos.jobs] == ["photo"] * 3


# The written melody


def test_written_melody_for_alto(found_a_love):
    notes = [
        MelodyNote(concert="C4", start=0, length=1),
        MelodyNote(concert="Bb3", start=1, length=1),
        MelodyNote(concert=None, start=2, length=1),
        MelodyNote(concert="C6", start=3, length=1),
    ]
    song = found_a_love.model_copy(update={"melody": Melody(notes=notes, source="audio")})
    out = apply_instrument(song, "alto_sax", comfortable_low="C4", comfortable_high="C6")
    written = [(n.written, n.out_of_range) for n in out.melody.notes]
    assert written == [("A4", False), ("G4", False), (None, False), ("A6", True)]

    down = song.model_copy(update={"melody": Melody(notes=notes, octave_shift=-1, source="audio")})
    out = apply_instrument(down, "alto_sax", comfortable_low="C4", comfortable_high="C6")
    written = [(n.written, n.out_of_range) for n in out.melody.notes]
    assert written == [("A3", True), ("G3", True), (None, False), ("A5", False)]
