"""Pasted text and .txt / ChordPro files."""

from __future__ import annotations

from ..model import SheetText, TextLine
from . import SheetInput, register

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍﻿⁠"), None)


def decode_text(data: bytes) -> str:
    """UTF-8 first; Russian files saved on Windows are often cp1251."""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def clean_lines(text: str) -> list[str]:
    """Split into lines, keeping each character's column so chords stay over their syllables."""
    text = text.translate(_INVISIBLE).replace("\r\n", "\n").replace("\r", "\n")
    return [line.replace(" ", " ").expandtabs(8).rstrip() for line in text.split("\n")]


@register("text")
def read_text(inp: SheetInput) -> SheetText:
    text = inp.data if isinstance(inp.data, str) else decode_text(inp.data)
    return SheetText(
        lines=[TextLine(text=line) for line in clean_lines(text)],
        source="text",
        source_name=inp.name,
        fingerprint=inp.fingerprint("text"),
    )
