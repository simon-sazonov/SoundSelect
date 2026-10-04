"""Where the song tool keeps its large files: downloaded models and each song's separated audio.

Everything sits in the library folder (``~/.soundselect`` unless ``SOUNDSELECT_HOME`` says
otherwise): ``models/`` holds the voice and note models, downloaded once and checked against
their SHA-256; ``audio/<song key>/`` holds what separating one recording made, so changing a
correction never separates the song again.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..store.library import default_home

MODELS_ENV = "SOUNDSELECT_MODELS"  # a folder of models to use instead of downloading them


@dataclass(frozen=True)
class ModelFile:
    name: str
    url: str
    sha256: str
    size: int
    what: str  # for messages: "the voice model"


VOICE_MODEL = ModelFile(
    "UVR-MDX-NET-Voc_FT.onnx",
    "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/"
    "UVR-MDX-NET-Voc_FT.onnx",
    "534b2070fcc7df514b13ef660dc8cbb328679c2374d04354a5c42bb14ecce111",
    66_762_490,
    "the voice separation model",
)
NOTE_MODEL = ModelFile(
    "basic-pitch-nmp.onnx",
    "https://raw.githubusercontent.com/spotify/basic-pitch/v0.4.0/"
    "basic_pitch/saved_models/icassp_2022/nmp.onnx",
    "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec",
    230_444,
    "the note model",
)
MODELS = (VOICE_MODEL, NOTE_MODEL)


class ModelUnavailable(RuntimeError):
    """A model could not be downloaded or did not match its checksum."""


def models_dir() -> Path:
    return Path(os.environ.get(MODELS_ENV) or default_home() / "models").expanduser()


def audio_dir(key: str) -> Path:
    path = default_home() / "audio" / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def model_path(model: ModelFile) -> Path:
    """The model file, downloaded the first time it is needed."""
    path = models_dir() / model.name
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{model.name}.{secrets.token_hex(4)}.part")
    try:
        with urllib.request.urlopen(model.url, timeout=60) as response, tmp.open("wb") as out:
            while block := response.read(1 << 20):
                out.write(block)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ModelUnavailable(
            f"Couldn't download {model.what} ({exc}). Check the internet connection and try "
            "again; it is downloaded once."
        ) from exc
    if _sha256(tmp) != model.sha256:
        tmp.unlink(missing_ok=True)
        raise ModelUnavailable(f"The download of {model.what} was damaged; try again.")
    tmp.replace(path)
    return path


def save_array(path: Path, data: np.ndarray) -> None:
    """Save audio as half-precision floats (half the disk, far below what anyone can hear)."""
    tmp = path.with_name(f"{path.stem}.{secrets.token_hex(4)}.tmp.npy")
    np.save(tmp, data.astype(np.float16))
    tmp.replace(path)


def load_array(path: Path) -> np.ndarray:
    return np.load(path).astype(np.float32)
