"""The song tool (Phase 4): each step on made-up sound, then the whole pipeline with the two
models replaced by stand-ins, so the tests need neither the downloads nor much time."""

import io
import itertools
import wave

import numpy as np
import pytest

from soundselect import service
from soundselect.audio import SONG_SPEC, available, song_source
from soundselect.audio import beats as beats_mod
from soundselect.audio import pipeline as song_pipeline
from soundselect.audio.key import song_key
from soundselect.audio.melody import clean_melody, drop_ghosts, merge_wobbles, one_line
from soundselect.audio.model import Beats, NoteEvent, Rhythm, SongSource, TimedNote, youtube_id
from soundselect.audio.notes import FRAMES, activations, to_notes
from soundselect.audio.rhythm import beat_position, to_rhythm
from soundselect.audio.separate import CHUNK, separate_voice
from soundselect.audio.tuning import estimate_tuning
from soundselect.core.song import Corrections
from soundselect.imports import InputRef
from soundselect.pipeline import registry
from soundselect.pipeline.runner import MemoryCache

RATE = 22050


def tone(freq, seconds, rate=RATE, harmonics=(1.0, 0.5, 0.25)):
    t = np.arange(int(seconds * rate)) / rate
    return sum(a * np.sin(2 * np.pi * freq * (h + 1) * t) for h, a in enumerate(harmonics))


def clicks(bpm, seconds, rate=RATE, accent_every=4, start=0.5):
    x = np.random.default_rng(0).normal(0, 0.01, int(seconds * rate))
    length = 2000
    decay = np.exp(-np.arange(length) / 300)
    for i, t in enumerate(np.arange(start, seconds - 0.2, 60 / bpm)):
        s = int(t * rate)
        down = i % accent_every == 0
        freq = 60 if down else 2000
        x[s : s + length] += (
            (1.0 if down else 0.4) * np.sin(2 * np.pi * freq * np.arange(length) / rate) * decay
        )
    return x.astype(np.float32)


def note(start, end, pitch, strength=0.7):
    return NoteEvent(start=start, end=end, pitch=pitch, strength=strength)


# Links and sources


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD",
        "https://m.youtube.com/shorts/dQw4w9WgXcQ",
    ],
)
def test_youtube_ids(url):
    assert youtube_id(url) == "dQw4w9WgXcQ"
    assert (
        SongSource("link", url=url).fingerprint
        == SongSource("link", url="https://youtu.be/dQw4w9WgXcQ").fingerprint
    )


def test_other_links_and_files():
    assert youtube_id("https://example.com/watch?v=dQw4w9WgXcQ") is None
    assert youtube_id("not a link") is None
    a = SongSource("audio", b"abc", "a.mp3")
    assert a.fingerprint == SongSource("audio", b"abc", "b.mp3").fingerprint
    assert a.fingerprint != SongSource("audio", b"abd", "a.mp3").fingerprint


def test_song_source_from_inputs():
    ref = InputRef(kind="audio", name="a.mp3", sha="x")
    assert song_source([ref], lambda r: b"data") == SongSource("audio", b"data", "a.mp3")
    link = InputRef(kind="link", url="https://youtu.be/dQw4w9WgXcQ")
    assert song_source([link], lambda r: b"").url == link.url
    with pytest.raises(ValueError):
        song_source([ref, ref], lambda r: b"")


# Steps


@pytest.mark.parametrize("cents", [0, 22, -38])
def test_tuning(cents):
    f = 440 * 2 ** (cents / 1200)
    x = sum(tone(f * 2 ** (s / 12), 4) for s in (0, 3, 7, -5))
    found = estimate_tuning(x.astype(np.float32), RATE)
    assert abs(found.cents - cents) < 3 and found.confidence > 0.9


def test_tuning_of_silence():
    assert estimate_tuning(np.zeros(RATE * 2, np.float32), RATE).cents == 0


def test_beats_and_bars():
    found = beats_mod.find_beats(clicks(96, 20))
    assert abs(found.tempo - 96) < 2
    assert found.beats_per_bar == 4
    assert abs(found.downbeats[0] - 0.5) < 0.05
    assert all(abs(b - a - 2.5) < 0.1 for a, b in itertools.pairwise(found.downbeats))


