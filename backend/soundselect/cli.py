"""The command line: ``soundselect sheet song.txt`` and friends.

Everything the app does is reachable here first; the web app calls the same functions.
"""

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .core.instruments import DEFAULT_INSTRUMENT, INSTRUMENTS
from .core.keys import Key
from .core.names import DEFAULT_NAMES, NAME_SYSTEMS, note_name
from .core.pitch import Pitch
from .core.song import Corrections, Song
from .core.view import with_names
from .pipeline.chord_sheet import analyze_sheet
from .render.text import song_text
from .settings import ViewSettings
from .sheets.readers import SheetInput, UnsupportedInput

app = typer.Typer(
    name="soundselect",
    help="SoundSelect: chord sheets written for your sax, with the key's pentatonic on the staff.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

InstrumentChoice = Enum("InstrumentChoice", {i: i for i in INSTRUMENTS}, type=str)
NamesChoice = Enum("NamesChoice", {n: n for n in NAME_SYSTEMS}, type=str)
FORMATS = ("html", "pdf", "json", "musicxml", "txt")

InstrumentOpt = Annotated[
    InstrumentChoice,
    typer.Option("--instrument", "-i", help="Instrument to write the music for."),
]
NamesOpt = Annotated[
    NamesChoice,
    typer.Option("--names", "-n", help="Note names shown under the notes and in text."),
]
KeyOpt = Annotated[
    str | None,
    typer.Option(
        "--key", "-k", help="The song's concert key, when you know it: 'Bb', 'Gm', 'ля минор'."
    ),
]


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)


def _check_key(key: str | None) -> None:
    if key is None:
        return
    try:
        Key.parse(key)
    except ValueError:
        raise typer.BadParameter(
            f"can't read {key!r} as a key; try 'Bb', 'F#m' or 'C minor'", param_hint="--key"
        ) from None


def _read_input(name: str) -> SheetInput:
    if name == "-":
        return SheetInput(sys.stdin.read())
    path = Path(name)
    if not path.is_file():
        raise FileNotFoundError(f"no file named {name}")
    return SheetInput.from_path(path)


def _write_outputs(song: Song, names: str, written: bool, targets: dict[str, Path]) -> bool:
    """Write each requested format; returns False when one could not be made."""
    ok = True
    for fmt, path in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if fmt == "html":
                from .render.page import song_page

                path.write_text(song_page(song, names, written=written), encoding="utf-8")
            elif fmt == "pdf":
                from .render.page import song_page
                from .render.pdf import html_to_pdf

                path.write_bytes(html_to_pdf(song_page(song, names, written=written)))
            elif fmt == "json":
                path.write_text(
                    with_names(song, names).model_dump_json(indent=2) + "\n", encoding="utf-8"
                )
            elif fmt == "musicxml":
                from .render.scores import song_score

                xml = song_score(song, "all", names=names, view="written" if written else "concert")
                path.write_text(xml or "", encoding="utf-8")
            elif fmt == "txt":
                path.write_text(song_text(song, names, written=written), encoding="utf-8")
        except Exception as exc:  # one failed format should not stop the others
            _fail(f"Could not write {path}: {exc}")
            ok = False
            continue
        typer.echo(f"Wrote {path}", err=True)
    return ok


