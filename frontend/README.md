# SoundSelect front end

The screens: import (chord sheets, songs, sheet music), batch progress, the song page, music
stand mode, library and settings. Laptop, iPad and phone, light and dark, installable to the
home screen (PWA).

Plain files with no build step: the back end serves them as they are (`uv run soundselect serve`,
then http://127.0.0.1:8000). Every screen address gets `index.html`; the files are under `/app`;
`/sw.js` (offline copy) and `/music-font.css` (Verovio's Leipzig font) sit at the top. Set
`SOUNDSELECT_FRONTEND=off` to get the old simple screens back, or a folder path to serve another copy.

- `app.js`: the screens and the address router.
- `music.js`: note names (Russian, letters, both, solfège, German), key and chord text, the staff
  for scales and chord notes (drawn here so it reflows and redraws at once when names change),
  and playback at concert pitch.
- `api.js`: calls to `/api/v1` (docs/api.md).
- The melody and sheet music come drawn by the server's Verovio (`score?format=svg`).