def test_beats_of_silence():
    found = beats_mod.find_beats(np.zeros(RATE * 3, np.float32))
    assert found.beat_times == [] and found.tempo is None


def test_chroma_hears_the_notes():
    x = tone(261.63, 2) + tone(392.0, 2)  # C and G
    colors = beats_mod.chroma(beats_mod.spectrogram(x.astype(np.float32)))
    assert {int(np.argmax(colors)), int(np.argsort(colors)[-2])} == {0, 7}


def test_notes_from_activations():
    frames = np.zeros((200, 88))
    onsets = np.zeros((200, 88))
    frames[10:60, 39] = 0.9  # C4 (MIDI 60) for 50 frames
    onsets[10, 39] = 0.9
    frames[80:85, 41] = 0.9  # too short to be a note
    frames[100:150, 43] = 0.8  # E4 without an onset: found by the melodia trick
    events = sorted(to_notes(frames, onsets))
    assert [(p, a, b) for a, b, p, _ in events] == [(60, 10, 60), (64, 100, 150)]


def test_activation_windows_join_up():
    seconds = 7.3
    samples = np.zeros(int(seconds * RATE), np.float32)

    def model(windows):
        n = windows.shape[0]
        return np.ones((n, FRAMES, 88)) * 0.1, np.zeros((n, FRAMES, 88))

    frames, onsets = activations(samples, model=model, batch=2)
    assert frames.shape == onsets.shape == (int(seconds * RATE / 256), 88)


def test_separation_puts_the_chunks_back_together():
    t = np.arange(int(CHUNK * 2.3)) / 44100
    mix = np.stack([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 330 * t)]).astype(np.float32)
    seen = []
    voice = separate_voice(mix, model=lambda spec: spec, progress=seen.append)
    assert voice.shape == mix.shape
    assert np.abs(voice / 1.021 - mix)[:, 2000:-2000].max() < 0.02
    assert seen[-1] == 1.0


def test_overtones_vibrato_and_blips_are_cleaned():
    heard = [
        note(0.0, 1.0, 60, 0.8),
        note(0.0, 1.0, 72, 0.5),  # its octave
        note(0.0, 1.0, 79, 0.5),  # an octave and a fifth
        note(1.0, 1.05, 62),  # a blip
        note(1.1, 1.2, 63, 0.6),  # vibrato into the next note
        note(1.2, 2.0, 62, 0.8),
        note(2.0, 3.0, 30, 0.9),  # the bass guitar
    ]
    assert [(n.pitch, n.start, n.end) for n in clean_melody(heard)] == [
        (60, 0.0, 1.0),
        (62, 1.1, 2.0),
    ]


def test_the_lead_wins_where_notes_overlap():
    line = one_line([note(0, 1, 60, 0.4), note(0.5, 1.5, 67, 0.8)])
    assert [(n.pitch, n.start, n.end) for n in line] == [(60, 0, 0.5), (67, 0.5, 1.5)]
    assert drop_ghosts([note(0, 0.05, 60)]) == []
    assert merge_wobbles([note(0, 1, 60), note(1.3, 2, 60)]) == [note(0, 1, 60), note(1.3, 2, 60)]


def test_beat_positions_follow_the_tempo():
    beats = [1.0, 1.5, 2.0, 2.6, 3.2]  # speeding down from 120 to 100 bpm
    pos = beat_position(np.array([0.5, 1.25, 2.3, 3.2, 3.8]), beats)
    assert np.allclose(pos, [-1, 0.5, 2.5, 4, 5])


def test_rhythm_snaps_to_sixteenths_from_the_first_bar():
    grid = [0.5 + 0.5 * i for i in range(16)]  # 120 bpm, bars of four from 0.5 s
    beats = Beats(tempo=120, beat_times=grid, downbeats=grid[::4])
    melody = [
        note(0.26, 0.5, 60),  # a pickup half a beat before the first bar
        note(0.52, 1.02, 62),  # a little late: snaps to the beat
        note(1.5, 2.48, 64),
    ]
    rhythm = to_rhythm(melody, beats, 8.0)
    assert [(n.pitch, n.start, n.length) for n in rhythm.notes] == [
        (60, 3.5, 0.5),
        (62, 4.0, 1.0),  # the gap after it is closed
        (64, 6.0, 2.0),
    ]
    assert rhythm.time_signature == "4/4" and rhythm.tempo == 120
    assert abs(rhythm.first_bar - (0.5 - 2.0)) < 1e-6  # the pickup bar starts 4 beats earlier


