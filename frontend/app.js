// SoundSelect's screens: import, batch progress, the song page, music stand, library, settings.
// Plain modules, no build step: the app serves these files as they are.

import * as api from "./api.js";
import * as M from "./music.js";
import { start as startArt } from "./art.js";

const main = document.getElementById("main");
const standRoot = document.getElementById("stand-root");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const store = {
  get(k, d = null) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

// ---------- routing ----------

let leave = null; // the current screen's clean-up
const ROUTES = [
  [/^\/(import)?$/, importView, "import"],
  [/^\/library$/, libraryView, "library"],
  [/^\/settings$/, settingsView, "settings"],
  [/^\/batches\/([\w-]+)$/, batchView, "batch"],
  [/^\/songs\/([\w-]+)\/stand$/, standView, "song"],
  [/^\/songs\/([\w-]+)$/, songView, "song"],
];

export function go(path, { replace = false } = {}) {
  if (replace) history.replaceState(null, "", path);
  else history.pushState(null, "", path);
  route();
}

async function route() {
  if (leave) { try { leave(); } catch { /* ignore */ } leave = null; }
  standRoot.innerHTML = "";
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const found = ROUTES.find(([re]) => re.test(path));
  const [re, view, nav] = found ?? [null, notFound, ""];
  for (const a of document.querySelectorAll("[data-nav]")) a.classList.toggle("on", a.dataset.nav === nav);
  main.innerHTML = `<div class="loading">Loading…</div>`;
  try {
    await view(...(re ? path.match(re).slice(1) : []));
  } catch (e) {
    main.innerHTML = `<div class="page narrow"><div class="card"><h1 style="font-size:26px">Something went wrong</h1><p class="err">${esc(e.message)}</p><p><a class="btn" href="/">Back to import</a></p></div></div>`;
  }
  if (!history.state?.keepScroll) window.scrollTo(0, 0);
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href]");
  if (!a || a.target || a.hasAttribute("download") || e.defaultPrevented) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
  const u = new URL(a.href, location.href);
  if (u.origin !== location.origin || u.pathname.startsWith("/api/") || u.pathname.startsWith("/app/")) return;
  e.preventDefault();
  go(u.pathname + u.search);
});
window.addEventListener("popstate", route);

function notFound() {
  main.innerHTML = `<div class="page narrow"><div class="card"><h1>Nothing here</h1><p><a href="/">Start an import</a> or open the <a href="/library">library</a>.</p></div></div>`;
}

function remember(kind, href, label) {
  for (const a of document.querySelectorAll(`.nav [data-nav="${kind}"]`)) {
    a.hidden = false;
    a.href = href;
    a.querySelector("span").textContent = label;
  }
}

// ---------- import ----------

const TOOL_ICON = { sheet: "chords", song: "wave", music: "pages" };
const TOOLS = [
  ["sheet", "Chord sheets", "Text, PDF or photos. Get the key, the chords for your instrument and the scales to play."],
  ["song", "Song", "A YouTube link or an audio file. Get the melody on the staff, written for you."],
  ["music", "Sheet music", "Screenshots or a video link. Get full pages, drawn fresh, in concert pitch and for you."],
];

async function importView() {
  const [health, settings, instruments, recent] = await Promise.all([
    api.health().catch(() => null), api.settings(), api.instruments(), api.call("/songs?limit=6").catch(() => ({ songs: [] })),
  ]);
  const tools = health?.tools ?? {};
  const st = { tool: store.get("ss-tool", "sheet"), files: [], oneSong: false, busy: false, error: "" };
  const inst = instruments.find((i) => i.id === settings.instrument);

  const missing = {
    sheet: !tools.photo_reading ? "Photos can't be read on this computer yet. Text and PDF work." : "",
    song: !tools.audio ? "Songs from recordings aren't installed on this computer yet (run uv sync --all-extras)." : !tools.links ? "YouTube links aren't installed yet; audio files work." : "",
    music: !tools.sheet_music ? "Sheet music reading isn't installed on this computer yet (run uv sync --all-extras)." : !tools.links ? "Video links aren't installed yet; screenshots and video files work." : "",
  };
  const accept = { sheet: ".txt,.cho,.crd,.chopro,.pro,.pdf,image/*", song: "audio/*,.mp3,.m4a,.wav,.flac,.ogg,.aac", music: "image/*,video/*,.mp4,.mov,.webm,.mkv" };

  function render() {
    const t = st.tool;
    main.innerHTML = `<div class="page" style="max-width:1040px;position:relative">
      <div class="margin-sax" data-art="margin"></div>
      <div class="lead"><h1 style="font-size:38px;letter-spacing:-0.02em">What are we reading today?</h1>
      <p class="muted" style="margin:6px 0 0">Everything comes back written for ${esc(inst?.name ?? "your instrument")}, with the key's pentatonic first.</p></div>
      <div class="tools" role="radiogroup" aria-label="Tool">${TOOLS.map(([id, name, d]) => `
        <button type="button" role="radio" class="tool ${id === t ? "on" : ""}" aria-checked="${id === t}" data-tool="${id}">
          <span data-ic="${TOOL_ICON[id]}" data-s="34"></span><span class="t">${name}</span><span class="d">${d}</span></button>`).join("")}</div>
      <form class="card" id="imp" style="display:flex;flex-direction:column;gap:18px">
        ${missing[t] ? `<div class="notice warn">${esc(missing[t])}</div>` : ""}
        ${t === "song" ? `<div><label class="lbl" for="links">YouTube or YouTube Music link</label>
            <textarea class="field" id="links" rows="2" style="min-height:56px;font:inherit;font-size:17px" placeholder="https://music.youtube.com/watch?v=… (one per line)"></textarea></div>` : ""}
        ${t === "music" ? `<div><label class="lbl" for="links">Video link: the app takes the screenshots</label>
            <input class="field" id="links" type="url" inputmode="url" placeholder="https://youtube.com/watch?v=…" style="min-height:56px;font-size:17px"></div>` : ""}
        <div class="row" style="align-items:stretch;gap:18px">
          <div class="drop" id="drop" style="flex:1 1 320px">
            <span data-ic="${t === "song" ? "wave" : "camera"}" data-s="40"></span>
            <b style="font-size:18px">${t === "sheet" ? "Drop photos, PDFs or text files" : t === "song" ? "Or drop an audio file" : "Or drop screenshots or a video"}</b>
            <span class="muted">${t === "sheet" ? "Seven photos of seven songs is fine: each comes back as its own song." : t === "song" ? "MP3, M4A, WAV and the like." : "In any order. Overlapping views are matched and joined into full pages."}</span>
            <label class="btn" style="cursor:pointer">Choose files<input type="file" id="pick" multiple accept="${accept[t]}" class="sr"></label>
            ${t === "sheet" ? `<label class="btn" style="cursor:pointer">Take a photo<input type="file" id="cam" accept="image/*" capture="environment" class="sr"></label>` : ""}
            ${st.files.length ? `<div class="files">${st.files.map((f, i) => `<div class="file"><span>${esc(f.name)}</span><button type="button" class="btn small" data-rm="${i}" aria-label="Remove ${esc(f.name)}">Remove</button></div>`).join("")}</div>` : ""}
          </div>
          ${t === "sheet" ? `<div style="flex:1 1 320px;display:flex;flex-direction:column">
            <label class="lbl" for="paste">Or paste a chord sheet</label>
            <textarea class="field" id="paste" placeholder="[Verse 1]&#10;Am        F&#10;Words of the song…" style="flex:1"></textarea></div>` : ""}
        </div>
        <div class="row" style="gap:18px">
          ${t === "sheet" && st.files.length > 1 ? `<button type="button" class="pill ${st.oneSong ? "on" : ""}" id="one" aria-pressed="${st.oneSong}">${st.oneSong ? "All these files are one song" : "One song per file"}</button>` : ""}
          <div class="row" style="gap:8px"><label class="lbl" for="inst" style="margin:0">Write it for</label>
            <select class="field" id="inst" style="width:auto;min-height:40px">${instruments.map((i) => `<option value="${i.id}" ${i.id === settings.instrument ? "selected" : ""}>${esc(i.name)}</option>`).join("")}</select></div>
        </div>
        ${st.error ? `<div class="err" role="alert">${esc(st.error)}</div>` : ""}
        <div class="row" style="justify-content:flex-end"><button class="btn primary" type="submit" ${st.busy ? "disabled" : ""} style="min-height:50px;padding:0 22px">${st.busy ? "Sending…" : t === "sheet" ? "Read it" : t === "song" ? "Get the melody" : "Build the pages"}</button></div>
      </form>
      ${recent.songs.length ? `<section style="display:flex;flex-direction:column;gap:10px"><div class="row spread"><h2 style="font-size:20px">Recent songs</h2><a href="/library">All songs</a></div>
        <div class="tiles">${recent.songs.map((s) => tile(s, settings.names)).join("")}</div></section>` : ""}
    </div>`;
    wire();
  }

  function addFiles(list) { st.files.push(...list); st.error = ""; keepText(); render(); }
  let kept = { paste: "", links: "" };
  function keepText() {
    kept = { paste: main.querySelector("#paste")?.value ?? kept.paste, links: main.querySelector("#links")?.value ?? kept.links };
  }
  function wire() {
    if (main.querySelector("#paste")) main.querySelector("#paste").value = kept.paste;
    if (main.querySelector("#links")) main.querySelector("#links").value = kept.links;
    main.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("click", () => {
      keepText(); st.tool = b.dataset.tool; st.files = []; st.error = ""; store.set("ss-tool", st.tool); render();
    }));
    for (const id of ["pick", "cam"]) main.querySelector(`#${id}`)?.addEventListener("change", (e) => addFiles([...e.target.files]));
    main.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => { keepText(); st.files.splice(Number(b.dataset.rm), 1); render(); }));
    main.querySelector("#one")?.addEventListener("click", () => { keepText(); st.oneSong = !st.oneSong; render(); });
    const drop = main.querySelector("#drop");
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); addFiles([...e.dataTransfer.files]); });
    main.querySelector("#imp").addEventListener("submit", submit);
  }
  async function submit(e) {
    e.preventDefault();
    keepText();
    const form = new FormData();
    const t = st.tool;
    if (t === "sheet" && kept.paste.trim()) form.append("text", kept.paste);
    for (const f of st.files) form.append("files", f, f.name);
    const links = kept.links.split(/\s+/).map((s) => s.trim()).filter(Boolean);
    for (const l of links) form.append("link", l);
    if (!form.has("text") && !form.has("files") && !form.has("link")) {
      st.error = t === "sheet" ? "Paste a chord sheet or add a file first." : t === "song" ? "Paste a link or add an audio file first." : "Paste a link or add screenshots first.";
      return render();
    }
    form.append("instrument", main.querySelector("#inst").value);
    if (t === "sheet") form.append("image_mode", "chord_sheet");
    if (t === "music") { form.append("image_mode", "sheet_music"); form.append("link_mode", "sheet_music"); }
    if (t === "song") form.append("link_mode", "sound");
    if (t === "sheet" && st.oneSong && st.files.length > 1) form.append("groups", JSON.stringify([st.files.map((_, i) => i)]));
    st.busy = true; render();
    try {
      const batch = await api.call("/imports", { method: "POST", form });
      store.set("ss-open-single", batch.jobs.length === 1 ? batch.id : "");
      go(`/batches/${batch.id}`);
    } catch (err) {
      st.busy = false; st.error = err.message; render();
    }
  }
  render();
}