@app.command()
def sheet(
    files: Annotated[
        list[str],
        typer.Argument(
            help="Chord sheet files (.txt, ChordPro), or - for pasted text.",
            show_default=False,
            metavar="FILES...",
        ),
    ],
    instrument: InstrumentOpt = InstrumentChoice[DEFAULT_INSTRUMENT],
    names: NamesOpt = NamesChoice[DEFAULT_NAMES],
    key: KeyOpt = None,
    capo: Annotated[
        int | None, typer.Option(help="Capo fret, when the sheet has none or the wrong one.")
    ] = None,
    title: Annotated[str | None, typer.Option(help="Song title (one sheet only).")] = None,
    artist: Annotated[str | None, typer.Option(help="Artist (one sheet only).")] = None,
    html: Annotated[Path | None, typer.Option(help="Write the song page here.")] = None,
    pdf: Annotated[Path | None, typer.Option(help="Write the song page as a PDF here.")] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write the Song result as JSON here.")
    ] = None,
    musicxml: Annotated[
        Path | None, typer.Option(help="Write the scales and chords as MusicXML here.")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Folder for the outputs of every sheet, named after each file."),
    ] = None,
    formats: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Formats to write into --out: html, pdf, json, musicxml, txt (comma separated).",
        ),
    ] = "html,pdf",
    concert: Annotated[
        bool, typer.Option(help="Show concert pitch instead of the instrument's notes.")
    ] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Print nothing but errors.")] = False,
) -> None:
    """Read chord sheets and write them for your instrument: key, pentatonic, scales, chords."""
    _check_key(key)
    single_targets = {"html": html, "pdf": pdf, "json": json_out, "musicxml": musicxml}
    single_targets = {k: v for k, v in single_targets.items() if v is not None}
    if len(files) > 1 and single_targets:
        raise typer.BadParameter("with several sheets, use --out FOLDER (and --format)")
    if len(files) > 1 and (title or artist):
        raise typer.BadParameter("--title and --artist work with one sheet at a time")
    chosen = [f.strip().lower() for f in formats.split(",") if f.strip()]
    unknown = [f for f in chosen if f not in FORMATS]
    if unknown:
        raise typer.BadParameter(
            f"unknown format {', '.join(unknown)}; use {', '.join(FORMATS)}", param_hint="--format"
        )

    corrections = Corrections(title=title, artist=artist, key=key, capo=capo)
    view = ViewSettings(instrument=instrument.value)
    written = not concert
    ok = True
    for i, name in enumerate(files):
        try:
            source = _read_input(name)
            song = analyze_sheet(source, corrections=corrections, view=view)
        except (FileNotFoundError, UnsupportedInput, ValueError) as exc:
            _fail(f"{name}: {exc}")
            ok = False
            continue
        if not quiet:
            if i:
                typer.echo("\n" + "─" * 60 + "\n")
            typer.echo(song_text(song, names.value, written=written, chart=len(files) == 1))
        targets = dict(single_targets)
        if out is not None:
            stem = Path(name).stem if name != "-" else (song.identity.title or "song")
            targets.update({fmt: out / f"{stem}.{fmt}" for fmt in chosen})
        ok = _write_outputs(song, names.value, written, targets) and ok
    if not ok:
        raise typer.Exit(1)


@app.command()
def chords(
    progression: Annotated[
        list[str],
        typer.Argument(
            help='Chords in order, e.g. "Am F C G".', show_default=False, metavar="CHORDS..."
        ),
    ],
    instrument: InstrumentOpt = InstrumentChoice[DEFAULT_INSTRUMENT],
    names: NamesOpt = NamesChoice[DEFAULT_NAMES],
    key: KeyOpt = None,
    concert: Annotated[
        bool, typer.Option(help="Show concert pitch instead of the instrument's notes.")
    ] = False,
) -> None:
    """Key, pentatonic and a scale for each chord, from a list of chords without lyrics."""
    _check_key(key)
    text = " ".join(progression).replace(",", " ")
    song = analyze_sheet(
        SheetInput(text, "chords"),
        corrections=Corrections(key=key, title="Chords"),
        view=ViewSettings(instrument=instrument.value),
    )
    if not song.chords:
        _fail("No chords found in that list.")
        raise typer.Exit(1)
    typer.echo(song_text(song, names.value, written=not concert, chart=False))


_INTERVAL_WORDS = {
    "P1": "the same as concert pitch",
    "M2": "a whole step above concert pitch",
    "M6": "a major sixth above concert pitch (a minor third down, an octave higher)",
    "M9": "a major ninth above concert pitch",
    "M13": "an octave and a major sixth above concert pitch",
}


@app.command()
def instruments() -> None:
    """The instruments SoundSelect writes for, and how each reads music."""
    for inst in INSTRUMENTS.values():
        typer.echo(f"{inst.id:<13} {inst.display_name}")
        words = _INTERVAL_WORDS.get(inst.interval.name, inst.interval.name)
        typer.echo(f"{'':<13} written {words}")
        if inst.id != "concert":
            low, high = inst.lowest.display(octave=True), inst.highest.display(octave=True)
            c_low = inst.comfortable_low.display(octave=True)
            c_high = inst.comfortable_high.display(octave=True)
            typer.echo(f"{'':<13} range {low}–{high}, comfortable {c_low}–{c_high} (written)")


@app.command("names")
def names_command() -> None:
    """Note names in every system SoundSelect can show."""
    systems = ("letters", "russian", "solfege", "german")
    typer.echo("  ".join(s.ljust(16) for s in systems).rstrip())
    for letter in "CDEFGAB":
        for alter in (0, 1, -1):
            p = Pitch(letter, alter)
            cells = [note_name(p, s, long=s == "russian") for s in systems]  # type: ignore[arg-type]
            typer.echo("  ".join(c.ljust(16) for c in cells).rstrip())


@app.command()
def schema(
    out: Annotated[Path | None, typer.Option(help="Write the schema to this file.")] = None,
) -> None:
    """The JSON Schema of the Song result, the contract between back end and front end."""
    text = json.dumps(Song.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {out}", err=True)


@app.command()
def version() -> None:
    """Show the SoundSelect version."""
    typer.echo(f"SoundSelect {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
