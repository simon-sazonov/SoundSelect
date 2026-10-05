// Note names, chord symbols, key names, the staff drawing for scales and chords, and playback.
// Pitches arrive from the API as spelled notes ("F#4", "Bb3"), so C♯ and D♭ stay different.

const LETTERS = "CDEFGAB";
const RUSSIAN = { C: "до", D: "ре", E: "ми", F: "фа", G: "соль", A: "ля", B: "си" };
const SOLFEGE = { C: "do", D: "re", E: "mi", F: "fa", G: "sol", A: "la", B: "si" };
const ACC = { 2: "𝄪", 1: "♯", 0: "", "-1": "♭", "-2": "𝄫" };

export const NAME_SYSTEMS = [
  ["russian", "Русские", "до ре ми фа♯"],
  ["letters", "Letters", "C D E F♯"],
  ["both", "Both", "ре over D"],
  ["solfege", "Solfège", "do re mi fa♯"],
  ["german", "German", "C D E Fis H"],
  ["none", "Off", "Just the staff"],
];
// the four on the song page's quick switch; the rest live in settings
export const QUICK_NAMES = ["russian", "letters", "both", "none"];

/** "F#4" -> {letter: "F", alter: 1, octave: 4}; octave is null for a bare name. */
export function parsePitch(text) {
  const m = /^([A-G])(##|#|bb|b|x)?(-?\d)?$/.exec(String(text).trim());
  if (!m) return null;
  const alter = { "##": 2, x: 2, "#": 1, bb: -2, b: -1 }[m[2]] ?? 0;
  return { letter: m[1], alter, octave: m[3] === undefined ? null : Number(m[3]) };
}

function german(letter, alter) {
  if (letter === "B") return alter === -1 ? "B" : alter === 0 ? "H" : alter > 0 ? "His" : "Heses";
  if (alter === 0) return letter;
  if (alter > 0) return letter + "is".repeat(alter);
  if (letter === "E" || letter === "A") return letter + "s" + "es".repeat(alter * -1 - 1);
  return letter + "es".repeat(-alter);
}

/** One note's name in a system, as [main, second line] ("both" has two). */
export function noteNames(pitch, system) {
  const p = typeof pitch === "string" ? parsePitch(pitch) : pitch;
  if (!p) return [String(pitch), ""];
  const acc = ACC[p.alter] ?? "";
  switch (system) {
    case "letters": return [p.letter + acc, ""];
    case "solfege": return [SOLFEGE[p.letter] + acc, ""];
    case "german": return [german(p.letter, p.alter), ""];
    case "both": return [RUSSIAN[p.letter] + acc, p.letter + acc];
    case "none": return ["", ""];
    default: return [RUSSIAN[p.letter] + acc, ""];
  }
}

/** A note's name for running text: "ре", "D", or "ре (D)" for both. Off reads as Russian. */
export function noteText(pitch, system) {
  const p = typeof pitch === "string" ? parsePitch(pitch) : pitch;
  if (!p) return String(pitch);
  if (system === "both") { const [a, b] = noteNames(p, "both"); return `${a} (${b})`; }
  return noteNames(p, system === "none" ? "russian" : system)[0];
}

/** "Bb major" -> "си♭ мажор" / "B♭ major" / "си♭ мажор (B♭ major)". */
export function keyText(key, system, { short = false } = {}) {
  if (!key) return "";
  const p = parsePitch(key.tonic);
  const acc = ACC[p.alter] ?? "";
  const ru = `${noteNames(p, "russian")[0]} ${key.mode === "minor" ? "минор" : "мажор"}`;
  const en = `${p.letter}${acc} ${key.mode === "minor" ? "minor" : "major"}`;
  const la = `${noteNames(p, "solfege")[0]} ${key.mode === "minor" ? "minor" : "major"}`;
  if (system === "letters" || system === "german") return en;
  if (system === "solfege") return la;
  if (system === "both" && !short) return `${ru} · ${en}`;
  return ru;
}
/** The other naming of a key, shown small under the main one. */
export function keyAside(key, system) {
  return system === "letters" || system === "german" || system === "solfege"
    ? keyText(key, "russian")
    : keyText(key, "letters");
}

/** Chord symbols stay letters, with real sharp and flat signs. */
export function prettyChord(symbol) {
  if (!symbol) return "N.C.";
  return String(symbol)
    .replace(/^([A-G])b/, "$1♭")
    .replace(/\/([A-G])b/, "/$1♭")
    .replace(/#/g, "♯")
    .replace(/([^A-G])b(\d)/g, "$1♭$2");
}
export function chordRoot(symbol) {
  const m = /^([A-G])(#|b)?/.exec(symbol || "");
  return m ? parsePitch(m[1] + (m[2] || "")) : null;
}

const SCALE_NAMES = {
  major_pentatonic: "Major pentatonic",
  minor_pentatonic: "Minor pentatonic",
  blues: "Blues scale",
  major_blues: "Major blues scale",
  arpeggio: "Chord notes",
};
export function scaleLabel(kind, root, system) {
  const name = SCALE_NAMES[kind] ?? kind.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  return root ? `${name} on ${noteText(root, system)}` : name;
}

/** Chord tones (pitch names) stacked upward from a starting octave, for the staff. */
export function stackTones(tones, octave = 4) {
  let prev = -Infinity;
  return tones.map((t) => {
    const p = parsePitch(t);
    let o = octave;
    let v = o * 7 + LETTERS.indexOf(p.letter);
    while (v <= prev) { o += 1; v += 7; }
    prev = v;
    return `${p.letter}${t.slice(1)}${o}`;
  });
}

// ---------- the staff ----------

const GAP = 10; // one staff space
const TOP = 46; // top staff line
const BOT = TOP + 4 * GAP;
const SHARPS = [["F", 8], ["C", 5], ["G", 9], ["D", 6], ["A", 3], ["E", 7], ["B", 4]];
const FLATS = [["B", 4], ["E", 7], ["A", 3], ["D", 6], ["G", 2], ["C", 5], ["F", 1]];
const GLYPH = { clef: "", sharp: "", flat: "", natural: "", dsharp: "", dflat: "", head: "" };
const ACC_GLYPH = { 2: GLYPH.dsharp, 1: GLYPH.sharp, 0: GLYPH.natural, "-1": GLYPH.flat, "-2": GLYPH.dflat };

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/**
 * A short line of notes (a scale or a chord's notes) on a treble staff, as an SVG string.
 * notes: ["D4", "E4", ...] written with octaves; `mark` lists indexes drawn in the accent.
 * fifths: the key signature. names: the name system for the hints under the notes.
 * The drawing reflows: it fills its box and keeps its proportions.
 */
export function staffSvg(notes, { fifths = 0, names = "russian", mark = [], label = "", chord = false } = {}) {
  const step = (p) => p.octave * 7 + LETTERS.indexOf(p.letter) - 30; // 0 = bottom line E4
  const y = (s) => BOT - (s * GAP) / 2;
  const keyAlter = {};
  const parts = [];
  const n = Math.max(-7, Math.min(7, fifths | 0));
  const sig = n > 0 ? SHARPS : FLATS;
  for (let i = 0; i < Math.abs(n); i++) {
    const [letter, s] = sig[i];
    keyAlter[letter] = n > 0 ? 1 : -1;
    parts.push(`<text class="g" x="${46 + i * 12}" y="${y(s)}">${n > 0 ? GLYPH.sharp : GLYPH.flat}</text>`);
  }
  const ps = notes.map(parsePitch).filter(Boolean);
  const both = names === "both";
  const x0 = 50 + Math.abs(n) * 12 + 14;
  const slot = chord ? 0 : 46;
  const width = Math.max(chord ? 150 : 200, x0 + slot * ps.length + 26 + (chord ? 40 : 0));
  const state = {};
  const heads = [];
  ps.forEach((p, i) => {
    const s = step(p);
    const cur = state[p.letter + p.octave] ?? keyAlter[p.letter] ?? 0;
    const acc = cur !== p.alter ? ACC_GLYPH[p.alter] : "";
    state[p.letter + p.octave] = p.alter;
    const cx = chord ? x0 + 20 : x0 + 14 + i * slot;
    heads.push({ p, s, cx, cy: y(s), acc, marked: mark.includes(i) });
  });
  // a chord's seconds sit side by side
  if (chord) heads.forEach((h, i) => { if (i && h.s - heads[i - 1].s === 1 && !heads[i - 1].shift) h.shift = 12; });
  for (const h of heads) {
    const cls = h.marked ? "m" : "";
    const hx = h.cx + (h.shift || 0);
    for (let s = -2; s >= h.s; s -= 2) parts.push(`<line class="l" x1="${hx - 5}" x2="${hx + 17}" y1="${y(s)}" y2="${y(s)}"/>`);
    for (let s = 10; s <= h.s; s += 2) parts.push(`<line class="l" x1="${hx - 5}" x2="${hx + 17}" y1="${y(s)}" y2="${y(s)}"/>`);
    if (h.acc) parts.push(`<text class="g ${cls}" x="${h.cx - 14 - (chord ? heads.indexOf(h) % 2 * 10 : 0)}" y="${h.cy}">${h.acc}</text>`);
    parts.push(`<text class="g ${cls}" x="${hx}" y="${h.cy}">${GLYPH.head}</text>`);
    if (!chord) {
      const up = h.s < 4;
      const sx = up ? hx + 11.6 : hx + 0.7;
      parts.push(`<line class="st ${cls}" x1="${sx}" x2="${sx}" y1="${h.cy + (up ? -2 : 2)}" y2="${h.cy + (up ? -34 : 34)}"/>`);
    }
  }
  if (chord) {
    const lo = heads.reduce((a, h) => (h.s < a.s ? h : a), heads[0]);
    const hi = heads.reduce((a, h) => (h.s > a.s ? h : a), heads[0]);
    if (lo) {
      const up = (lo.s + hi.s) / 2 < 4;
      const sx = up ? lo.cx + 11.6 : lo.cx + 0.7;
      parts.push(`<line class="st" x1="${sx}" x2="${sx}" y1="${up ? lo.cy - 2 : hi.cy + 2}" y2="${up ? hi.cy - 34 : lo.cy + 34}"/>`);
    }
  }
  // names under the notes
  const ny = Math.max(BOT + 30, ...heads.map((h) => h.cy + (h.s < 4 ? 26 : 44)));
  if (names !== "none") {
    if (chord) {
      const line = heads.map((h) => noteNames(h.p, names)[0]).join(" ");
      parts.push(`<text class="nm" x="${x0 + 26}" y="${ny}" text-anchor="middle">${esc(line)}</text>`);
      if (both) parts.push(`<text class="nm2" x="${x0 + 26}" y="${ny + 17}" text-anchor="middle">${esc(heads.map((h) => noteNames(h.p, "letters")[0]).join(" "))}</text>`);
    } else {
      for (const h of heads) {
        const [a, b] = noteNames(h.p, names);
        parts.push(`<text class="nm ${h.marked ? "m" : ""}" x="${h.cx + 6}" y="${ny}" text-anchor="middle">${esc(a)}</text>`);
        if (b) parts.push(`<text class="nm2" x="${h.cx + 6}" y="${ny + 17}" text-anchor="middle">${esc(b)}</text>`);
      }
    }
  }
  const height = names === "none" ? Math.max(BOT + 24, ...heads.map((h) => h.cy + 40)) : ny + (both ? 24 : 10);
  const top = Math.min(0, ...heads.map((h) => h.cy - 44));
  const lines = [0, 1, 2, 3, 4].map((i) => `<line class="sl" x1="4" x2="${width - 4}" y1="${TOP + i * GAP}" y2="${TOP + i * GAP}"/>`).join("");
  const end = `<line class="sl" x1="${width - 4}" x2="${width - 4}" y1="${TOP}" y2="${BOT}"/>`;
  return `<svg class="ss-staff" viewBox="0 ${top} ${width} ${height - top}" style="max-width:${Math.round(width * 1.3)}px" role="img" aria-label="${esc(label || notes.join(" "))}">${lines}${end}<text class="g" x="8" y="${y(2)}">${GLYPH.clef}</text>${parts.join("")}</svg>`;
}

// ---------- playback (concert pitch, so it matches the record) ----------

let audio = null;
const SEMI = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
export function midi(pitch) {
  const p = typeof pitch === "string" ? parsePitch(pitch) : pitch;
  return p && p.octave !== null ? 12 * (p.octave + 1) + SEMI[p.letter] + p.alter : null;
}
let stopAt = 0;
/** Play [{pitch, start, length}] (beats) at a tempo; returns the seconds it takes. */
export function play(events, tempo = 100) {
  audio = audio || new (window.AudioContext || window.webkitAudioContext)();
  if (audio.state === "suspended") audio.resume();
  const beat = 60 / tempo;
  const t0 = Math.max(audio.currentTime + 0.05, stopAt);
  const master = audio.createGain();
  master.gain.value = 0.22;
  master.connect(audio.destination);
  let end = t0;
  for (const e of events) {
    const m = midi(e.pitch);
    if (m === null) continue;
    const start = t0 + e.start * beat;
    const dur = Math.max(0.08, e.length * beat * 0.92);
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = "triangle";
    osc.frequency.value = 440 * 2 ** ((m - 69) / 12);
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(1, start + 0.02);
    gain.gain.setTargetAtTime(0.55, start + 0.05, 0.12);
    gain.gain.setTargetAtTime(0, start + dur, 0.05);
    osc.connect(gain).connect(master);
    osc.start(start);
    osc.stop(start + dur + 0.4);
    end = Math.max(end, start + dur);
  }
  stopAt = end;
  return end - audio.currentTime;
}
/** A scale up and back down, one note per beat. */
export function playScale(staff, tempo = 132) {
  const up = staff.map((pitch, i) => ({ pitch, start: i, length: 1 }));
  const down = staff.slice(0, -1).reverse().map((pitch, i) => ({ pitch, start: staff.length + i, length: i === staff.length - 2 ? 2 : 1 }));
  return play([...up, ...down], tempo);
}
export function playChord(staff) {
  return play([...staff.map((pitch, i) => ({ pitch, start: i * 0.5, length: 1 })), ...staff.map((pitch) => ({ pitch, start: staff.length * 0.5, length: 3 }))], 100);
}