function sourceKind(source) {
  return { text: "Chord sheet", pdf: "Chord sheet · PDF", photo: "Chord sheet · photo", audio: "Song · audio", link: "Link", screenshots: "Sheet music", video: "Sheet music · video" }[source] ?? source;
}
function tile(s, names) {
  const key = s.written_key ?? s.key;
  return `<a class="tile" href="/songs/${s.id}"><span class="src">${esc(sourceKind(s.source))}</span>
    <span><b style="font-size:18px;display:block">${esc(s.title || "Untitled song")}</b><span class="muted" style="font-size:14px">${esc(s.artist || s.source_name || "")}</span></span>
    <span class="k">${key ? `<span class="kick brass" style="display:block">${esc(M.keyText(key, names, { short: true }))}</span>` : ""}
    <span style="font-weight:600">${esc(s.pentatonic.map((p) => M.noteText(p, names === "none" ? "russian" : names === "both" ? "russian" : names)).join(" "))}</span>
    ${s.warnings ? `<span class="muted" style="display:block;font-size:13px">${s.warnings} thing${s.warnings > 1 ? "s" : ""} to check</span>` : ""}</span></a>`;
}

// ---------- batch progress ----------

async function batchView(id) {
  let batch = await api.call(`/batches/${id}`);
  const settings = await api.settings();
  const health = await api.health().catch(() => null);
  const songs = {};
  let loading = false;
  const autoOpen = store.get("ss-open-single") === id;

  async function loadSongs() {
    if (loading) return;
    loading = true;
    try {
      const list = await api.call("/songs?limit=500");
      for (const s of list.songs) songs[s.id] = s;
    } catch { /* keys can wait */ }
    loading = false;
    render();
  }
  function row(j) {
    const s = j.song_id ? songs[j.song_id] : null;
    const key = s ? s.written_key ?? s.key : null;
    const status = j.status === "done" ? (j.reused ? "Already in library" : "Ready") : j.status === "failed" ? "Couldn't read it" : j.status === "running" ? "Reading" : "Waiting";
    const sub = j.status === "running" ? `${esc(j.step_label || "Working")}${j.step_count ? ` · step ${j.step_number} of ${j.step_count}` : ""}`
      : j.status === "failed" ? esc(j.error || "") : s ? esc([s.artist, s.warnings ? `${s.warnings} thing${s.warnings > 1 ? "s" : ""} to check` : ""].filter(Boolean).join(" · ")) : esc(j.name);
    const inner = `<div class="nm"><b>${esc(s?.title || j.name)}</b><span class="muted" style="font-size:14px">${sub}</span>
        ${j.status === "running" ? `<div class="bar" style="margin-top:6px"><i style="width:${Math.round((j.progress || 0) * 100)}%"></i></div>` : ""}</div>
      <div class="ky">${key ? `<span class="kick brass">${esc(M.keyText(key, settings.names, { short: true }))}</span><b>${esc(s.pentatonic.map((p) => M.noteText(p, settings.names)).join(" "))}</b>` : ""}</div>
      <span class="status ${j.status}">${status}</span>`;
    return j.song_id ? `<a class="job" href="/songs/${j.song_id}">${inner}</a>` : `<div class="job">${inner}</div>`;
  }
  function render() {
    const working = batch.total - batch.done - batch.failed;
    const ready = batch.jobs.filter((j) => j.status === "done").length;
    main.innerHTML = `<div class="page" style="max-width:1040px">
      <header class="head"><div><h1 class="title" style="font-size:34px">${batch.total === 1 ? esc(batch.jobs[0]?.name ?? "Your import") : `${batch.total} songs`}</h1>
        <p class="muted" style="margin:6px 0 0">${[ready && `${ready} ready`, batch.failed && `${batch.failed} couldn't be read`, working && `${working} still reading`].filter(Boolean).join(" · ")}${working ? ". Songs open as soon as they're ready; you can leave this page." : "."}</p></div>
        ${ready > 1 && health?.tools?.pdf_output !== false ? `<a class="btn primary" href="${api.url(`/batches/${id}/songbook`, { format: "pdf", names: settings.names })}">Songbook PDF${working ? ` (${ready} of ${batch.total} so far)` : ""}</a>` : ""}
      </header>
      <div class="bar" role="progressbar" aria-label="Import progress" aria-valuemin="0" aria-valuemax="${batch.total}" aria-valuenow="${batch.done + batch.failed}"><i style="width:${Math.round(((batch.done + batch.failed) / Math.max(1, batch.total)) * 100)}%"></i></div>
      <div class="jobs">${batch.jobs.map(row).join("")}</div>
      <div><a class="btn" href="/">Import more</a></div></div>`;
  }
  remember("batch", `/batches/${id}`, batch.total === 1 ? "Last import" : `Import · ${batch.total} songs`);
  render();
  loadSongs();

  let es = null;
  let timer = null;
  const finish = () => {
    if (autoOpen && batch.jobs.length === 1 && batch.jobs[0].song_id && batch.jobs[0].status === "done") {
      store.set("ss-open-single", "");
      go(`/songs/${batch.jobs[0].song_id}`, { replace: true });
    }
  };
  if (batch.status !== "done" && "EventSource" in window) {
    es = new EventSource(api.url(`/batches/${id}/events`));
    es.addEventListener("job", (e) => {
      const j = JSON.parse(e.data);
      const i = batch.jobs.findIndex((x) => x.id === j.id);
      const wasDone = i >= 0 && batch.jobs[i].status === "done";
      if (i >= 0) batch.jobs[i] = j;
      if (j.status === "done" && !wasDone) loadSongs(); else render();
    });
    es.addEventListener("batch", (e) => { const b = JSON.parse(e.data); batch = { ...batch, ...b, jobs: b.jobs?.length ? b.jobs : batch.jobs }; render(); });
    es.addEventListener("end", async () => { es.close(); batch = await api.call(`/batches/${id}`); await loadSongs(); finish(); });
    es.onerror = () => { es.close(); es = null; poll(); };
  } else if (batch.status !== "done") poll();
  else finish();
  function poll() {
    timer = setInterval(async () => {
      try { batch = await api.call(`/batches/${id}`); await loadSongs(); if (batch.status === "done") { clearInterval(timer); finish(); } } catch { /* try again */ }
    }, 1500);
  }
  leave = () => { es?.close(); clearInterval(timer); };
}

// ---------- the song page ----------

const drawnCache = new Map();
async function drawn(id, params) {
  const key = id + JSON.stringify(params);
  if (!drawnCache.has(key)) drawnCache.set(key, api.text(`/songs/${id}/score?` + new URLSearchParams({ ...params, format: "svg" })).catch((e) => { drawnCache.delete(key); throw e; }));
  return drawnCache.get(key);
}

function songModel(song, view) {
  const written = view !== "concert";
  const side = written ? "written" : "concert";
  const key = written ? song.view.written_key ?? song.key.concert : song.key.concert;
  const headline = song.scales.find((s) => s.role === "headline") ?? song.scales[0];
  const instName = (song.view?.name ?? "Instrument").split(" in ")[0];
  return { written, side, key, fifths: key?.fifths ?? 0, headline, others: song.scales.filter((s) => s !== headline), instName };
}

async function songView(id) {
  const [song0, settings, health] = await Promise.all([api.call(`/songs/${id}`), api.settings(), api.health().catch(() => null)]);
  const st = { song: song0, names: settings.names, view: sessionStorage.getItem("ss-view") || "written", sel: null, compare: false, pages: null, line: null };
  remember("song", `/songs/${id}`, song0.identity.title || "Song");
  const tools = health?.tools ?? {};

  function pickDefault() {
    const ch = st.song.chords;
    if (!ch.length) return null;
    const m = songModel(st.song, st.view);
    return (ch.find((c) => c.clashes?.[m.side]?.length) ?? [...ch].sort((a, b) => b.count - a.count)[0]).symbol;
  }
  st.sel = pickDefault();

  function render() {
    const { song, names } = st;
    const m = songModel(song, st.view);
    const title = song.identity.title || "Untitled song";
    const warn = song.notes.filter((n) => n.level === "warning");
    const info = song.notes.filter((n) => n.level !== "warning");
    const quick = M.QUICK_NAMES.includes(names) ? M.QUICK_NAMES : [...M.QUICK_NAMES, names];
    const label = Object.fromEntries(M.NAME_SYSTEMS.map(([k, l]) => [k, l]));
    const exportParams = { names, view: m.side === "written" ? "written" : "concert" };
    const hasPages = song.source_pages?.length > 0;
    const sheet = song.sheet_music;

    main.innerHTML = `<div class="page">
      <header class="head">
        <div style="display:flex;flex-direction:column;gap:6px;min-width:0">
          <div class="muted" style="font-size:14px"><a href="/library">Library</a> / ${esc(sourceKind(song.identity.source))}</div>
          <h1 class="title">${esc(title)}</h1>
          <div class="muted">${esc([song.identity.artist, song.identity.source_name, song.timing?.time_signature].filter(Boolean).join(" · "))}</div>
        </div>
        <div class="row" style="gap:8px">
          <a class="btn" href="/songs/${song.id}/stand"><span data-ic="stand" data-s="18"></span>Music stand</a>
          ${hasPages ? `<button class="btn" type="button" data-act="compare" aria-pressed="${st.compare}">${st.compare ? "Hide the original" : "Compare with the original"}</button>` : ""}
          <button class="btn" type="button" data-act="fix">Fix</button>
          ${sheet ? `<a class="btn" href="${api.url(`/songs/${song.id}/export`, { format: "clean" })}" download>Clean copy</a>` : ""}
          <a class="btn" href="${api.url(`/songs/${song.id}/export`, { ...exportParams, format: "musicxml" })}" download>MusicXML</a>
          ${tools.pdf_output === false ? "" : `<a class="btn primary" href="${api.url(`/songs/${song.id}/export`, { ...exportParams, format: "pdf" })}" download>PDF</a>`}
        </div>
      </header>

      <div class="card toolbar">
        <div class="row"><span class="lbl" style="margin:0">Note names</span>
          <div class="seg" role="group" aria-label="Note names">${quick.map((n) => `<button type="button" class="${n === names ? "on" : ""}" aria-pressed="${n === names}" data-names="${n}">${esc(label[n])}</button>`).join("")}</div></div>
        <div class="row"><span class="lbl" style="margin:0">Written for</span>
          <div class="seg" role="group" aria-label="Pitch">
            <button type="button" class="${m.written ? "on" : ""}" aria-pressed="${m.written}" data-view="written">${esc(song.view?.name ?? "Instrument")}</button>
            <button type="button" class="${!m.written ? "on" : ""}" aria-pressed="${!m.written}" data-view="concert">Concert (piano)</button></div></div>
      </div>

      ${warn.map((n) => `<div class="notice warn" role="status">${esc(n.message)}${n.code === "b_flat_guess" ? ` <button class="btn small" type="button" data-act="fix" style="margin-left:6px">Check it</button>` : ""}</div>`).join("")}

      ${hero(song, m, names)}

      ${song.melody?.notes?.length && !sheet ? `<section class="card" aria-labelledby="mel-h" style="display:flex;flex-direction:column;gap:10px">
        <div class="row spread"><div class="row" style="gap:12px"><h2 id="mel-h" style="font-size:22px">Melody</h2>
          ${song.melody.source === "audio" ? `<span class="kick brass">Draft · red notes are doubtful</span>` : ""}</div>
          <div class="row" style="gap:8px"><button class="btn small" type="button" data-play="melody">Play</button><button class="btn small" type="button" data-play="melody-slow">Slower</button></div></div>
        <div class="drawn" data-drawn="melody"><div class="loading" style="padding:30px">Drawing the melody…</div></div>
        ${song.melody.octave_shift ? `<div class="muted" style="font-size:14px">Moved ${Math.abs(song.melody.octave_shift)} octave${Math.abs(song.melody.octave_shift) > 1 ? "s" : ""} ${song.melody.octave_shift > 0 ? "up" : "down"} to sit in your range. Change it under Fix.</div>` : ""}
      </section>` : ""}

      ${sheet ? sheetSection(song, m) : ""}

      ${st.compare ? `<section class="card" aria-label="The original" style="display:flex;flex-direction:column;gap:12px">
        <div class="row spread"><h2 style="font-size:20px">The original</h2><span class="muted" style="font-size:14px">${song.form.length ? "Tap a line of the chart to find it here." : ""}</span></div>
        <div class="grid2" data-pages>${st.pages ? pagesHtml(st.pages, st.line) : `<div class="loading">Loading the pages…</div>`}</div></section>` : ""}

      ${m.others.length ? `<section style="display:flex;flex-direction:column;gap:12px"><h2 style="font-size:22px">More scales for the whole song</h2>
        <div class="grid2">${m.others.map((s, i) => `<div class="card" style="display:flex;flex-direction:column;gap:6px">
          <div class="row spread"><b style="font-size:18px">${esc(M.scaleLabel(s.kind, s[m.side].root, names))}</b><button class="btn small" type="button" data-play="scale:${i}">Play</button></div>
          <div class="muted" style="font-size:14px">${esc(scaleWhy(s))}</div>
          ${M.staffSvg(s[m.side].staff, { fifths: m.fifths, names, mark: blueNotes(s, m.side) })}</div>`).join("")}</div></section>` : ""}

      ${song.form.length || song.chords.length ? chartSection(song, m, names, st) : ""}

      ${info.length || song.identity.source_name ? `<section style="display:flex;flex-direction:column;gap:6px"><h2 style="font-size:16px">Notes to you</h2>
        ${info.map((n) => `<div style="color:var(--ink2)">${esc(n.message)}</div>`).join("")}
        <div class="muted" style="font-size:14px">${song.key.basis === "stated" ? "The key is the one stated on the sheet." : `Key found with ${Math.round(song.key.confidence * 100)}% confidence.`}</div></section>` : ""}
    </div>`;
    wire();
    fillDrawn();
  }

  function fillDrawn() {
    const { song, names } = st;
    const view = st.view === "concert" ? "concert" : "written";
    for (const el of main.querySelectorAll("[data-drawn]")) {
      const part = el.dataset.drawn;
      drawn(song.id, { part, names, view }).then((svg) => { if (el.isConnected) el.innerHTML = svg; })
        .catch((e) => { if (el.isConnected) el.innerHTML = `<div class="err">${esc(e.message)}</div>`; });
    }
    if (st.compare && !st.pages) {
      api.call(`/songs/${song.id}/pages`).then((p) => { st.pages = p; const el = main.querySelector("[data-pages]"); if (el) el.innerHTML = pagesHtml(p, st.line); });
    }
  }

  function wire() {
    main.querySelectorAll("[data-names]").forEach((b) => b.addEventListener("click", async () => {
      st.names = b.dataset.names;
      render();
      try { await api.saveSettings({ names: st.names }); } catch { /* the view still changed */ }
    }));
    main.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
      st.view = b.dataset.view; sessionStorage.setItem("ss-view", st.view); render();
    }));
    main.querySelectorAll("[data-chord]").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      st.sel = b.dataset.chord;
      if (b.dataset.line) st.line = Number(b.dataset.line);
      render();
      if (matchMedia("(max-width: 860px)").matches) main.querySelector("#chord-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }));
    main.querySelectorAll("[data-line-row]").forEach((r) => r.addEventListener("click", () => {
      if (!st.compare) return;
      st.line = Number(r.dataset.lineRow);
      const el = main.querySelector("[data-pages]");
      if (el && st.pages) { el.innerHTML = pagesHtml(st.pages, st.line); el.querySelector(".hl")?.scrollIntoView({ behavior: "smooth", block: "center" }); }
    }));
    main.querySelectorAll("[data-act=compare]").forEach((b) => b.addEventListener("click", () => { st.compare = !st.compare; render(); }));
    main.querySelectorAll("[data-act=fix]").forEach((b) => b.addEventListener("click", () => openFix(st, (song) => { st.song = song; drawnCache.clear(); render(); })));
    main.querySelectorAll("[data-act=page-instrument]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { st.song = await api.call(`/songs/${st.song.id}`, { method: "PATCH", json: { page_instrument: b.dataset.value } }); drawnCache.clear(); render(); }
      catch (e) { b.disabled = false; alert(e.message); }
    }));
    main.querySelectorAll("[data-play]").forEach((b) => b.addEventListener("click", () => playThing(b.dataset.play)));
  }

  function playThing(what) {
    const { song } = st;
    const m = songModel(song, st.view);
    if (what === "headline") return M.playScale(m.headline.concert.staff);
    if (what.startsWith("scale:")) return M.playScale(m.others[Number(what.slice(6))].concert.staff);
    if (what.startsWith("cscale:")) {
      const [, sym, i] = what.split(":");
      return M.playScale(song.chords.find((c) => c.symbol === sym).scales[Number(i)].concert.staff);
    }
    if (what.startsWith("ctones:")) {
      const c = song.chords.find((x) => x.symbol === what.slice(7));
      return M.playChord(M.stackTones(c.concert.tones, Number((c.scales[0]?.concert.staff[0] ?? "C4").slice(-1))));
    }
    if (what.startsWith("melody")) {
      const tempo = (song.timing?.tempo || 96) * (what === "melody-slow" ? 0.6 : 1);
      return M.play(song.melody.notes.filter((n) => n.concert).map((n) => ({ pitch: n.concert, start: n.start, length: n.length })), tempo);
    }
  }

  render();
}

function scaleWhy(s) {
  if (s.kind === "minor_pentatonic") return "The same five notes, starting lower. Sounds darker.";
  if (s.kind === "blues") return "Adds the blue note, marked in orange. Grittier.";
  return s.reason ? s.reason.charAt(0).toUpperCase() + s.reason.slice(1) + "." : "";
}
function blueNotes(s, side) {
  if (s.kind !== "blues") return [];
  // the blue note is the one the minor pentatonic doesn't have: the sixth of seven notes from the root is not it; find the flat fifth
  const staff = s[side].staff;
  const root = M.midi(staff[0]);
  return staff.map((p, i) => ((M.midi(p) - root) % 12 + 12) % 12 === 6 ? i : -1).filter((i) => i >= 0);
}

function hero(song, m, names) {
  const k = song.key;
  const other = m.written
    ? `Concert key ${M.keyText(k.concert, names, { short: true })}, as the piano plays it.`
    : song.view?.written_key ? `${m.instName} plays it in ${M.keyText(song.view.written_key, names, { short: true })}.` : "";
  const runners = (k.runners_up || []).filter((r) => r.probability >= 0.05).map((r) => M.keyText(r.key, names, { short: true }));
  const sure = k.basis === "stated" ? "Stated on the sheet." : `${Math.round(k.confidence * 100)}% sure.${runners.length ? ` Also possible${m.written ? " (concert)" : ""}: ${runners.join(", ")}.` : ""}`;
  const h = m.headline;
  return `<section class="hero" aria-labelledby="key-h">
    <div class="keycol">
      <div class="kick" id="key-h">Key${m.written ? ` · for ${esc(m.instName.toLowerCase())}` : " · concert pitch"}</div>
      <div class="bigkey">${esc(M.keyText(m.key, names, { short: true }))}</div>
      <div class="sub">${esc(M.keyAside(m.key, names))}</div>
      <div class="sub">${esc(other)}</div>
      <div style="flex:1"></div>
      <div class="sub" style="font-size:14px">${esc(sure)}</div>
      <div><button class="btn" type="button" data-act="fix">Wrong key? Fix it</button></div>
    </div>
    ${h ? `<div class="scalecol">
      <div class="row spread"><span class="kick">Play this first</span><button class="btn small play" type="button" data-play="headline"><span data-ic="play" data-s="14"></span>Play</button></div>
      <div style="font-size:24px;font-weight:700">${esc(M.scaleLabel(h.kind, h[m.side].root, names))}</div>
      <div class="box">${M.staffSvg(h[m.side].staff, { fifths: m.fifths, names, label: "The key's pentatonic" })}</div>
      <div class="sub" style="font-size:14px">Works over the whole song.</div>
    </div>` : ""}
  </section>`;
}

function sheetSection(song, m) {
  const sm = song.sheet_music;
  const concertPage = sm.page_instrument === "concert";
  const facts = [`${sm.views} view${sm.views === 1 ? "" : "s"} joined`, `${sm.systems} lines`, `${sm.measures} bars read`].join(" · ");
  return `<section class="card" aria-labelledby="sheet-h" style="display:flex;flex-direction:column;gap:12px">
    <div class="row spread"><div><h2 id="sheet-h" style="font-size:22px">The piece, drawn fresh</h2><div class="muted" style="font-size:14px">${esc(facts)}</div></div>
      <span class="muted" style="font-size:14px">Check it against the original before you print.</span></div>
    <div class="notice ok row spread">
      <span>${sm.part_name ? `The page says <b>${esc(sm.part_name)}</b>, so it` : "It"} was read as ${concertPage ? "concert pitch (piano or voice)" : `already written for ${esc(m.instName.toLowerCase())}`}${concertPage ? ` and written up for ${esc(m.instName.toLowerCase())}` : ", so it isn't transposed again"}.</span>
      <button class="btn small" type="button" data-act="page-instrument" data-value="${concertPage ? esc(song.view.instrument) : "concert"}">${concertPage ? `It's already for ${esc(m.instName.toLowerCase())}` : "It's concert pitch"}</button>
    </div>
    <div class="drawn" data-drawn="sheet"><div class="loading" style="padding:30px">Drawing the piece…</div></div>
  </section>`;
}

function pagesHtml(p, line) {
  if (!p.pages.length) return `<div class="muted">This song has no pages to show.</div>`;
  return p.pages.map((pg) => {
    const box = p.lines.find((l) => l.line === line && l.page === pg.index);
    const hl = box && pg.width && pg.height
      ? `<div class="hl" style="left:${(box.box[0] / pg.width) * 100}%;top:${(box.box[1] / pg.height) * 100}%;width:${((box.box[2] - box.box[0]) / pg.width) * 100}%;height:${((box.box[3] - box.box[1]) / pg.height) * 100}%"></div>` : "";
    return `<figure style="margin:0"><div class="pageimg"><img src="${esc(pg.image)}" alt="Page ${pg.index + 1} of the original" loading="lazy">${hl}</div>
      <figcaption class="muted" style="font-size:13px;padding-top:4px">Page ${pg.index + 1}</figcaption></figure>`;
  }).join("");
}

function chordButton(pl, song, m, names, st, lineNo, { stand = false } = {}) {
  if (!pl.chord) {
    return `<span class="chord ${pl.readable === false ? "unread" : "nc"}" title="${pl.readable === false ? "Couldn't read this as a chord" : "No chord"}"><span class="sy">${esc(pl.readable === false ? pl.text : "N.C.")}</span><span class="hn"></span></span>`;
  }
  const info = song.chords.find((c) => c.symbol === pl.chord);
  const sym = m.written ? pl.written ?? info?.written?.symbol ?? pl.chord : pl.chord;
  const clash = info?.clashes?.[m.side]?.length > 0;
  const root = M.chordRoot(sym);
  const hint = root && names !== "letters" && names !== "none" && names !== "german" ? M.noteNames(root, names === "both" ? "russian" : names)[0] : "";
  const on = !stand && st.sel === pl.chord;
  return `<button type="button" class="chord ${clash ? "clash" : ""} ${on ? "on" : ""}" ${stand ? "tabindex=\"-1\"" : `data-chord="${esc(pl.chord)}" data-line="${lineNo}"`} aria-pressed="${on}" aria-label="${esc(M.prettyChord(sym))}${clash ? ", the song scale clashes here" : ""}">
    <span class="sy">${esc(M.prettyChord(sym))}</span><span class="hn">${esc(hint) || "&nbsp;"}</span></button>`;
}

