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
