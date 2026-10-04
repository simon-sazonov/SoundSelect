"""The player's defaults: instrument, note names, comfortable range and readers."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .core.instruments import DEFAULT_INSTRUMENT
from .core.names import DEFAULT_NAMES, NameSystem
from .core.song import Model


class ViewSettings(Model):
    """What the music core needs to write a song for the player."""

    instrument: str = DEFAULT_INSTRUMENT
    comfortable_low: str | None = Field(None, description="Written note; instrument default.")
    comfortable_high: str | None = Field(None, description="Written note; instrument default.")


class Settings(ViewSettings):
    names: NameSystem = DEFAULT_NAMES
    photo_reader: Literal["local", "ai"] = "local"

    def view(self) -> ViewSettings:
        return ViewSettings(
            instrument=self.instrument,
            comfortable_low=self.comfortable_low,
            comfortable_high=self.comfortable_high,
        )
