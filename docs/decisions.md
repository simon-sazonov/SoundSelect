# Decisions made while building

Choices the plan left open or that differ from it, with the reason for each. Newest at the bottom.

## Phase 0

**Own pitch core instead of music21, for now.** The plan names music21 for the music model.
Phase 0 needs only spelled pitches, intervals, keys and chords, so a small exact module
(`core/pitch.py`, `core/keys.py`) does it, with tests for every key and every instrument. It
starts instantly and pulls in nothing heavy. music21 joins in Phase 3 (reading MusicXML from
sheet music) and Phase 4 (melody to notation), where its parsers and rhythm tools pay off.

**PDF with WeasyPrint.** The song page is one HTML file and WeasyPrint prints that same HTML,
so the page and the PDF always match. It needs the Pango library from the system
(`brew install pango` on a Mac); everything else works without it. Verovio's SVG needed two
changes to print: the inner drawing fills its outer picture, and the music font is included
once per page instead of inside every staff (this cut a page from 2.2 MB to about 200 KB).

**Written keys never need more than six sharps or flats.** When a major sixth up would give
seven or more (concert E major would be C♯ major for alto), the whole song moves by the
enharmonic interval one letter lower instead (a diminished seventh, giving D♭ major). Every
note and chord uses the same interval, so nothing is spelled against the key signature.

**Chord roots keep their spelling** unless they fall far outside the key: A♯ in F major
becomes B♭, but C♯m in E major stays C♯m.

**Finding the key.** Each of the 24 keys is scored from the chords: chords in the key count
fully, common borrowed chords partly, the first chord strongly and the last chord at half
weight (a short loop like Am F C G stops wherever it wraps around), plus V to I moves. When
only major versus minor is unsure (A minor or C major), the page says the pentatonic notes are
the same either way instead of raising an alarm.

**Scales over chords.** Major chord: major pentatonic. Minor chord: minor pentatonic.
Dominant seventh: major pentatonic, with the blues scale as the gritty option.
Half-diminished: minor pentatonic on the chord's minor third. Sus4: major pentatonic on the
fourth (Csus4: F G A C D); 7sus4: the one a whole step below the root (C7sus4: B♭ C D F G).
Diminished and augmented: the chord's own notes.

**Clashes.** A note of the key's pentatonic clashes with a chord when it sits a half step
above a chord note (G over D major, against its F♯), or when it is the minor third over a
chord with a major third.

**B and H.** H is always B natural. When a sheet writes H anywhere, a plain B on it means B♭,
as on German and Russian sheets.

**The first line of a sheet.** "Artist - Title" (the usual order on chord sites) and
"Title by Artist" are both read.

**Key names.** A key can be typed in English (Bb, F# minor, Gm), German (Es-Dur, fis-moll;
B-Dur is B♭ major) or Russian (ля минор, си-бемоль мажор).

**Names on the page.** Russian names are the default under the staff and in text. Chord
symbols stay in letters with the root's Russian name as a hint; scales read "Major pentatonic
on ре" and keys "ре мажор", as in the screen design.

**The chord chart.** Chords stay over their syllables. When a rewritten chord is longer than
the original (F/A becomes D/F♯), the next chord and the words move right together.

## Phase 1

**Simple screens served by the back end.** Phase 1 needed "a simple screen to use it day to
day" before the real front end exists. The back end serves five plain pages (new import,
batch progress, song page with a Fix panel, library, settings) with a little JavaScript that
calls the same API the front end will. There is no build step, and the pages go away or stay
as a fallback once the front end arrives (`create_app(screens=False)` already turns them off).

**One library folder.** Songs, imports, settings and saved step outputs live in one SQLite
file (WAL mode, one short connection per call, so the web app and worker threads never share
one) next to the inputs as they arrived, stored once each under their SHA-256. Moving to the
home server means copying `~/.soundselect`. The database upgrades itself by numbered
migrations, and refuses to open a library made by a newer version.