def test_rhythm_without_a_beat():
    rhythm = to_rhythm([note(0.0, 0.6, 60)], Beats(), 2.0)
    assert rhythm.notes[0].start == 0 and rhythm.notes[0].length == 1.0  # 100 bpm


def test_key_from_the_melody():
    scale = [60, 62, 64, 65, 67, 69, 71, 72, 67, 64, 60, 67, 60]
    rhythm = Rhythm(
        notes=[TimedNote(pitch=p, start=i, length=1, confidence=0.9) for i, p in enumerate(scale)]
    )
    key = song_key(rhythm, Beats())
    assert (key.concert.tonic, key.concert.mode, key.basis) == ("C", "major", "melody")
    fixed = song_key(rhythm, Beats(), "Gm")
    assert (fixed.concert.tonic, fixed.concert.mode, fixed.basis) == ("G", "minor", "correction")
    assert song_key(Rhythm(), Beats(chroma=[0.0] * 12)) is None


# The whole pipeline, with stand-ins for the models


def wav_bytes(samples, rate=44100):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        stereo = np.stack([samples, samples], axis=1)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


# Bb major, the start of a tune: Bb C D Eb F (the sheet test's key, so alto reads G major)
TUNE = [(0.5, 1.0, 70), (1.0, 1.5, 72), (1.5, 2.0, 74), (2.0, 2.5, 75), (2.5, 3.5, 77)]


@pytest.fixture
def song_tool(tmp_path, monkeypatch):
    """The song tool with the models replaced: the voice is half the mix, the notes are TUNE."""
    pytest.importorskip("av")
    monkeypatch.setenv("SOUNDSELECT_HOME", str(tmp_path / "home"))
    calls = {"separate": 0, "notes": 0}

    def fake_separate(mix, **kwargs):
        calls["separate"] += 1
        return mix * 0.5

    def fake_notes(samples, **kwargs):
        calls["notes"] += 1
        return [note(a, b, p, 0.8) for a, b, p in TUNE] + [note(3.5, 3.6, 77, 0.2)]

    monkeypatch.setattr("soundselect.audio.separate.separate_voice", fake_separate)
    monkeypatch.setattr("soundselect.audio.notes.find_notes", fake_notes)
    beat = clicks(120, 6, rate=44100, start=0.5)
    mix = beat.copy()
    for a, b, p in TUNE:
        sung = tone(440 * 2 ** ((p - 69) / 12), b - a, 44100)
        mix[int(a * 44100) : int(a * 44100) + len(sung)] += 0.3 * sung
    return wav_bytes(mix * 0.5), calls


def test_song_from_an_audio_file(song_tool):
    data, calls = song_tool
    source = SongSource("audio", data, "Test Band - Little Tune.wav")
    cache = MemoryCache()
    steps = []
    song = song_pipeline.analyze_song(
        source, cache=cache, on_step=lambda name, phase, n, total: steps.append((name, phase))
    )
    assert [s for s, phase in steps if phase == "done"] == [
        s.name for s in SONG_SPEC.pipeline.steps
    ]
    assert (song.identity.title, song.identity.artist) == ("Little Tune", "Test Band")
    assert song.identity.source == "audio" and song.identity.fingerprint == source.fingerprint
    assert song.timing.time_signature == "4/4" and abs(song.timing.tempo - 120) < 3
    assert [n.concert for n in song.melody.notes] == ["Bb4", "C5", "D5", "Eb5", "F5"]
    assert song.view.instrument == "alto_sax"
    assert [n.written for n in song.melody.notes][:2] in (["G4", "A4"], ["G5", "A5"])
    assert song.headline is not None and song.melody.source == "audio"
    assert any(n.code == "melody_draft" for n in song.notes)
    assert song.versions["separate"] == song_pipeline.SEPARATE_VERSION
    assert calls == {"separate": 1, "notes": 1}

    # a key correction runs only the key and what follows it; the separated parts are kept
    fixed = song_pipeline.analyze_song(
        source, cache=cache, corrections=Corrections(key="Gm", melody_octave=-1)
    )
    assert fixed.key.concert.tonic == "G" and fixed.key.basis == "correction"
    assert fixed.melody.octave_shift == -1
    assert calls == {"separate": 1, "notes": 1}

    # a new cache still finds the separated parts on disk
    song_pipeline.analyze_song(source, cache=MemoryCache())
    assert calls == {"separate": 1, "notes": 2}


