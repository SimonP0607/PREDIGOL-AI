/*
 * PrediGol service worker: makes the web app installable (PWA), shows a page of its own when there is no
 * connection, and keeps the app's own static files (scripts, styles, icons) in a cache.
 *
 * What it NEVER caches, by design:
 *   - the API (/api/*) and /health: odds, picks, scores and the account are always read live, and a cached
 *     answer could show yesterday's price as today's or one account's data to another;
 *   - pages (HTML): a navigation always goes to the network; only when the network fails is the offline page
 *     shown - never a stale copy of a page;
 *   - anything from another origin (team logos): the browser's own HTTP cache handles those.
 *
 * Updates are CONTROLLED: a new version of this file installs in the background and then WAITS. The page shows
 * "a new version is ready" and only when the reader accepts does it send SKIP_WAITING; the page reloads once the new
 * worker takes over. An open tab never has its scripts swapped under it in the middle of a match.
 *
 * Notices on the reader's devices (plan UX, B7; section 34): PrediGol's messenger sends each one encrypted for this
 * browser alone (backend fbi.messaging.push_jobs) - a title, a line, the page it opens, its tag and its category, under
 * 4 KB. Every push shows a notification (Safari withdraws the permission otherwise), the same tag replaces the older one
 * on the screen, and a tap opens its page of PrediGol - only PrediGol's: another site's address, a page written as
 * //host, or a message that cannot be read opens Inicio. The page opened carries ?notice=<category> so that the app
 * counts the opening (notification_opened) and then takes the mark away.
 *
 * Bump VERSION to retire every cache at the next visit (v3: the offline page clears the iPhone notch and its
 * retry button is 44 px tall - mobile UX audit, Oct 2026; v4: the notices of B7).
 */
const VERSION = "predigol-v4";
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

const NOTICE_ICON = "/brand/icon-192.png";
const NOTICE_BADGE = "/brand/predigol-mark-64.png";
const HOME = "/home";

/** The page a notice opens: a path of PrediGol (never another site, not even //host), marked with its category. */
function pageOf(url, category) {
  let target = null;
  if (typeof url === "string" && /^\/(?![/\\])/.test(url)) {
    try {
      target = new URL(url, self.location.origin);
    } catch {
      target = null;
    }
  }
  if (!target || target.origin !== self.location.origin)
    target = new URL(HOME, self.location.origin);
  if (typeof category === "string" && /^[a-z]{1,20}$/.test(category)) {
    target.searchParams.set("notice", category);
  }
  return `${target.pathname}${target.search}${target.hash}`;
}

/** What a push carries, read defensively: whatever arrives, the reader sees a notification of PrediGol. */
function noticeOf(data) {
  const notice = { title: "PrediGol", body: "", tag: "predigol", url: pageOf(HOME, null) };
  if (!data || typeof data !== "object") return notice;
  if (typeof data.title === "string" && data.title.trim()) notice.title = data.title.slice(0, 120);
  if (typeof data.body === "string") notice.body = data.body.slice(0, 300);
  if (typeof data.tag === "string" && data.tag) notice.tag = data.tag.slice(0, 120);
  notice.url = pageOf(data.url, data.category);
  return notice;
}

self.addEventListener("push", (event) => {
  let data = null;
  try {
    data = event.data ? event.data.json() : null;
  } catch {
    data = null;
  }
  const notice = noticeOf(data);
  event.waitUntil(
    self.registration.showNotification(notice.title, {
      body: notice.body,
      tag: notice.tag,
      icon: NOTICE_ICON,
      badge: NOTICE_BADGE,
      data: { url: notice.url },
    }),
  );
});

/** A window of PrediGol already open goes to the page and comes to the front; otherwise a new one opens. */
async function openPage(url) {
  const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  for (const client of windows) {
    if (new URL(client.url).origin !== self.location.origin) continue;
    if (typeof client.navigate === "function") {
      try {
        const moved = await client.navigate(url);
        if (moved) return moved.focus();
      } catch {
        // a window this worker does not control cannot be moved: a new one opens below
      }
    }
  }
  return self.clients.openWindow(url);
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data;
  const url = data && typeof data.url === "string" ? pageOf(data.url, null) : pageOf(HOME, null);
  event.waitUntil(openPage(url));
});

self.addEventListener("fetch", (event) => {
  const route = routeFor(new URL(event.request.url), event.request);
  if (route === "navigate") event.respondWith(networkOrOffline(event.request));
  else if (route === "static") event.respondWith(cacheFirst(event.request));
});
