// The pencil drawings: the alto sax, the S monogram and the icons. Each is a small SVG drawn in
// code, gone over twice like a pencil, and roughened by one shared filter. Music itself (staves,
// notes, chords) never goes through the filter: it stays crisp ink.
//   <span data-ic="library" data-s="20"></span>  an icon
//   <span data-art="sax"></span>, <span data-art="mono"></span>  the drawings
// Anything with those attributes is drawn as soon as it lands in the page.

// a fixed seed, so the sax is drawn the same way every time
let seed = 11;
const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
const jit = (a) => (rnd() - 0.5) * 2 * a;
const f1 = (n) => n.toFixed(1);

// a smooth line through the points (Catmull-Rom as cubic Bézier)
function curve(pts) {
  let d = `M${f1(pts[0][0])} ${f1(pts[0][1])}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    d += ` C${f1(p1[0] + (p2[0] - p0[0]) / 6)} ${f1(p1[1] + (p2[1] - p0[1]) / 6)} ${f1(p2[0] - (p3[0] - p1[0]) / 6)} ${f1(p2[1] - (p3[1] - p1[1]) / 6)} ${f1(p2[0])} ${f1(p2[1])}`;
  }
  return d;
}
const shake = (pts, a) => pts.map(([x, y]) => [x + jit(a), y + jit(a)]);

// the alto's centre line, mouthpiece to bell: x, y and the tube's width there
const LINE = [
  [26, 14, 5], [44, 20, 6], [62, 27, 7], [80, 36, 8], [94, 49, 9], [102, 64, 10], [105, 82, 11],
  [104, 120, 13], [102, 160, 15], [99, 200, 17], [96, 240, 19], [94, 276, 21],
  [97, 304, 23], [110, 322, 25], [130, 328, 26], [148, 318, 27], [158, 296, 28],
  [163, 268, 31], [168, 246, 38], [173, 228, 50],
];
function edges() {
  const L = [], R = [];
  LINE.forEach((p, i) => {
    const a = LINE[Math.max(0, i - 1)], b = LINE[Math.min(LINE.length - 1, i + 1)];
    let dx = b[0] - a[0], dy = b[1] - a[1];
    const n = Math.hypot(dx, dy); dx /= n; dy /= n;
    L.push([p[0] - dy * p[2] / 2, p[1] + dx * p[2] / 2]);
    R.push([p[0] + dy * p[2] / 2, p[1] - dx * p[2] / 2]);
  });
  return [L, R];
}
function saxInner({ passes = 2, keys = true, shade = true, w = 1.15 } = {}) {
  seed = 11;
  const [L, R] = edges();
  let g = "";
  for (let k = 0; k < passes; k++) {
    const op = k ? 0.45 : 0.9;
    g += `<path class="p" stroke-width="${w}" opacity="${op}" d="${curve(shake(L, k ? 1.2 : 0.4))}"/>`;
    g += `<path class="p" stroke-width="${w}" opacity="${op}" d="${curve(shake(R, k ? 1.2 : 0.4))}"/>`;
  }
  g += `<ellipse class="p" cx="174" cy="226" rx="27" ry="8.5" transform="rotate(-14 174 226)" stroke-width="${w}"/>`;
  g += `<ellipse class="p" cx="173" cy="227" rx="21" ry="5.5" transform="rotate(-14 173 227)" stroke-width="${w * 0.7}" opacity=".5"/>`;
  g += `<path class="p" stroke-width="${w}" d="M27 11 L10 6 L8 12 L27 18"/><path class="p" stroke-width="${w * 0.8}" d="M34 13 L32 22 M38 14 L36 23"/>`;
  if (keys) {
    // pearl keys down the body, the rod beside them, the octave key on the crook
    for (const [x, y, r] of [[96, 108, 4.5], [95, 128, 4.5], [94, 148, 4.5], [92, 182, 5.5], [90, 204, 5.5], [88, 226, 5.5], [86, 252, 6]]) {
      g += `<circle class="p" cx="${f1(x + jit(0.4))}" cy="${f1(y + jit(0.4))}" r="${r}" stroke-width="${w * 0.9}"/>`;
      g += `<path class="p" stroke-width="${w * 0.6}" opacity=".6" d="M${x + r} ${y} L${x + r + 7} ${y + 1}"/>`;
    }
    g += `<path class="p" stroke-width="${w * 0.7}" opacity=".7" d="${curve([[113, 96], [112, 150], [109, 210], [106, 268]])}"/>`;
    g += `<path class="p" stroke-width="${w * 0.8}" d="M84 40 C 90 34, 98 36, 100 44"/>`;
    g += `<ellipse class="p" cx="126" cy="300" rx="7" ry="4" stroke-width="${w * 0.8}"/><ellipse class="p" cx="143" cy="290" rx="6" ry="3.5" stroke-width="${w * 0.8}"/>`;
    g += `<path class="p" stroke-width="${w * 0.8}" opacity=".7" d="M97 90 L 112 90 M95 268 L 113 270"/>`;
  }
  if (shade) {
    // graphite hatching on the shadow side and inside the bell
    for (let i = 0; i < 26; i++) {
      const t = 7 + i * 0.5, p = LINE[Math.floor(t)], q = LINE[Math.min(LINE.length - 1, Math.floor(t) + 1)], f = t % 1;
      const x = p[0] + (q[0] - p[0]) * f, y = p[1] + (q[1] - p[1]) * f, wd = p[2] / 2;
      g += `<path class="p" stroke-width=".7" opacity=".35" d="M${f1(x + wd * 0.2)} ${f1(y + 3)} L${f1(x + wd * 0.95)} ${f1(y - 3)}"/>`;
    }
    for (let i = 0; i < 9; i++) g += `<path class="p" stroke-width=".7" opacity=".3" d="M${152 + i * 3.5} ${238 - i} L${160 + i * 3.5} ${222 - i}"/>`;
  }
  return g;
}

// the S monogram: the crook and mouthpiece on top, the tail flaring into a bell
const monoInner = (w = 4) => `<path class="p" stroke-width="${w}" d="M64 22 C 40 8, 14 22, 22 44 C 30 64, 70 62, 74 88 C 78 114, 46 124, 30 108"/>`
  + `<path class="p" stroke-width="${w * 0.7}" d="M64 22 L 76 18 L 78 24 L 66 26"/>`
  + `<ellipse class="p" cx="26" cy="104" rx="11" ry="5" transform="rotate(48 26 104)" stroke-width="${w * 0.7}"/>`
  + [[58, 66], [68, 76], [72, 90]].map(([x, y]) => `<circle class="p" cx="${x}" cy="${y}" r="2.6" stroke-width="${w * 0.5}"/>`).join("");

const note = (x, y, s) => `<g transform="translate(${x} ${y}) scale(${s}) rotate(-8)"><ellipse cx="0" cy="18" rx="4.6" ry="3.4" transform="rotate(-20 0 18)" fill="currentColor"/><path class="p" d="M4 17 V-2 C 8 4, 14 5, 12 12" stroke-width="1.2"/></g>`;

const svg = (vb, inner, size) => `<svg viewBox="${vb}" ${size} aria-hidden="true" focusable="false"><g class="pencil">${inner}</g></svg>`;

export const ART = {
  sax: () => svg("0 0 200 340", saxInner({ passes: 2 }), 'width="100%" height="100%"'),
  // the same sax for small places, in a heavier line so it still reads at 40 px
  saxSmall: () => svg("0 0 200 340", saxInner({ passes: 1, shade: false, w: 3.4 }), 'width="100%" height="100%"'),
  // the sax leaning into a page corner, with one note drifting off the bell
  margin: () => svg("0 0 200 340", `<g transform="rotate(18 100 170)">${saxInner({ passes: 2 })}</g>${note(30, 80, 0.8)}`, 'width="100%" height="100%"'),
  mono: () => svg("0 0 96 130", monoInner(4), 'width="100%" height="100%"'),
};

// icons on a 24 px grid
const ICONS = {
  plus: "M12 5v14M5 12h14",
  chords: "M6 3h9l4 4v14H6z M15 3v4h4 M9 10.5h3 M13.5 10.5h2.5 M9 14h7 M9 17.5h5",
  wave: "M6 9.5v5 M9 6v12 M12 9v6 M15 4.5v15 M18 8.5v7 M21 11v2 M3 11v2",
  pages: "M8 3h11v15 M5 6h11v15H5z M7 11h7 M7 13h7 M7 15h7 M7 17h7",
  library: "M4 5h4v14H4z M10 5h4v14h-4z M16 6l4 1-3 13-4-1z",
  batch: "M4 7h16 M4 12h16 M4 17h10",
  note: "M9 18a3 3 0 1 1-.1 0 M12 18V4l7 2.5v3L12 7",
  settings: "M12 9a3 3 0 1 0 .1 0 M12 2.5v3 M12 18.5v3 M2.5 12h3 M18.5 12h3 M5.3 5.3l2.1 2.1 M16.6 16.6l2.1 2.1 M5.3 18.7l2.1-2.1 M16.6 7.4l2.1-2.1",
  stand: "M4.5 4h15v9h-15z M7 7h10 M7 10h10 M12 13v7.5 M8 21.5l4-1.2 4 1.2",
  play: "M8 5l11 7-11 7z",
  camera: "M4 8h3l2-2.5h6L17 8h3v11H4z M12 10a3.5 3.5 0 1 0 .1 0",
  fix: "M15 4l5 5L9 20H4v-5z M13 6l5 5",
};
export function icon(name, size = 20) {
  const d = ICONS[name];
  if (!d) return "";
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><g class="pencil"><path class="p" d="${d}" stroke-width="1.6"/><path class="p" d="${d}" stroke-width=".8" opacity=".45" transform="translate(.35 .3)"/></g></svg>`;
}

// the shared filter: a slight wobble, then graphite that breaks up on the paper
const FILTER = `<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>
  <filter id="pencil" x="-5%" y="-5%" width="110%" height="110%">
    <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="3" result="wob"/>
    <feDisplacementMap in="SourceGraphic" in2="wob" scale="2.2" xChannelSelector="R" yChannelSelector="G" result="shaky"/>
    <feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="1" seed="7" result="grit"/>
    <feColorMatrix in="grit" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -2.2 2.0" result="mask"/>
    <feComposite in="shaky" in2="mask" operator="in"/>
  </filter></defs></svg>`;

const cache = {};
function paint(root) {
  for (const el of root.querySelectorAll("[data-ic]:not([data-done]), [data-art]:not([data-done])")) {
    el.dataset.done = "";
    if (el.dataset.ic) el.innerHTML = icon(el.dataset.ic, Number(el.dataset.s || 20));
    else if (ART[el.dataset.art]) el.innerHTML = cache[el.dataset.art] ??= ART[el.dataset.art]();
  }
}

export function start() {
  document.body.insertAdjacentHTML("afterbegin", FILTER);
  paint(document);
  new MutationObserver(() => paint(document)).observe(document.body, { childList: true, subtree: true });
}