def test_melody_moves_into_the_comfortable_range(song_tool):
    data, _ = song_tool
    song = song_pipeline.analyze_song(SongSource("audio", data, "low.wav"))
    low = song_pipeline.write_for(
        song.model_copy(
            update={
                "melody": song.melody.model_copy(
                    update={
                        "notes": [
                            n.model_copy(update={"concert": "Bb2"}) for n in song.melody.notes
                        ]
                    }
                )
            }
        ),
        service.ViewSettings(),
    )
    assert low.melody.octave_shift == 1 and low.melody.notes[0].written == "G4"


def test_import_an_audio_file(song_tool, library):
    data, _ = song_tool
    batch = service.start_import(library, files=[("tune.wav", data)])
    job = batch.jobs[0]
    assert job.kind == "song" and job.status == "queued"
    from soundselect.jobs.work import run_job

    run_job(library, job.id)
    done = library.job(job.id)
    assert done.status == "done", done.error
    song = service.get_song(library, done.song_id)
    assert song.melody is not None and song.identity.title == "tune"
    again = service.start_import(library, files=[("copy.wav", data)])
    run_job(library, again.jobs[0].id)
    assert library.job(again.jobs[0].id).reused


def test_links_use_the_download_module(song_tool, monkeypatch):
    from soundselect import links

    def refuse(url, folder, want="video"):
        raise links.LinkError("This video is private.")

    monkeypatch.setattr(links, "download", refuse)
    with pytest.raises(Exception, match="private"):
        song_pipeline.analyze_song("https://youtu.be/dQw4w9WgXcQ")


def test_unreadable_audio(song_tool):
    from soundselect.sheets.readers import UnsupportedInput

    with pytest.raises(UnsupportedInput):
        song_pipeline.analyze_song(SongSource("audio", b"not sound at all", "x.mp3"))


def test_ready_only_with_the_engines(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "av" else real(name, *a)
    )
    assert not available() and not registry.ready("song")
    assert registry.route("audio") is None
    message = registry.not_yet_message(InputRef(kind="audio", name="a.mp3"))
    assert "uv sync --all-extras" in message


# The melody on the staff (a handoff to render/)


def test_melody_score(song_tool):
    from xml.dom import minidom

    import verovio

    from soundselect.audio.score import melody_xml

    data, _ = song_tool
    song = song_pipeline.analyze_song(SongSource("audio", data, "tune.wav"))
    notes = [n.model_copy(update={"start": 3.0, "length": 2.5}) for n in song.melody.notes[:1]]
    notes[0] = notes[0].model_copy(update={"confidence": 0.1})
    song = song.model_copy(update={"melody": song.melody.model_copy(update={"notes": notes})})
    xml = melody_xml(song, "russian")
    doc = minidom.parseString(xml.split("\n", 2)[2])
    measures = doc.getElementsByTagName("measure")
    assert len(measures) == 2  # a note from beat 4 for 2.5 beats crosses into bar 2
    ties = [t.getAttribute("type") for t in doc.getElementsByTagName("tie")]
    assert ties == ["start", "stop"]
    assert 'color="#C0392B"' in xml and "соль" in xml  # doubtful, and G4 named in Russian
    assert doc.getElementsByTagName("fifths")[0].firstChild.data == "1"  # G major for alto
    tk = verovio.toolkit()
    assert tk.loadData(xml)