function lineHtml(line, song, m, names, st, lineNo, opts = {}) {
  const lyrics = line.lyrics || "";
  const chords = [...line.chords].sort((a, b) => (a.pos ?? a.beat ?? 0) - (b.pos ?? b.beat ?? 0));
  const segs = [];
  const placed = chords.every((c) => c.pos !== null && c.pos !== undefined) && lyrics;
  if (placed) {
    const first = chords.length ? Math.min(chords[0].pos, lyrics.length) : lyrics.length;
    if (first > 0) segs.push({ chord: null, text: lyrics.slice(0, first) });
    chords.forEach((c, i) => {
      const from = Math.min(c.pos, lyrics.length);
      const to = i + 1 < chords.length ? Math.min(chords[i + 1].pos, lyrics.length) : lyrics.length;
      segs.push({ chord: c, text: lyrics.slice(from, Math.max(from, to)) });
    });
  } else {
    chords.forEach((c) => segs.push({ chord: c, text: "" }));
    if (lyrics) segs.push({ chord: null, text: lyrics });
  }
  // a chord inside a word splits it; a faint hyphen keeps it reading as one word
  segs.forEach((s, i) => { s.mid = /\p{L}$/u.test(s.text) && /^\p{L}/u.test(segs[i + 1]?.text ?? ""); });
  return `<div class="sheetline" data-line-row="${lineNo}" style="${st.line === lineNo && st.compare ? "outline:2px solid var(--clash);outline-offset:4px;border-radius:6px" : ""}">${segs.map((s) => `<div class="seg2">${s.chord ? chordButton(s.chord, song, m, names, st, lineNo, opts) : chords.length ? `<span class="chord nc" aria-hidden="true" style="visibility:hidden"><span class="sy">&nbsp;</span><span class="hn"></span></span>` : ""}<span class="ly">${esc(s.text)}${s.mid ? `<span class="hy" aria-hidden="true">-</span>` : ""}</span></div>`).join("")}${line.repeat ? `<span class="rep">×${line.repeat}</span>` : ""}</div>`;
}

