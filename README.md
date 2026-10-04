# SoundSelect

A personal toolkit for alto saxophone players. Every tool shows its results the same way: on the staff, written for alto sax, with the note names you choose (letters or Russian до, ре, ми).

Three tools share one music core:

- **Chord sheets.** Paste text or upload a PDF or photos of chord and lyrics sheets. You get the pentatonic of the song's key first, written for alto, then the key, every chord rewritten for alto, and scales for the whole song and for each chord.
- **Songs.** Upload an audio file or paste a YouTube link. You get the main melody written for alto on the staff, with the same key and scale information.
- **Sheet music from videos.** Screenshots of a sheet-music video, or its link, become full pages and a clean PDF in concert pitch and for alto.

The full system plan (phases, the Song result, the API) is in the project's plan document. Each build phase arrives as a pull request.

## What works now (Phase 1)

The chord sheet tool as an app you open in the browser. Paste a chord sheet or choose text and
PDF files (several at once make a batch, one song each). Each song gets its page: the key's
pentatonic for alto first, on the staff, then the key, the other scales, every chord rewritten
for alto with a scale to play over it, and the chord chart. Every song is kept in your library.

- **Fix** what was read wrong (the key, the capo, a chord, the title) and only the steps your fix
  touches run again.
- **Switch** note names (до ре ми or C D E) and concert pitch on the song page; set your
  instrument and comfortable range once in Settings.
- **Download** a song as PDF, or a whole batch as one songbook PDF with a contents page.
- The same features are a web API under `/api/v1` for the real front end (see
  [docs/api.md](docs/api.md)).

Photos of sheets, sheet music from videos and songs from YouTube come in the next phases; the
app already accepts them and says when each arrives.

## Running it

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.11 by itself). For PDFs you
also need the Pango library: `brew install pango` on a Mac.

```sh
uv sync
uv run soundselect serve          # then open http://127.0.0.1:8000
```

Your songs are kept in `~/.soundselect` (set `SOUNDSELECT_HOME` or `--home` to use another
folder). The app answers only this computer. Stop it with Ctrl+C; anything still being read
carries on the next time it starts.

The command line does the same work without the browser:

```sh
uv run soundselect add song.txt songbook.pdf             # add sheets to your library
uv run soundselect songs лето                            # find songs in your library
uv run soundselect sheet song.txt                        # one-off: key, pentatonic, chords, chart
uv run soundselect sheet song.txt --html song.html --pdf song.pdf
uv run soundselect sheet *.txt --out pages/              # a page and a PDF for each sheet
uv run soundselect chords Am F C G                       # just a list of chords
uv run soundselect sheet song.txt --key "ля минор"       # when the key guess is wrong
uv run soundselect sheet song.txt --names letters        # letters instead of до, ре, ми
```

Other options: `--instrument` (alto_sax, tenor_sax, soprano_sax, baritone_sax, concert),
`--names` (russian, letters, both, solfege, german, none), `--capo`, `--concert` for concert
pitch, `--json` for the full Song result and `--musicxml` for the staves.
`uv run soundselect --help` lists everything.

## Layout

```
backend/soundselect/
  core/        the music core: pitches, keys, chords, scales, instruments, note names, the Song result
  sheets/      chord sheets: readers per input kind, line sorting, chord parsing, capo, key
  pipeline/    the step runner with saved outputs, and the chord sheet pipeline
  render/      MusicXML, staff drawing (Verovio), chord chart, song page, songbook, PDF, text
  store/       the library: songs, imports and their jobs, settings (SQLite in one folder)
  jobs/        background jobs (Huey on SQLite), run as threads inside the app
  api/         the web API under /api/v1 (FastAPI)
  web/         the simple screens, until the real front end arrives
  imports.py   which tool reads each pasted text, file and link
  service.py   what the app does with songs, shared by the API, screens, jobs and command line
  cli.py       the command line
  sheetmusic/  Phase 3: sheet music from screenshots and videos
  audio/       Phase 4: songs from links and audio files
backend/tests/ tests, with sample sheets in tests/data/ (test PDFs and how they were made in pdf/)
docs/          api.md (how the front end uses the API), openapi.json (its exact description),
               song.schema.json (the Song result) and decisions.md
```

## Checks

```sh
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

After changing the Song model or the API, regenerate their descriptions (a test checks that
they are current):

```sh
uv run soundselect schema --out docs/song.schema.json
uv run soundselect openapi --out docs/openapi.json
```
