# The SoundSelect API

How the front end talks to the back end. Every call is under `/api/v1`. The exact description
of each call, with every field, is published by the app at `/api/v1/openapi.json` (browse it at
`/api/v1/docs`) and kept in [openapi.json](openapi.json); a test fails when the two drift. The
Song result itself is described in [song.schema.json](song.schema.json).

Start the back end with `uv run soundselect serve` (http://127.0.0.1:8000). The Vite dev server
at `localhost:5173` may call it from the browser; add other origins with
`SOUNDSELECT_CORS_ORIGINS=https://a.example,https://b.example`.

The back end only answers requests addressed to 127.0.0.1, localhost or ::1; add other host
names with `SOUNDSELECT_ALLOWED_HOSTS=mymac.local`. Others get 400 `bad_host`. A POST, PUT,
PATCH or DELETE whose `Origin` is neither the app itself nor an allowed CORS origin gets 403
`bad_origin`.

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
job per song or piece. Each pasted text, file and link is one, except for groups and sheet
music screenshots (below).

| Field | |
|---|---|
| `text` | Pasted chord sheet; repeat the field for several |
| `files` | Text (`.txt`, `.cho`, `.crd`, ...), PDF and photos of chord sheets; screenshots and videos of sheet music; audio files. Repeat for several |
| `link` | A link (YouTube and others); repeat for several |
| `instrument` | Write the songs for this instrument instead of the default |
| `title`, `artist`, `key`, `capo` | Corrections for a single song (ignored in a batch of several) |
| `groups` | JSON, e.g. `[[0, 1]]`: files that make one song or piece, by position from 0 |
| `image_mode` | What image files are: `auto` (look for staves), `chord_sheet` or `sheet_music` |
| `link_mode` | What a link is read for: `auto`, `sound` (the song tool) or `sheet_music` |

Which tool reads each item:

- Text and PDF files are chord sheets.
- Image files are photos of chord sheets, or screenshots of sheet music when `image_mode` is
  `sheet_music`, or when it is `auto` and the sheet music reader sees staves in the image.
- Videos are sheet music; audio files are songs.
- A link is read for its sound with `link_mode=sound` and for its sheet music with
  `sheet_music`. With `auto` it goes to sheet music while that is the only one built, and to
  songs otherwise; Phase 4 decides it by looking at the link once both exist.

A group always means "these files make one song or piece", read in the group's order. Its files
must all go to the same tool, and that tool must read several files at once; a group that mixes
chord sheets and sheet music fails with "A group can't mix chord sheets and sheet music."
Sheet music screenshots in no group are the pages of one piece: they make one job together, at
the place of the first, named "first.png and 2 more". Every other file is one song or piece.

Every item gets a job, including kinds a later phase reads (photos, audio, video, links): their
job has already failed with a message saying when they arrive, so the screen can show every
item the same way. When a tool is built but its extra packages aren't installed, the message
says to run `uv sync --all-extras`. A file nothing can read fails the same way ("SoundSelect can't read .docx
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
  `b_is_flat` says what a plain B on the sheet means: `true` B♭ (as on Russian and German
  sheets), `false` B natural, `null` read from the sheet (a sheet with H means B♭ by B; a Russian
  sheet whose chords fit B♭ much better gets a `b_flat_guess` notice).
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
| `melody` | The melody (songs from recordings) in bars of its time signature, with rests, ties and the tempo; doubtful notes are red |
| `all` | All of the above, the melody first |
| `chord` | One chord (`chord=Gm`, its concert symbol) with its notes and scale |
| `sheet` | Sheet music only: the whole piece as read from the pictures, drawn fresh |

MusicXML is what the front end draws with Verovio in the browser, so the music reflows to the
screen; `svg` is the server's drawing of it. Note names, when asked for, sit under the notes.

## Downloads

- `GET /songs/{id}/export?format=pdf|html|musicxml|json|txt&names=&view=&instrument=`: the song
  page as PDF or HTML, the staves as MusicXML (opens in MuseScore), the Song result as JSON, or
  a text summary. MIDI answers 501 until it is built.
- Sheet music (a song with `sheet_music`): `format=pdf` is the piece drawn fresh on A4 pages,
  written for the instrument (or `view=concert`) with note names under the notes when asked for;
  `format=musicxml` is that piece; `format=clean` is the clean copy, the joined screenshots on A4
  pages as the video showed them. Other songs answer 404 to `clean`.
- `GET /batches/{id}/songbook?format=pdf|html&names=&view=&instrument=`: the batch's finished
  songs in one document with a contents page, each song starting a new page.

## Source pages

`GET /songs/{id}/pages` lists the source's pages (`image` URLs, with width and height) and where
each line of the song sits on them: `line` counts lines across the whole song, as chord fixes
do, and `box` is `x0, y0, x1, y1` in pixels of that page image. `GET
/songs/{id}/pages/{n}.png` is the page itself (144 dpi). Pages are numbered across the song's
files in order: a two-page PDF and then a photo give pages 0, 1 and 2. Pasted text has no
pages. For sheet music the pages are the clean copy (300 dpi) and each line is one line of
music (a system).

## Settings and the app

- `GET /settings`, `PUT /settings`: the default instrument, note names (`russian`, `letters`,
  `both`, `solfege`, `german`, `none`), comfortable range (written notes with octave, at least an
  octave apart) and photo reader.
- `GET /instruments`: the instruments songs can be written for, with their ranges.
- `GET /health`: whether the app is up, how many songs and waiting jobs there are, and which
  tools are installed: `pdf_output` (false without Pango), `pdf_reading`, `photo_reading`,
  `sheet_music` (screenshots and videos), `audio` (songs from audio) and `links` (yt-dlp is
  installed, something reads links, and Deno, which YouTube needs, is on the app's `PATH`).
- `GET /search?q=`: finding a song on YouTube by name, which comes with the song tool (501 now).