**A stored song is the pipeline's result for the instrument it was made for.** Showing it for
another instrument or with other note names is worked out when it is asked for, so changing
your default instrument never rewrites the library. Corrections are saved apart from the
result; a song saved by an older version is made again from its inputs when it is opened,
keeping the corrections.

**Jobs run inside the app.** Huey keeps its queue in a SQLite file in the library folder, and
`soundselect serve` runs two worker threads, so one command starts everything.
`soundselect worker` runs them as a process of their own, which the audio worker will use in
Phase 4; that is also when the Docker Compose setup from the plan arrives, since there will be
two processes to start together. Jobs that were running when the app stopped go back in the
queue when it starts, and a job is only ever taken by one worker.

**Every input gets a job, even before its reader exists.** Photos, audio, video and links are
accepted now and their job fails at once with a message saying which phase reads them. The
front end handles every kind the same way, and nothing in the API changes when the readers
arrive.

**Progress by Server-Sent Events.** The event stream checks the jobs' change counter four times
a second and sends what changed. That needs no message broker, and the browser reconnects by
itself.

**The same sheet twice is the same song.** An import whose contents are already in the library
returns that song instead of a copy, unless the import carries corrections (a key, a title).
Checking for the song and saving a new one happen in one database write transaction, so two
workers given the same sheet at the same moment still make one song.

