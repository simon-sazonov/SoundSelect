// Loads the app from the device after the first visit, and keeps the songs you opened for use
// without a connection. The app files come from the cache first (refreshed in the background);
// songs and drawings come from the app first, and from the cache when it can't be reached.

const SHELL = "ss-shell-v2";
const SONGS = "ss-songs-v1";
const FILES = ["/", "/app/app.js", "/app/api.js", "/app/music.js", "/app/art.js", "/app/styles.css", "/music-font.css", "/app/manifest.webmanifest", "/app/icon.svg",
  "/app/fonts/fonts.css", "/app/fonts/jost-latin.woff2", "/app/fonts/cormorant-latin.woff2", "/app/fonts/caveat-latin.woff2", "/app/fonts/jost-cyrillic.woff2", "/app/fonts/cormorant-cyrillic.woff2"];
const PAGES = /^\/(import|library|settings|batches\/[\w-]+|songs\/[\w-]+(\/stand)?)?$/;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, SONGS].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // every screen is the same page; the app picks the screen from the address
  if (req.mode === "navigate" && PAGES.test(url.pathname)) {
    e.respondWith(fresh(req, SHELL, "/"));
    return;
  }
  if (url.pathname.startsWith("/app/") || url.pathname === "/music-font.css") {
    e.respondWith(caches.open(SHELL).then(async (c) => {
      const hit = await c.match(req);
      const net = fetch(req).then((res) => { if (res.ok) c.put(req, res.clone()); return res; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  // songs, their drawings and settings: the app first, the copy when offline
  if (/^\/api\/v1\/(songs\/[\w-]+(\/score|\/pages(\/\d+\.png)?)?|songs|settings|instruments)$/.test(url.pathname)) {
    e.respondWith(fresh(req, SONGS));
  }
});

async function fresh(req, cacheName, key) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(key ?? req, res.clone());
    return res;
  } catch {
    const hit = await cache.match(key ?? req);
    if (hit) return hit;
    throw new Error("offline");
  }
}