function chartHtml(song, m, names, st, opts = {}) {
  let n = 0;
  return song.form.map((sec) => `<div class="kick secl">${esc(sec.label || sec.kind || "")}${sec.repeat ? ` ×${sec.repeat}` : ""}</div>
    ${sec.lines.map((line) => lineHtml(line, song, m, names, st, n++, opts)).join("")}`).join("");
}

function chartSection(song, m, names, st) {
  const info = song.chords.find((c) => c.symbol === st.sel);
  const chips = !song.form.length
    ? `<div class="chips">${song.chords.map((c) => chordButton({ chord: c.symbol, written: c.written.symbol }, song, m, names, st, -1)).join("")}</div>` : "";
  return `<section class="split" aria-labelledby="chart-h">
    <div class="card main"><div class="row spread" style="margin-bottom:12px"><h2 id="chart-h" style="font-size:22px">${song.form.length ? "Chords and lyrics" : "Chords"}</h2>
      <span class="muted" style="font-size:14px">Tap a chord for its scale. Orange means the song scale clashes there.</span></div>
      ${chips}${chartHtml(song, m, names, st)}</div>
    ${info ? chordPanel(info, song, m, names) : ""}
  </section>`;
}

function chordPanel(c, song, m, names) {
  const spell = c[m.side];
  const otherSpell = m.written ? c.concert : c.written;
  const clash = c.clashes?.[m.side] ?? [];
  const root = M.parsePitch(spell.root);
  const startOct = Number((c.scales[0]?.[m.side].staff[0] ?? "C4").slice(-1));
  const fam = { major: "Major", minor: "Minor", dominant: "Dominant 7th", half_diminished: "Half-diminished", diminished: "Diminished", augmented: "Augmented", suspended: "Suspended" }[c.family] ?? (c.family || "");
  const verdict = clash.length
    ? `The song scale has ${clash.map((n) => M.noteText(n, names)).join(" and ")}, which rub${clash.length > 1 ? "" : "s"} against this chord. Use the scale below here.`
    : "The song scale fits here. Stay on it, or try the scale below.";
  return `<aside class="card side sticky" id="chord-panel" aria-labelledby="cp-h" style="display:flex;flex-direction:column;gap:10px">
    <div class="row" style="gap:12px;align-items:baseline"><h2 id="cp-h" style="font-size:34px">${esc(M.prettyChord(spell.symbol))}</h2>
      <span class="muted">${m.written ? "concert" : esc(m.instName.toLowerCase())} ${esc(M.prettyChord(otherSpell.symbol))}</span></div>
    <div style="color:var(--ink2)">${esc(fam)} chord${root ? ` · root ${esc(M.noteText(root, names))}` : ""} · ${c.count}× in the song</div>
    <div class="notice ${clash.length ? "warn" : "ok"}">${esc(verdict)}</div>
    ${c.scales.map((s, i) => `<div class="row spread" style="padding-top:4px"><b>${esc(M.scaleLabel(s.kind, s[m.side].root, names))}</b><button class="btn small" type="button" data-play="cscale:${esc(c.symbol)}:${i}">Play</button></div>
      ${M.staffSvg(s[m.side].staff, { fifths: m.fifths, names, mark: s[m.side].staff.map((p, j) => (clash.length && !song.scales[0]?.[m.side].notes.includes(p.replace(/-?\d+$/, "")) ? j : -1)).filter((j) => j >= 0) })}`).join("")}
    <div class="row spread"><b>Chord notes</b><button class="btn small" type="button" data-play="ctones:${esc(c.symbol)}">Play</button></div>
    ${M.staffSvg(M.stackTones(spell.tones, startOct), { fifths: m.fifths, names })}
  </aside>`;
}

