"""The song pipeline: open the recording, check its tuning, separate the voice, find the notes,
pick out the melody, find the beat, fit the notes to it, find the key, assemble the Song, then
the music core writes it for the player's instrument.

Separated audio is kept in the song's folder (see ``files``), so a correction (the key, the
melody's octave, the title) re-runs only the quick steps after it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path, PurePath
from typing import Any

import numpy as np

from ..core.instruments import Transposition, get_instrument
from ..core.keys import Key
from ..core.pitch import Pitch
from ..core.ranges import fit_melody
from ..core.song import (
    Corrections,
    Identity,
    KeyResult,
    Melody,
    MelodyNote,
    Notice,
    Song,
    Timing,
)
from ..core.view import VERSION as VIEW_VERSION
from ..core.view import apply_instrument
from ..pipeline.runner import Cache, Pipeline, Step, StepEvent
from ..settings import ViewSettings
from ..sheets.analyze import _key_notices
from ..sheets.readers import UnsupportedInput
from . import files
from .model import AUDIO_VERSION, Beats, Notes, Recording, Rhythm, Separation, SongSource, Tuning

FETCH_VERSION = AUDIO_VERSION
TUNING_VERSION = "1"
SEPARATE_VERSION = "1"
NOTES_VERSION = "1"
MELODY_VERSION = "1"
BEATS_VERSION = "1"
RHYTHM_VERSION = "1"
KEY_VERSION = "1"
SONG_VERSION = "1"

ANALYSIS_RATE = 22050
SEPARATION_RATE = 44100
QUIET_VOICE = 0.04  # below this share of the sound, the song has no singing to follow
DOUBTFUL = 0.4  # notes heard less clearly than this are marked for checking
TUNING_NOTICE = 15.0  # cents
LINKS_MISSING = (
    "Links can't be read yet: YouTube downloads come with the sheet music build phase. "
    "Download the song's audio and import the file instead."
)


# --- the recording itself -------------------------------------------------------------------


def _download(source: SongSource) -> tuple[Path, dict[str, Any]]:
    """The link's audio, downloaded once into the song's folder, and what the site says."""
    assert source.url is not None
    folder = files.audio_dir(source.folder)
    saved = next(folder.glob("download.*"), None)
    meta_file = folder / "download.json"
    try:
        from .. import links
    except ImportError:
        raise UnsupportedInput(LINKS_MISSING) from None
    if not hasattr(links, "download"):
        raise UnsupportedInput(LINKS_MISSING)
    meta: dict[str, Any] = {}
    if saved is None:
        got = Path(links.download(source.url, want="audio"))
        saved = folder / f"download{got.suffix}"
        if got != saved:
            saved.write_bytes(got.read_bytes())
        if hasattr(links, "info"):
            try:
                meta = dict(links.info(source.url) or {})
            except Exception:
                meta = {}
        import json

        meta_file.write_text(json.dumps({k: meta.get(k) for k in _META_KEYS}), encoding="utf-8")
    elif meta_file.exists():
        import json

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    return saved, meta


_META_KEYS = ("title", "track", "artist", "creator", "uploader", "channel")


def _audio(source: SongSource) -> bytes | Path:
    if source.kind == "audio":
        assert source.data is not None
        return source.data
    return _download(source)[0]


def _decode(source: SongSource, *, rate: int, channels: int = 1) -> np.ndarray:
    from .decode import decode

    return decode(_audio(source), rate=rate, channels=channels)


def fetch(source: SongSource) -> Recording:
    if source.kind == "audio":
        samples = _decode(source, rate=8000)
        stem = PurePath(source.name).stem if source.name else None
        title, artist = _title_artist(stem)
        return Recording(
            seconds=round(len(samples) / 8000, 2),
            title=title,
            artist=artist,
            source_name=source.name,
        )
    path, meta = _download(source)
    samples = _decode(source, rate=8000)
    return Recording(
        seconds=round(len(samples) / 8000, 2),
        title=meta.get("track") or meta.get("title"),
        artist=meta.get("artist")
        or meta.get("creator")
        or meta.get("uploader")
        or meta.get("channel"),
        source_name=source.url,
        file=path.name,
    )


def _title_artist(stem: str | None) -> tuple[str | None, str | None]:
    """'Artist - Title' file names, as music downloads are usually named."""
    if not stem:
        return None, None
    for sep in (" - ", " – ", " — "):
        if sep in stem:
            artist, title = stem.split(sep, 1)
            if artist.strip() and title.strip():
                return title.strip(), artist.strip()
    return stem.strip() or None, None


def check_tuning(source: SongSource, recording: Recording) -> Tuning:
    from .tuning import estimate_tuning

    del recording  # in the needs only so the recording is opened (and checked) first
    samples = _decode(source, rate=ANALYSIS_RATE)
    return estimate_tuning(samples[: ANALYSIS_RATE * 120], ANALYSIS_RATE)


# --- separated parts, kept as files --------------------------------------------------------


def _stem_paths(source: SongSource) -> tuple[Path, Path]:
    folder = files.audio_dir(source.folder)
    return (
        folder / f"voice-{SEPARATE_VERSION}.npy",
        folder / f"band-{SEPARATE_VERSION}.npy",
    )


def stems(source: SongSource) -> tuple[np.ndarray, np.ndarray]:
    """The voice and the band, mono at 22.05 kHz; separated now if not already."""
    voice_path, band_path = _stem_paths(source)
    if voice_path.exists() and band_path.exists():
        return files.load_array(voice_path), files.load_array(band_path)
    from .decode import resample
    from .separate import separate_voice

    mix = _decode(source, rate=SEPARATION_RATE, channels=2)
    voice = separate_voice(mix)
    band = (mix - voice).mean(axis=0)
    voice_mono = resample(voice.mean(axis=0), SEPARATION_RATE, ANALYSIS_RATE)
    band_mono = resample(band, SEPARATION_RATE, ANALYSIS_RATE)
    files.save_array(voice_path, voice_mono)
    files.save_array(band_path, band_mono)
    return voice_mono, band_mono


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def separate(source: SongSource, recording: Recording) -> Separation:
    del recording
    voice, band = stems(source)
    v, b = _rms(voice), _rms(band)
    share = v / (v + b) if v + b > 0 else 0.0
    return Separation(
        engine="mdx-net voc_ft",
        voice_share=round(share, 3),
        melody_from="voice" if share >= QUIET_VOICE else "mix",
    )


# --- notes, melody, beat --------------------------------------------------------------------


def _gate(events: list, voice: np.ndarray) -> list:
    """Drop notes where the voice part is all but silent (what leaks through in the intro)."""
    hop = ANALYSIS_RATE // 20
    n = len(voice) // hop
    if n == 0:
        return events
    env = np.sqrt(np.mean(voice[: n * hop].reshape(n, hop) ** 2, axis=1))
    loud = float(np.percentile(env, 95))
    if loud <= 0:
        return []
    keep = []
    for e in events:
        a, b = int(e.start * 20), max(int(e.start * 20) + 1, int(e.end * 20))
        if env[a:b].size and float(env[a:b].mean()) >= 0.12 * loud:
            keep.append(e)
    return keep


def find_notes(
    source: SongSource, recording: Recording, separation: Separation, tuning: Tuning
) -> Notes:
    from .decode import resample
    from .notes import find_notes as heard

    del recording
    voice, band = stems(source)
    samples = voice if separation.melody_from == "voice" else voice + band
    # retune to A = 440: lowering by c cents is playing it 2^(c/1200) times slower
    factor = 2 ** (tuning.cents / 1200) if abs(tuning.cents) >= 5 else 1.0
    retuned = resample(samples, ANALYSIS_RATE, ANALYSIS_RATE * factor)
    events = [
        e.model_copy(update={"start": round(e.start / factor, 4), "end": round(e.end / factor, 4)})
        for e in heard(retuned)
    ]
    if separation.melody_from == "voice":
        events = _gate(events, voice)
    return Notes(events=events)


def pick_melody(notes: Notes) -> Notes:
    from .melody import clean_melody

    return Notes(events=clean_melody(notes.events))


def find_beats(source: SongSource, recording: Recording, separation: Separation) -> Beats:
    from .beats import find_beats as beats_of

    del recording, separation
    voice, band = stems(source)
    return beats_of(band if _rms(band) > 0 else voice)


def fit_rhythm(melody: Notes, beats: Beats, recording: Recording) -> Rhythm:
    from .rhythm import to_rhythm

    return to_rhythm(melody.events, beats, recording.seconds)


def find_key(rhythm: Rhythm, beats: Beats, corrected: str | None = None) -> KeyResult | None:
    from .key import song_key

    return song_key(rhythm, beats, corrected)


# --- the Song -------------------------------------------------------------------------------


def build_song(
    source: SongSource,
    recording: Recording,
    separation: Separation,
    tuning: Tuning,
    rhythm: Rhythm,
    beats: Beats,
    key: KeyResult | None,
    corrections: Corrections | None = None,
) -> Song:
    corrections = corrections or Corrections()
    key_obj = key.concert.to_key() if key else None

    def spell(midi: int) -> str:
        octave = midi // 12 - 1
        if key_obj is not None:
            return str(key_obj.spell(midi % 12, octave=octave))
        return str(Key.from_pc(0, "major").spell(midi % 12, octave=octave))

    notes = [
        MelodyNote(
            concert=spell(n.pitch),
            start=n.start,
            length=n.length,
            confidence=n.confidence,
        )
        for n in rhythm.notes
    ]
    melody = Melody(
        notes=notes,
        octave_shift=corrections.melody_octave or 0,
        source="audio",
    )
    notices: list[Notice] = [
        Notice(
            code="melody_draft",
            message="The melody is a draft written down from the recording: check it by ear, "
            "the rhythm especially.",
        )
    ]
    doubtful = sum(1 for n in notes if (n.confidence or 0) < DOUBTFUL)
    if doubtful:
        notices.append(
            Notice(
                level="warning",
                code="doubtful_notes",
                message=f"{doubtful} of {len(notes)} notes were hard to hear; they are marked "
                "so you can check them.",
            )
        )
    if not notes:
        notices.append(
            Notice(level="warning", code="no_melody", message="No melody could be heard.")
        )
    if separation.melody_from == "mix":
        notices.append(
            Notice(
                code="no_voice",
                message="There is hardly any singing, so the melody was taken from the whole band.",
            )
        )
    if abs(tuning.cents) >= TUNING_NOTICE and tuning.confidence >= 0.3:
        side = "sharp" if tuning.cents > 0 else "flat"
        notices.append(
            Notice(
                code="tuning",
                message=f"The recording is tuned {abs(round(tuning.cents))} cents {side} of "
                "A = 440 Hz; tune with it to play along.",
            )
        )
    notices += _key_notices(key)
    fallback = (
        PurePath(recording.source_name).stem
        if source.kind == "audio" and recording.source_name
        else None
    )
    identity = Identity(
        title=corrections.title or recording.title or fallback,
        artist=corrections.artist or recording.artist,
        source="audio" if source.kind == "audio" else "link",
        source_name=recording.source_name,
        fingerprint=source.fingerprint,
    )
    return Song(
        identity=identity,
        key=key,
        melody=melody,
        timing=Timing(
            tempo=rhythm.tempo,
            time_signature=rhythm.time_signature,
            beat_times=beats.beat_times or None,
            downbeats=beats.downbeats or None,
        ),
        corrections=corrections,
        notes=notices,
    )


def write_for(song: Song, view_settings: ViewSettings) -> Song:
    """The music core's view, with the melody moved by octaves to sit in the player's
    comfortable range (unless the player chose the octave)."""
    if song.melody is not None and song.melody.notes and song.corrections.melody_octave is None:
        inst = get_instrument(view_settings.instrument)
        key = song.key.concert.to_key() if song.key else None
        tr = Transposition.for_key(inst, key)
        low = (
            Pitch.parse(view_settings.comfortable_low)
            if view_settings.comfortable_low
            else inst.comfortable_low
        )
        high = (
            Pitch.parse(view_settings.comfortable_high)
            if view_settings.comfortable_high
            else inst.comfortable_high
        )
        written = [
            Pitch.parse(n.concert).transpose(tr.interval) for n in song.melody.notes if n.concert
        ]
        fit = fit_melody(written, low, high, lowest=inst.lowest, highest=inst.highest)
        song = song.model_copy(
            update={"melody": song.melody.model_copy(update={"octave_shift": fit.octaves})}
        )
    return apply_instrument(
        song,
        view_settings.instrument,
        comfortable_low=view_settings.comfortable_low,
        comfortable_high=view_settings.comfortable_high,
    )


SONG = Pipeline(
    "song",
    [
        Step("fetch", FETCH_VERSION, ("source",), fetch, Recording),
        Step("tuning", TUNING_VERSION, ("source", "fetch"), check_tuning, Tuning),
        Step("separate", SEPARATE_VERSION, ("source", "fetch"), separate, Separation),
        Step(
            "notes",
            NOTES_VERSION,
            ("source", "fetch", "separate", "tuning"),
            find_notes,
            Notes,
        ),
        Step("melody", MELODY_VERSION, ("notes",), pick_melody, Notes),
        Step("beats", BEATS_VERSION, ("source", "fetch", "separate"), find_beats, Beats),
        Step("rhythm", RHYTHM_VERSION, ("melody", "beats", "fetch"), fit_rhythm, Rhythm),
        Step("key", KEY_VERSION, ("rhythm", "beats", "key_fix"), find_key, KeyResult | None),
        Step(
            "song",
            SONG_VERSION,
            ("source", "fetch", "separate", "tuning", "rhythm", "beats", "key", "corrections"),
            build_song,
            Song,
        ),
        Step("view", VIEW_VERSION, ("song", "view_settings"), write_for, Song),
    ],
)

LABELS: Mapping[str, str] = {
    "fetch": "Opening the recording",
    "tuning": "Checking the tuning",
    "separate": "Separating the voice (this takes a few minutes)",
    "notes": "Finding the notes",
    "melody": "Picking out the melody",
    "beats": "Finding the beat",
    "rhythm": "Fitting the notes to the beat",
    "key": "Finding the key",
    "song": "Putting the song together",
    "view": "Writing it for your instrument",
}


def analyze_song(
    source: SongSource | str | os.PathLike[str],
    *,
    corrections: Corrections | None = None,
    view: ViewSettings | None = None,
    cache: Cache | None = None,
    on_step: StepEvent | None = None,
) -> Song:
    """A recording in, the finished Song out (written for the player's instrument).

    ``source`` is a song source, a link, or an audio file path.
    """
    if isinstance(source, os.PathLike):
        path = Path(source)
        source = SongSource("audio", path.read_bytes(), path.name)
    elif isinstance(source, str):
        source = SongSource("link", url=source)
    corrections = corrections or Corrections()
    inputs = {
        "source": source,
        "key_fix": corrections.key,
        "corrections": corrections,
        "view_settings": view or ViewSettings(),
    }
    song: Song = SONG.run(inputs, cache=cache, on_step=on_step)["view"]
    return song.model_copy(update={"versions": SONG.versions})
