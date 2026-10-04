"""The player's defaults: instrument, note names, comfortable range and readers."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .core.instruments import DEFAULT_INSTRUMENT, get_instrument
from .core.names import DEFAULT_NAMES, NameSystem
from .core.pitch import Pitch
from .core.song import Model


class ViewSettings(Model):
    """What the music core needs to write a song for the player."""

    instrument: str = DEFAULT_INSTRUMENT
    comfortable_low: str | None = Field(None, description="Written note; instrument default.")
    comfortable_high: str | None = Field(None, description="Written note; instrument default.")

    @field_validator("instrument")
    @classmethod
    def _known_instrument(cls, value: str) -> str:
        get_instrument(value)
        return value

    @field_validator("comfortable_low", "comfortable_high")
    @classmethod
    def _note_with_octave(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        pitch = Pitch.parse(value)
        if pitch.octave is None:
            raise ValueError(f"give {value!r} with its octave, like 'C4'")
        return str(pitch)

    @model_validator(mode="after")
    def _low_below_high(self) -> ViewSettings:
        if self.comfortable_low and self.comfortable_high:
            low, high = Pitch.parse(self.comfortable_low), Pitch.parse(self.comfortable_high)
            if low.midi + 12 > high.midi:
                raise ValueError("the comfortable range needs at least an octave, low to high")
        return self


class Settings(ViewSettings):
    names: NameSystem = DEFAULT_NAMES
    photo_reader: Literal["local", "ai"] = "local"

    def view(self, instrument: str | None = None) -> ViewSettings:
        """The view settings, for another instrument when one is given."""
        return ViewSettings(
            instrument=instrument or self.instrument,
            comfortable_low=self.comfortable_low,
            comfortable_high=self.comfortable_high,
        )