// ---------- fixing what was read wrong ----------

const MAJOR = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const MINOR = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"];

function openFix(st, done) {
  const { song, names } = st;
  const c = song.corrections;
  const shown = names === "none" ? "letters" : names;
  const sheetChords = [...new Set(song.form.flatMap((s) => s.lines.flatMap((l) => l.chords.map((p) => p.text))))];
  const fromSheet = ["text", "pdf", "photo"].includes(song.identity.source);
  const bChoice = fromSheet && (c.b_is_flat !== null || sheetChords.some((t) => /^[BH]/.test(t)) || song.notes.some((n) => n.code === "b_flat_guess"));
  const keyOpts = [["major", MAJOR], ["minor", MINOR]].flatMap(([mode, tonics]) => tonics.map((t) => {
    const v = `${t} ${mode}`;
    return `<option value="${v}" ${c.key === v ? "selected" : ""}>${esc(M.keyText({ tonic: t, mode }, shown, { short: true }))}${shown !== "letters" ? ` (${esc(M.keyText({ tonic: t, mode }, "letters"))})` : ""}</option>`;
  })).join("");
  const dlg = document.createElement("dialog");
  dlg.innerHTML = `<form method="dialog">
    <div class="row spread"><h2 style="font-size:22px">Fix what was read wrong</h2><button class="btn small" value="cancel" formnovalidate>Close</button></div>
    <div class="fields">
      <div><label class="lbl" for="fx-key">Key (concert, as the piano plays it)</label>
        <select class="field" id="fx-key"><option value="">${song.melody?.source === "audio" ? "Found from the recording" : "Found from the chords"}</option>${keyOpts}</select></div>
      ${song.form.length ? `<div><label class="lbl" for="fx-capo">Capo</label><input class="field" id="fx-capo" type="number" min="0" max="12" value="${c.capo ?? ""}" placeholder="As on the sheet"></div>` : ""}
      <div><label class="lbl" for="fx-title">Title</label><input class="field" id="fx-title" value="${esc(song.identity.title ?? "")}"></div>
      <div><label class="lbl" for="fx-artist">Artist</label><input class="field" id="fx-artist" value="${esc(song.identity.artist ?? "")}"></div>
      ${bChoice ? `<div><label class="lbl" for="fx-b">A plain B on the sheet means</label><select class="field" id="fx-b">
        <option value="" ${c.b_is_flat === null ? "selected" : ""}>Work it out from the sheet</option>
        <option value="true" ${c.b_is_flat === true ? "selected" : ""}>B♭ (си-бемоль), as on Russian sheets</option>
        <option value="false" ${c.b_is_flat === false ? "selected" : ""}>B natural (си)</option></select></div>` : ""}
      ${song.melody ? `<div><label class="lbl" for="fx-oct">Melody octave</label><select class="field" id="fx-oct">
        <option value="" ${c.melody_octave === null ? "selected" : ""}>Fit my range</option>
        ${[2, 1, 0, -1, -2].map((o) => `<option value="${o}" ${c.melody_octave === o ? "selected" : ""}>${{ 2: "Two octaves up", 1: "An octave up", 0: "No octave move", "-1": "An octave down", "-2": "Two octaves down" }[o]}</option>`).join("")}</select></div>` : ""}
    </div>
    ${sheetChords.length ? `<div class="fields"><div><label class="lbl" for="fx-chord">A chord as written on the sheet</label><select class="field" id="fx-chord"><option value=""></option>${sheetChords.map((t) => `<option>${esc(t)}</option>`).join("")}</select></div>
      <div><label class="lbl" for="fx-to">should be (empty removes it)</label><input class="field" id="fx-to" placeholder="e.g. F#m7" autocapitalize="off"></div></div>` : ""}
    <div class="err" id="fx-err" role="alert"></div>
    <div class="row spread">
      <button class="btn danger" type="button" id="fx-del">Delete this song</button>
      <div class="row" style="gap:8px">
        ${c.key || c.capo !== null || c.chords.length || c.title || c.artist || c.b_is_flat !== null || c.melody_octave !== null ? `<button class="btn" type="button" id="fx-undo">Undo all my fixes</button>` : ""}
        <button class="btn primary" type="button" id="fx-save">Save</button></div>
    </div>
    <div class="muted" style="font-size:13px">Saving runs again only the steps your fix touches.</div>
  </form>`;
  document.body.append(dlg);
  dlg.addEventListener("close", () => dlg.remove());
  dlg.showModal();
  const $ = (id) => dlg.querySelector(`#${id}`);
  const err = $("fx-err");
  async function send(patch) {
    err.textContent = "";
    for (const b of dlg.querySelectorAll("button")) b.disabled = true;
    try { const song2 = await api.call(`/songs/${song.id}`, { method: "PATCH", json: patch }); dlg.close(); done(song2); }
    catch (e) { err.textContent = e.message; for (const b of dlg.querySelectorAll("button")) b.disabled = false; }
  }
  $("fx-save").addEventListener("click", () => {
    const patch = {};
    const key = $("fx-key").value;
    if (key !== (c.key ?? "")) patch.key = key || null;
    if ($("fx-capo")) { const v = $("fx-capo").value.trim(); if (v !== String(c.capo ?? "")) patch.capo = v === "" ? null : Number(v); }
    for (const f of ["title", "artist"]) { const v = $(`fx-${f}`).value.trim(); if (v !== (song.identity[f] ?? "")) patch[f] = v || null; }
    if ($("fx-b")) { const v = $("fx-b").value; const cur = c.b_is_flat === null ? "" : String(c.b_is_flat); if (v !== cur) patch.b_is_flat = v === "" ? null : v === "true"; }
    if ($("fx-oct")) { const v = $("fx-oct").value; if (v !== String(c.melody_octave ?? "")) patch.melody_octave = v === "" ? null : Number(v); }
    if ($("fx-chord")?.value) patch.chords = [...c.chords, { original: $("fx-chord").value, to: $("fx-to").value.trim() }];
    if (!Object.keys(patch).length) return dlg.close();
    send(patch);
  });
  $("fx-undo")?.addEventListener("click", () => send({ key: null, capo: null, title: null, artist: null, chords: [], b_is_flat: null, melody_octave: null }));
  $("fx-del").addEventListener("click", async () => {
    if (!confirm("Delete this song from your library?")) return;
    try { await api.call(`/songs/${song.id}`, { method: "DELETE" }); dlg.close(); go("/library"); } catch (e) { err.textContent = e.message; }
  });
}