**Reading PDFs.** pdfplumber gives every letter with its position. In a typewriter font the
letters sit on a grid, so the sheet comes out exactly as typed. In a proportional font (a sheet
typed in Word) each chord is placed over the lyric letter below it by position, which lands
within a letter of where the writer put it. Two columns are found from the empty strip
between them; page numbers, web addresses and dates in the top and bottom margins are dropped.
Margin lines are left out before looking for the strip, so a centred page number doesn't
hide it. Positions and page sizes are those of the visible page (the PDF's CropBox), which is
what gets drawn. A scanned PDF (pages that are pictures) gets a message that scans come with photo reading; a
PDF with some scanned pages is read and says which pages were skipped.

**Source pages are drawn when first asked for** (at 144 dpi with pypdfium2) and kept in the
library folder. Each line of the song records its box on the page, for checking the reading
side by side. PDFium can't draw from two threads at once, so drawing pages takes a lock.

**Verovio is given its music fonts in every thread.** Verovio finds its fonts through a
setting that only the thread that imported it gets, so the first staff drawn inside a web
request came out empty. The drawing engine is now pointed at its font folder when it starts.

**The app answers only this computer.** `serve` listens on 127.0.0.1 and warns when told to
listen on other addresses, since there is no sign-in yet; the sign-in comes with the home
server and Tailscale.

**The app checks the Host and Origin of requests.** With no sign-in, a web page open in the
browser must not be able to use the app. Requests must be addressed to 127.0.0.1, localhost
or ::1 (others can be added with `SOUNDSELECT_ALLOWED_HOSTS`), which stops a site from
pointing its own name at this computer to read the library (DNS rebinding). POST, PUT, PATCH
and DELETE that carry an Origin must come from the app's own pages or an allowed CORS origin,
so another site can't send a form that adds or deletes songs.

**Tests use httpx2.** Starlette's test client now prefers httpx2 and warns about httpx.

**The Phase 1 gate** is ten of your real chord sheets coming out right. The sample sheets and
test PDFs in `backend/tests/data` stand in until those arrive.

## Hooks for the next phases

Photos (Phase 2) and sheet music (Phase 3) are built side by side, so the spots both touch
landed once, before either.

**One OpenCV for everything: `opencv-python-headless` 4.** RapidOCR asks for `opencv-python`
and homr for the headless build; both installed side by side share one `cv2` folder and break
homr. A uv override drops `opencv-python`, and everything uses the headless OpenCV 4, which
needs no screen libraries on the home server.

**onnxruntime below 1.24 on Intel Macs.** onnxruntime 1.24 and later has no Intel Mac wheels,
though homr asks for 1.24.1 or later. Another override keeps Intel Macs on 1.20 to 1.23 and
everything else on 1.24.1 or later. uv never builds these from source.

**Extras for the heavy tools.** The photo reader (RapidOCR, onnxruntime, OpenCV, HEIC
support) is in the main install. Sheet music (`sheetmusic`: homr, music21), links (`links`:
yt-dlp) and audio (`audio`: PyAV, which decodes audio and video files for the song tool) are
extras; `uv sync --all-extras` installs everything, and CI does too. Without an
extra the app still runs: Health says which tools are there, and an item that needs a missing
one fails with a message saying to install it.

**Pipelines register themselves.** Each phase's package registers its pipeline with
`register_pipeline`; its name is its job kind ("sheet_music", "song"). Importing a package stays
cheap: the heavy libraries are imported inside functions. A pipeline can say whether its tools
are installed (`available`), whether it should read an image (`claims`), and how to draw its
source pages (`pages`).

**Routing and grouping.** `route` sends each item to a pipeline: text and PDF to chord
sheets; images to sheet music when it claims them (or `image_mode` says so), else to chord
sheet photos; videos to sheet music; audio to songs; links by `link_mode`. A group is always
one song or piece, from files that go to the same pipeline, which must read several files at
once. Sheet music screenshots in no group make one piece, since a piece's pages are usually
chosen together.

**Page numbers run across a song's files.** Each kind of file with pages registers how to count
and draw them; a song's pages are numbered across its files in order, so a two-page PDF then a
photo gives pages 0, 1 and 2. Drawn pages are kept under the pipeline's name and its inputs.

## Phase 2

**Photos are read on this computer.** RapidOCR (PaddleOCR's models, run by onnxruntime)
reads each picture; nothing is sent anywhere. Its built-in model reads Latin letters, digits
and signs, so every chord, but no Cyrillic. Russian lyrics need PaddleOCR's East Slavic model,
which RapidOCR downloads the first time (about 8 MB) and keeps. Both models read every piece of
text and the surer reading wins. Without the internet on first use the chords still come
through, and the song says some writing couldn't be read. The AI reader the plan keeps as a
fallback (`settings.photo_reader = "ai"`) is not built: the local reader is to be judged on
your real photos first.

**A photo is prepared the same way every time.** The page is cut out of a darker background
and flattened when its edges are clear, the picture is sized to 1400 to 2000 pixels on its long
side, and a tilt of up to 6 degrees is levelled by finding the angle at which the rows of ink
separate most sharply. All of it depends only on the file, so the picture shown beside a song,
drawn again long after reading, is the one the line boxes were measured on. The phone's
orientation tag is followed; a photo with a wrong tag is read sideways. iPhone HEIC photos open
through pillow-heif.

**Words become lines the way the PDF reader does it.** Each word read comes with its box, its
letters share its width evenly, and the PDF reader's layout puts each chord over the letter it
sits above, splits pages printed in two columns and drops page numbers and web addresses in
the margins. In a row that is otherwise chords, two chords read as one word (`Bb/DCm7`) are
split, and `rn` read for `m` is put right. A chord read with little certainty is pointed out.

**Scanned PDFs are photos.** A PDF page with only a picture on it is drawn at twice its shown
size and read by the photo reader, with boxes in the page's shown size, so the source view
works as for any PDF.

**A group is one song from several files,** read in the order given, its pages numbered on
across the files (a two-page PDF then a photo gives pages 0, 1 and 2). Its fingerprint is made
from the files' contents in order, so the same photos under other names are the same song.

**Measured on the test pictures** (made from the sample sheets by
`backend/tests/data/photos/make.py`): a screenshot, a phone-style photo at an angle on a dark
table, the scanned PDF and a song over two pictures all give every chord and the key right,
each chord within a letter of its place. Reading takes about a second a picture on the
cloud test machine.

## Before the real sheets

**B or B♭ on Russian sheets without H.** A sheet with H means B♭ by its plain B; a sheet
without H, with Russian words, no B♭ or A♯ of its own, and chords that fit a key much better
with B♭ (at least half a point of key fit per chord that changes) is read as B♭, with a
notice and a "B on the sheet" choice under Fix to undo it; English sheets keep B natural.

**A stated key keeps all its words.** "Тональность: ре минор" and "Key: D minor" are read
whole, and a line that only starts like a key line ("Key to my heart") stays a lyric.

**Short "Name:" labels.** A line that is just a short name and a colon ("A1:", "B:", "Intro
riff:") is a section label when chords, a tab or ChordPro follow it, and a title set off by a
blank line stays the title even when the lyrics run straight into the chords.

**Lowercase chord lines.** A line such as "am  dm" is read as chords when every word is a chord
once capitalised, and there are two or more of them or Russian lyrics follow.

**Repeat words after chords.** "(2 раза)", "2 times" and "x 2" after chords are read as one
repeat mark, as "x2" already was.

## Phase 4: songs from audio

**Every engine runs on onnxruntime and numpy.** The plan picked Demucs through audio-separator,
Basic Pitch and Beat This. On an Intel Mac none of them installs today: PyTorch stops at 2.2
there (audio-separator needs 2.3 and numpy 2; Beat This needs PyTorch), numba and llvmlite (so
librosa) have no Intel Mac wheels, and the basic-pitch package pulls TensorFlow or coremltools
on macOS. So the song tool uses:

- the voice: the MDX-Net vocal model `UVR-MDX-NET-Voc_FT` from the Ultimate Vocal Remover
  project, run with onnxruntime (`audio/separate.py`, with the model's published spectrogram
  settings). About 0.6 times the song's length on four cloud cores.
- the notes: Basic Pitch's own ONNX model file (v0.4.0), with its note decoding ported to numpy
  (`audio/notes.py`).
- the beat: the classic onset-strength, tempo and dynamic-programming beat tracker (the method
  librosa uses), in numpy (`audio/beats.py`); bars from where the bass and kick hit hardest,
  4/4 unless 3/4 is clearly better.
- opening any recording: PyAV, which carries its own ffmpeg, so nothing else is installed.

Both models download once into `~/.soundselect/models` and are checked against their SHA-256;
`SOUNDSELECT_MODELS` points at a folder of models instead. Demucs and Beat This can join later
as optional engines where PyTorch installs (Linux, Docker, Apple-chip Macs).

**Separated parts are files, the rest is saved by the step runner.** The voice and the band,
mono at 22.05 kHz in half-precision, sit in `~/.soundselect/audio/<recording>/` (about 20 MB a
song); a key or octave correction never separates again, and a missing file is simply made
again. A link's download is kept there too.

**Tuning first.** The recording's distance from A = 440 Hz (from its sharpest spectral peaks)
is measured before notes are found, and the voice is retuned for the note finder, so a record
a quarter tone off doesn't land between keys. More than 15 cents off gets a note to the player.

**Melody.** Overtone ghosts are dropped (an octave, octave and fifth, two octaves, two octaves
and a third above a louder note), the louder and higher note wins where notes overlap, short
neighbour notes (vibrato, scoops) fold into the note they decorate, and notes where the voice
part is nearly silent (what leaks through in an intro) are dropped. With hardly any singing
(an instrumental), the melody comes from the whole mix and the player is told.

**Rhythm.** Times become beats along the beats found, one beat at a time, then snap to
sixteenths; bar 1 starts at the downbeat at or before the first note. Tiny gaps close up.
Notes heard less clearly than 0.4 count as doubtful and are listed in a note to the player;
every song says its melody is a draft.

**Key.** From the melody (how long each pitch class is held) and the band's sound (how strongly
each pitch class rings), half each, against the Krumhansl-Kessler profiles. Chords recognized
from the band will add their evidence in a later phase.

**Octave.** The melody moves by whole octaves to sit in the player's comfortable range, unless
the player set `melody_octave`.

**Links** wait for the shared download module from the sheet music phase; until it lands, a
link job fails with a message that says so.

**Docker Compose** runs the app and one worker on one library volume; songs take minutes, so
they run one at a time in the worker and the app stays quick.
