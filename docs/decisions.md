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

## Phase 3

**One piece from many screenshots.** A sheet music video shows a few lines at a time, and each
new view repeats the last lines of the one before. The views are cut into systems (staves joined
by a line at their left edge stay together, so piano music keeps its pairs), and each new view's
first lines are matched against the previous view's last ones by picture; everything after the
match is new. When a line was cut off by the edge of one view, the uncut copy is kept. All lines
are then laid out on A4 pages at one staff size: the clean copy, ready in about a second.

**Videos are read by OpenCV, not ffmpeg.** OpenCV's wheels can open MP4 and WebM files
themselves, so nothing else needs installing on a Mac without Homebrew packages. Two frames a
second are enough: a stretch of frames that hardly changes is one view, fades and page turns are
skipped, and the pixel median over a view's frames removes a moving playback cursor. Links are
downloaded picture-only (no sound, up to 1080p, one file so no merging) by the shared
`soundselect.links` module, which the song tool reuses for the sound.

**homr reads the notes at our staff positions.** Handing homr the staves the stitching already
found skips its own staff finder, which is slower and misses staves in small video pictures
(82% of notes right at 480p against 94% this way). Its `--read-staff-positions` option crashes in
0.7, so its note reader is called directly. homr is AGPL-3.0, fine for personal use, and
downloads its models (about 300 MB) the first time it reads. It runs on onnxruntime 1.23 on
Intel Macs (the last version with Intel Mac wheels), with the same results on the test pieces.

**Chord names by OCR, placed by barlines.** RapidOCR reads the strip above each system's top
staff, cut to the staff's width (the text finder misses lone letters in a page-wide strip). A
chord's bar is the number of barlines to its left, and its beat the note nearest its place in the
bar. A music-font flat often comes back as "2" or is dropped altogether: "B2" is read as B♭, and
a lone letter whose box is wider than a letter gets the flat or sharp back from the number of
upright strokes after it (one is a flat, two a sharp). Letters much smaller than the chord names
(fingerings, rehearsal letters) are left out, and so is anything over the clef.

**The library keeps the piece in concert pitch.** A page whose part name says it is for alto sax
(or another saxophone) is moved to concert pitch first, so it is not transposed twice;
`Corrections.page_instrument` fixes a wrong guess ("concert" or an instrument). The piece for the
player is made from the concert score with the interval the music core chose for the song's key,
so the notation, the key and the chords always agree. The key comes from the key signature: its
major key or the relative minor, whichever the chords and the last note point to.

**Two PDFs, as the plan says.** The clean copy is the joined screenshots exactly as the video
showed them. The re-engraved piece is drawn by Verovio on A4 pages and printed by WeasyPrint like
every other page, with note names under the notes when asked for (Russian by default).

**What the check screen is for.** homr doesn't read lyrics or 1st and 2nd ending brackets yet, and
on the test page it added two fermatas and an ornament that aren't there, so every sheet music
song carries a note to check it against the original, and the pages call returns the clean copy
with a box for every line.

**The pictures a piece is made from live in the library folder** (`sheetmusic/`, by SHA-256),
so a saved step points at them by name and a correction never reads the pictures again. The
clean copy's page list is kept beside them, so its pages and PDF come back without re-reading.