// ---------- music stand ----------

async function standView(id) {
  const [song, settings] = await Promise.all([api.call(`/songs/${id}`), api.settings()]);
  const names = settings.names;
  const m = songModel(song, sessionStorage.getItem("ss-view") || "written");
  const h = m.headline;
  main.innerHTML = "";
  standRoot.innerHTML = `<div class="stand" id="stand" tabindex="-1">
    <header><a href="/songs/${id}">Done</a><div style="flex:1;text-align:center;font-weight:600">${esc(song.identity.title || "Song")} · ${esc(M.keyText(m.key, names, { short: true }))}</div>
      <span id="awake" class="muted" style="font-size:14px"></span></header>
    <div class="body">
      ${h ? `<div><div class="kick brass">${esc(M.scaleLabel(h.kind, h[m.side].root, names))}</div>${M.staffSvg(h[m.side].staff, { fifths: m.fifths, names })}</div>` : ""}
      ${song.melody?.notes?.length && !song.sheet_music ? `<div class="drawn" data-drawn="melody"></div>` : ""}
      ${song.sheet_music ? `<div class="drawn" data-drawn="sheet"></div>` : ""}
      ${song.form.length ? `<div>${chartHtml(song, m, names, { line: null }, { stand: true })}</div>` : ""}
    </div>
    <button class="edge l" type="button" aria-label="Previous page" data-turn="-1"></button>
    <button class="edge r" type="button" aria-label="Next page" data-turn="1"></button></div>`;
  const box = standRoot.querySelector("#stand");
  for (const el of box.querySelectorAll("[data-drawn]")) {
    drawn(id, { part: el.dataset.drawn, names, view: m.side === "written" ? "written" : "concert" }).then((svg) => { el.innerHTML = svg; }).catch(() => { el.remove(); });
  }
  const turn = (d) => box.scrollBy({ top: d * (box.clientHeight - 90), behavior: "smooth" });
  box.querySelectorAll("[data-turn]").forEach((b) => b.addEventListener("click", () => turn(Number(b.dataset.turn))));
  // page-turn pedals send arrow keys or Page Up/Down
  const onKey = (e) => {
    if (["ArrowRight", "ArrowDown", "PageDown", " "].includes(e.key)) { e.preventDefault(); turn(1); }
    if (["ArrowLeft", "ArrowUp", "PageUp"].includes(e.key)) { e.preventDefault(); turn(-1); }
    if (e.key === "Escape") go(`/songs/${id}`);
  };
  document.addEventListener("keydown", onKey);
  box.focus();
  let lock = null;
  const awake = standRoot.querySelector("#awake");
  async function keepAwake() {
    try { lock = await navigator.wakeLock.request("screen"); awake.textContent = "Screen stays on"; }
    catch { awake.textContent = ""; }
  }
  if ("wakeLock" in navigator) keepAwake();
  const onVis = () => { if (document.visibilityState === "visible" && "wakeLock" in navigator) keepAwake(); };
  document.addEventListener("visibilitychange", onVis);
  leave = () => { document.removeEventListener("keydown", onKey); document.removeEventListener("visibilitychange", onVis); lock?.release?.(); standRoot.innerHTML = ""; };
}

