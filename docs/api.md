# The SoundSelect API

How the front end talks to the back end. Every call is under `/api/v1`. The exact description
of each call, with every field, is published by the app at `/api/v1/openapi.json` (browse it at
`/api/v1/docs`) and kept in [openapi.json](openapi.json); a test fails when the two drift. The
Song result itself is described in [song.schema.json](song.schema.json).

Start the back end with `uv run soundselect serve` (http://127.0.0.1:8000). The Vite dev server
at `localhost:5173` may call it from the browser; add other origins with
`SOUNDSELECT_CORS_ORIGINS=https://a.example,https://b.example`.

## Errors

Every error the API answers on purpose looks the same, with a message written for the player
that can be shown as it is:

```json
{"detail": {"code": "bad_request", "message": "Can't read 'Q' as a key. Try 'Bb', 'F#m' or 'ля минор'."}}
```

| Status | Code | When |
|---|---|---|
| 400 | `bad_request` | Something in the request can't be used: an unknown key or instrument, nothing to import |
| 404 | `not_found` | No such song, batch, job, page or chord |
| 501 | `not_built` | A call for a later build phase (MIDI export, YouTube search) |
| 503 | `pdf_unavailable` | PDF output asked for on a machine without the Pango library |

A request FastAPI can't parse at all (a missing field, a number out of range) gets its usual
422 answer, with `detail` as a list.

## Importing

`POST /imports` takes `multipart/form-data` and answers at once with `202` and a **Batch**: one
job per song. Each pasted text, file and link is one song.

| Field | |
|---|---|
| `text` | Pasted chord sheet; repeat the field for several |
| `files` | Text (`.txt`, `.cho`, `.crd`, ...) and PDF chord sheets; repeat for several |
| `link` | A link; repeat for several |
| `instrument` | Write the songs for this instrument instead of the default |
| `title`, `artist`, `key`, `capo` | Corrections for a single song (ignored in a batch of several) |
| `groups` | JSON, e.g. `[[0, 1]]`: files that make one song (photo phase) |
| `link_mode` | `auto`, `sound` or `sheet_music` (link phases) |

Every item gets a job, including kinds a later phase reads (photos, audio, video, links): their
job has already failed with a message saying when they arrive, so the screen can show every
item the same way. A file nothing can read fails the same way ("SoundSelect can't read .docx
files..."), and so does an empty file. The same contents imported again come back as the song
already in the library (`reused: true`), unless the import carries corrections.

A job's `status` is `queued`, `running`, `done` (with `song_id`) or `failed` (with `error`).
While it runs, `step` names the step, `step_label` says it in words ("Finding the key"), and
`step_number`, `step_count` and `progress` (0 to 1) show how far along it is. A batch is
`done` once every job has finished, even when some failed; `done` and `failed` count them.

### Following progress

`GET /batches/{id}/events` is a Server-Sent Events stream for the whole batch:

```js
const events = new EventSource(`/api/v1/batches/${batch.id}/events`);
events.addEventListener("job", (e) => showJob(JSON.parse(e.data)));     // a Job, on each change
events.addEventListener("batch", (e) => showCounts(JSON.parse(e.data))); // the Batch, when counts change
events.addEventListener("end", () => events.close());                    // every job has finished
```

The stream starts with every job as it is, so a page opened late catches up. `GET
/jobs/{id}/events` does the same for one job. Without streams, poll `GET /batches/{id}` or
`GET /jobs/{id}`; each job's `rev` goes up with every change.

## Songs

- `GET /songs?q=&sort=recent|title&limit=&offset=&instrument=`: the library. Each entry has the
  concert key, the key written for the instrument and the key's pentatonic as written. `q`
  matches every word in title, artist, file name and lyrics.
- `GET /songs/{id}?instrument=&names=`: the full **Song result**, written for the instrument,
  with `names` (a table of note names for every pitch in the song) in the asked system. For a
  PDF, each `source_pages` entry gets its `image` URL.
- `PATCH /songs/{id}`: save corrections and get the song back once the steps they touch have
  run again (a key fix doesn't read the sheet again). Send only what changes; `null` clears a
  correction; `chords` is the whole list of chord fixes. An empty body makes the song again
  with the newest version of every step, keeping the corrections.

  ```json
  {"key": "Gm", "capo": 2, "title": "Летний вечер",
   "chords": [{"original": "F/A", "to": "F"}, {"original": "Bb", "to": "", "line": 3, "index": 0}]}
  ```

  A chord fix without `line` and `index` changes every occurrence; `to: ""` removes the chord.
- `DELETE /songs/{id}`: remove it from the library (204).

Instruments and note names are applied when a song is asked for: the saved song never changes
when you look at it for another instrument or with other names.

## The staff

`GET /songs/{id}/score?part=&names=&view=written|concert&instrument=&format=musicxml|svg`
gives one part of the song on the staff:

| `part` | |
|---|---|
| `headline` | The key's pentatonic, the headline result |
| `scales` | Every whole-song scale |
| `chord_scales` | A scale over each chord |
| `chord_notes` | Each chord's notes |
| `all` | All of the above |
| `chord` | One chord (`chord=Gm`, its concert symbol) with its notes and scale |

MusicXML is what the front end draws with Verovio in the browser, so the music reflows to the
screen; `svg` is the server's drawing of it. Note names, when asked for, sit under the notes.

## Downloads

- `GET /songs/{id}/export?format=pdf|html|musicxml|json|txt&names=&view=&instrument=`: the song
  page as PDF or HTML, the staves as MusicXML (opens in MuseScore), the Song result as JSON, or
  a text summary. MIDI answers 501 until it is built.
- `GET /batches/{id}/songbook?format=pdf|html&names=&view=&instrument=`: the batch's finished
  songs in one document with a contents page, each song starting a new page.

## Source pages

`GET /songs/{id}/pages` lists the source's pages (`image` URLs, with width and height) and where
each line of the song sits on them: `line` counts lines across the whole song, as chord fixes
do, and `box` is `x0, y0, x1, y1` in pixels of that page image. `GET
/songs/{id}/pages/{n}.png` is the page itself (144 dpi). Pasted text has no pages.

## Settings and the app

- `GET /settings`, `PUT /settings`: the default instrument, note names (`russian`, `letters`,
  `both`, `solfege`, `german`, `none`), comfortable range (written notes with octave, at least an
  octave apart) and photo reader.
- `GET /instruments`: the instruments songs can be written for, with their ranges.
- `GET /health`: whether the app is up, how many songs and waiting jobs there are, and which
  tools are installed (`pdf_output` is false without Pango).
- `GET /search?q=`: finding a song on YouTube by name, which comes with the song tool (501 now).
