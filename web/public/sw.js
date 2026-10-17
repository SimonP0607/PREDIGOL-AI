/*
 * PrediGol service worker: makes the web app installable (PWA), shows a page of its own when there is no
 * connection, and keeps the app's own static files (scripts, styles, icons) in a cache.
 *
 * What it NEVER caches, by design:
 *   - the API (/api/*) and /health: odds, picks, scores and the account are always read live, and a cached
 *     answer could show yesterday's price as today's or one account's data to another;
 *   - pages (HTML): a navigation always goes to the network; only when the network fails is the offline page
 *     shown - never a stale copy of a page;
 *   - anything from another origin (fonts, team logos): the browser's own HTTP cache handles those.
 *
 * Updates are CONTROLLED: a new version of this file installs in the background and then WAITS. The page shows
 * "a new version is ready" and only when the reader accepts does it send SKIP_WAITING; the page reloads once the new
 * worker takes over. An open tab never has its scripts swapped under it in the middle of a match.
 *
 * Bump VERSION to retire every cache at the next visit (v3: the offline page clears the iPhone notch and its
 * retry button is 44 px tall - mobile UX audit, Oct 2026).
 */
const VERSION = "predigol-v3";
const STATIC_CACHE = `${VERSION}-static`;
const OFFLINE_URL = "/offline.html";
const PRECACHE = [OFFLINE_URL, "/brand/predigol-mark-128.png", "/manifest.webmanifest"];
const STATIC_LIMIT = 200;

/** What to do with a request: "bypass" (the browser, untouched), "navigate" (network, offline page on
 *  failure) or "static" (cache first, then network). */
function routeFor(url, request) {
  if (request.method !== "GET") return "bypass";
  if (url.origin !== self.location.origin) return "bypass";
  const path = url.pathname;
  if (
    path.startsWith("/api/") ||
    path === "/api" ||
    path === "/health" ||
    path.startsWith("/health/")
  ) {
    return "bypass";
  }
  if (path === "/sw.js") return "bypass";
  if (request.mode === "navigate") return "navigate";
  if (
    path.startsWith("/assets/") ||
    path.startsWith("/brand/") ||
    path === "/manifest.webmanifest" ||
    path === "/favicon.ico" ||
    path === "/apple-touch-icon.png" ||
    path === OFFLINE_URL
  ) {
    return "static";
  }
  return "bypass";
}

async function trim(cache) {
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - STATIC_LIMIT))) await cache.delete(key);
}

async function cacheFirst(request) {
  const cache = await caches.open(STATIC_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok && response.type === "basic") {
    await cache.put(request, response.clone());
    await trim(cache);
  }
  return response;
}

async function networkOrOffline(request) {
  try {
    return await fetch(request);
  } catch (error) {
    const offline = await caches.match(OFFLINE_URL);
    if (offline) return offline;
    throw error;
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)));
});

// The page asks for the switch when the reader accepts the update (src/lib/pwa.ts).
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => !key.startsWith(`${VERSION}-`)).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const route = routeFor(new URL(event.request.url), event.request);
  if (route === "navigate") event.respondWith(networkOrOffline(event.request));
  else if (route === "static") event.respondWith(cacheFirst(event.request));
});