// ---------- library ----------

const FILTERS = [["all", "All"], ["sheet", "Chord sheets", ["text", "pdf", "photo"]], ["song", "Songs", ["audio", "link"]], ["music", "Sheet music", ["screenshots", "video"]]];

async function libraryView() {
  const settings = await api.settings();
  const st = { q: new URLSearchParams(location.search).get("q") ?? "", sort: store.get("ss-sort", "recent"), filter: "all", list: null };
  async function load() {
    st.list = await api.call(`/songs?${new URLSearchParams({ q: st.q, sort: st.sort, limit: 500 })}`);
    renderList();
  }
  main.innerHTML = `<div class="page">
    <div class="row spread"><h1 class="title" style="font-size:34px">Library</h1>
      <div style="flex:0 1 420px;min-width:220px"><label class="sr" for="q">Search songs</label><input class="field" id="q" type="search" placeholder="Search by title, artist or lyrics" value="${esc(st.q)}"></div></div>
    <div class="row spread"><div class="row" role="group" aria-label="Show" id="filters" style="gap:8px"></div>
      <div class="seg" role="group" aria-label="Sort"><button type="button" data-sort="recent">Newest</button><button type="button" data-sort="title">A to Z</button></div></div>
    <div id="list"><div class="loading">Loading…</div></div></div>`;
  function renderList() {
    const songs = st.list?.songs ?? [];
    const f = FILTERS.find(([k]) => k === st.filter);
    const shown = f[2] ? songs.filter((s) => f[2].includes(s.source)) : songs;
    main.querySelector("#filters").innerHTML = FILTERS.map(([k, label, src]) => {
      const n = src ? songs.filter((s) => src.includes(s.source)).length : songs.length;
      return `<button type="button" class="pill ${k === st.filter ? "on" : ""}" aria-pressed="${k === st.filter}" data-filter="${k}">${label} ${n}</button>`;
    }).join("");
    main.querySelectorAll("[data-sort]").forEach((b) => { b.classList.toggle("on", b.dataset.sort === st.sort); b.setAttribute("aria-pressed", b.dataset.sort === st.sort); });
    main.querySelector("#list").innerHTML = shown.length ? `<div class="tiles">${shown.map((s) => tile(s, settings.names)).join("")}</div>`
      : `<div class="card empty">${st.q ? "No songs match that search." : `Nothing here yet. <a href="/">Import a song</a>.`}</div>`;
    main.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => { st.filter = b.dataset.filter; renderList(); }));
  }
  let t = null;
  main.querySelector("#q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { st.q = e.target.value.trim(); history.replaceState(null, "", st.q ? `/library?q=${encodeURIComponent(st.q)}` : "/library"); load(); }, 220); });
  main.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => { st.sort = b.dataset.sort; store.set("ss-sort", st.sort); load(); }));
  await load();
}

// ---------- settings ----------

async function settingsView() {
  const [settings, instruments, health] = await Promise.all([api.settings(true), api.instruments(), api.health().catch(() => null)]);
  const st = { s: { ...settings }, theme: store.get("ss-theme", "auto"), saved: "" };
  const NAT = ["C", "D", "E", "F", "G", "A", "B"];
  function notesBetween(lo, hi) {
    const out = [];
    for (let o = 3; o <= 6; o++) for (const l of NAT) { const n = `${l}${o}`; if (M.midi(n) >= M.midi(lo) && M.midi(n) <= M.midi(hi)) out.push(n); }
    if (!out.includes(lo)) out.unshift(lo);
    if (!out.includes(hi)) out.push(hi);
    return out;
  }
  function render() {
    const inst = instruments.find((i) => i.id === st.s.instrument) ?? instruments[0];
    const range = notesBetween(inst.lowest, inst.highest);
    const lo = st.s.comfortable_low ?? inst.comfortable_low;
    const hi = st.s.comfortable_high ?? inst.comfortable_high;
    const noteOpt = (n, cur) => `<option value="${n}" ${n === cur ? "selected" : ""}>${esc(M.noteText(n, st.s.names === "none" ? "russian" : st.s.names))} (${n.replace("#", "♯").replace(/([A-G])b/, "$1♭")})</option>`;
    main.innerHTML = `<div class="page narrow">
      <div class="row spread"><h1 class="title" style="font-size:34px">Settings</h1><span class="muted" role="status">${esc(st.saved)}</span></div>
      <section class="card" aria-labelledby="nm-h" style="display:flex;flex-direction:column;gap:14px">
        <h2 id="nm-h" style="font-size:20px">Note names under the staff</h2>
        <div class="opts" role="radiogroup" aria-label="Note names">${M.NAME_SYSTEMS.map(([k, label, eg]) => `<button type="button" role="radio" class="opt ${k === st.s.names ? "on" : ""}" aria-checked="${k === st.s.names}" data-names="${k}"><b>${esc(label)}</b><small>${esc(eg)}</small></button>`).join("")}</div>
        <div style="background:var(--chip);border-radius:12px;padding:6px 12px">${M.staffSvg(["D4", "E4", "F#4", "A4", "B4", "D5"], { fifths: 2, names: st.s.names })}</div>
        <div class="muted" style="font-size:14px">Chord symbols stay in letters, as sheets write them, with the root in your names as a hint.</div>
      </section>
      <section class="card fields" aria-labelledby="in-h">
        <h2 id="in-h" style="font-size:20px;grid-column:1/-1">Your instrument and range</h2>
        <div><label class="lbl" for="st-inst">Instrument</label><select class="field" id="st-inst">${instruments.map((i) => `<option value="${i.id}" ${i.id === inst.id ? "selected" : ""}>${esc(i.name)}</option>`).join("")}</select></div>
        <div><label class="lbl" for="st-lo">Lowest comfortable note</label><select class="field" id="st-lo">${range.map((n) => noteOpt(n, lo)).join("")}</select></div>
        <div><label class="lbl" for="st-hi">Highest comfortable note</label><select class="field" id="st-hi">${range.map((n) => noteOpt(n, hi)).join("")}</select></div>
        <div class="muted" style="font-size:14px;grid-column:1/-1">Written notes. Melodies move by whole octaves to sit in this range; notes still outside are marked.</div>
      </section>
      <section class="card fields" aria-labelledby="mo-h">
        <h2 id="mo-h" style="font-size:20px;grid-column:1/-1">Reading and look</h2>
        <div><label class="lbl" for="st-reader">Photo reader</label><select class="field" id="st-reader">
          <option value="local" ${st.s.photo_reader === "local" ? "selected" : ""}>On this computer only</option>
          <option value="ai" ${st.s.photo_reader === "ai" ? "selected" : ""}>On this computer, AI for messy photos</option></select></div>
        <div><span class="lbl">Theme</span><div class="seg" role="group" aria-label="Theme">${[["auto", "Device"], ["light", "Light"], ["dark", "Dark"]].map(([k, l]) => `<button type="button" class="${st.theme === k ? "on" : ""}" aria-pressed="${st.theme === k}" data-theme="${k}">${l}</button>`).join("")}</div></div>
      </section>
      ${health ? `<section class="card" aria-labelledby="hl-h" style="display:flex;flex-direction:column;gap:8px"><h2 id="hl-h" style="font-size:20px">On this computer</h2>
        <div class="muted" style="font-size:14px">SoundSelect ${esc(health.version)} · ${health.songs} songs</div>
        <div class="chips">${Object.entries({ pdf_output: "PDF output", pdf_reading: "PDF sheets", photo_reading: "Photos", sheet_music: "Sheet music", audio: "Songs from audio", links: "Links" }).map(([k, l]) => `<span class="status ${health.tools[k] ? "done" : ""}">${health.tools[k] ? "✓" : "–"} ${l}</span>`).join("")}</div></section>` : ""}
    </div>`;
    main.querySelectorAll("[data-names]").forEach((b) => b.addEventListener("click", () => save({ names: b.dataset.names })));
    main.querySelector("#st-inst").addEventListener("change", (e) => save({ instrument: e.target.value, comfortable_low: null, comfortable_high: null }));
    main.querySelector("#st-lo").addEventListener("change", (e) => save({ comfortable_low: e.target.value }));
    main.querySelector("#st-hi").addEventListener("change", (e) => save({ comfortable_high: e.target.value }));
    main.querySelector("#st-reader").addEventListener("change", (e) => save({ photo_reader: e.target.value }));
    main.querySelectorAll("[data-theme]").forEach((b) => b.addEventListener("click", () => {
      st.theme = b.dataset.theme; store.set("ss-theme", st.theme);
      if (st.theme === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = st.theme;
      render();
    }));
  }
  async function save(patch) {
    const before = { ...st.s };
    st.s = { ...st.s, ...patch };
    render();
    try { st.s = await api.saveSettings(patch); st.saved = "Saved"; }
    catch (e) { st.s = before; st.saved = e.message; }
    render();
  }
  render();
}

// ---------- start ----------

api.health().then((h) => { document.getElementById("ver").textContent = `Version ${h.version}`; }).catch(() => {});
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
route();
startArt();
