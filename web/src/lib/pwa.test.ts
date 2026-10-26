/// <reference types="bun" />
/**
 * The installable app: the service worker is registered in production only, and what it caches is decided by
 * routeFor() in public/sw.js - never the API, never a page, never another origin.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  installOrder,
  installPlatform,
  isStandalone,
  markInstalledOnce,
  registerServiceWorker,
  reloadOnStaleChunks,
  SERVICE_WORKER_URL,
  watchForUpdates,
} from "@/lib/pwa";

const ORIGIN = "https://predigol.example";
type Route = "bypass" | "navigate" | "static";
type RouteFor = (url: URL, request: { method: string; mode: string }) => Route;

/** routeFor() out of the real public/sw.js, evaluated against a stand-in for the worker's global scope. */
function loadRouteFor(): RouteFor {
  const source = readFileSync(join(import.meta.dir, "..", "..", "public", "sw.js"), "utf8");
  const self = { location: new URL(ORIGIN), addEventListener: () => undefined };
  const factory = new Function("self", "caches", "fetch", `${source}\nreturn routeFor;`) as (
    self: unknown,
    caches: unknown,
    fetch: unknown,
  ) => RouteFor;
  return factory(self, {}, () => undefined);
}

const routeFor = loadRouteFor();
const at = (path: string, mode = "cors", method = "GET", origin = ORIGIN): Route =>
  routeFor(new URL(path, origin), { method, mode });

describe("what the service worker caches", () => {
  test("the API and health are never intercepted, whatever the request", () => {
    expect(at("/api/v1/home")).toBe("bypass");
    expect(at("/api/v1/matches/12/center")).toBe("bypass");
    expect(at("/api/v1/auth/login", "cors", "POST")).toBe("bypass");
    expect(at("/api/v1/live", "navigate")).toBe("bypass");
    expect(at("/health")).toBe("bypass");
  });

  test("a page goes to the network, with the offline page only when the network fails", () => {
    expect(at("/home", "navigate")).toBe("navigate");
    expect(at("/matches/123", "navigate")).toBe("navigate");
    expect(at("/admin/system", "navigate")).toBe("navigate");
  });

  test("the app's own static files are cached; its own worker script is not", () => {
    expect(at("/assets/index-jUWoWssh.js")).toBe("static");
    expect(at("/assets/styles-DNqR4TiC.css")).toBe("static");
    expect(at("/brand/icon-512.png")).toBe("static");
    expect(at("/manifest.webmanifest")).toBe("static");
    expect(at("/offline.html")).toBe("static");
    expect(at("/sw.js")).toBe("bypass");
  });

  test("another origin (team logos) and anything that is not a GET are left to the browser", () => {
    // The fonts are ours since plan UX, A4 (/assets/*.woff2, cached like any static file); another origin stays
    // the browser's.
    expect(at("/assets/ibm-plex-sans-latin-400-normal.woff2")).toBe("static");
    expect(at("/widget.css", "cors", "GET", "https://cdn.example.org")).toBe("bypass");
    expect(at("/football/teams/33.png", "no-cors", "GET", "https://media.api-sports.io")).toBe(
      "bypass",
    );
    expect(at("/assets/index.js", "cors", "POST")).toBe("bypass");
  });

  test("anything else of ours is left to the network", () => {
    expect(at("/robots.txt")).toBe("bypass");
    expect(at("/unknown/thing.json")).toBe("bypass");
  });
});

describe("registration", () => {
  test("production registers the worker for the whole site", async () => {
    const calls: Array<[string, unknown]> = [];
    const host = {
      serviceWorker: {
        register: (url: string, options?: unknown) => {
          calls.push([url, options]);
          return Promise.resolve({});
        },
      },
    };
    expect(await registerServiceWorker(host, true)).toBe(true);
    expect(calls).toEqual([[SERVICE_WORKER_URL, { scope: "/" }]]);
  });

  test("development never registers it, and a browser without service workers is fine", async () => {
    let called = false;
    const host = {
      serviceWorker: {
        register: () => {
          called = true;
          return Promise.resolve({});
        },
      },
    };
    expect(await registerServiceWorker(host, false)).toBe(false);
    expect(called).toBe(false);
    expect(await registerServiceWorker({}, true)).toBe(false);
  });

  test("a failed registration is reported and nothing else changes", async () => {
    const host = { serviceWorker: { register: () => Promise.reject(new Error("blocked")) } };
    const warn = console.warn;
    console.warn = () => undefined;
    try {
      expect(await registerServiceWorker(host, true)).toBe(false);
    } finally {
      console.warn = warn;
    }
  });
});

describe("controlled updates", () => {
  type Listener = (event?: unknown) => void;
  function loadWorker() {
    const listeners: Record<string, Listener> = {};
    let skipped = 0;
    const self = {
      location: new URL(ORIGIN),
      addEventListener: (type: string, fn: Listener) => {
        listeners[type] = fn;
      },
      skipWaiting: () => {
        skipped += 1;
      },
      clients: { claim: () => Promise.resolve() },
    };
    const source = readFileSync(join(import.meta.dir, "..", "..", "public", "sw.js"), "utf8");
    const caches = { open: () => Promise.resolve({ addAll: () => Promise.resolve() }) };
    new Function("self", "caches", "fetch", source)(self, caches, () => undefined);
    return { listeners, skipped: () => skipped };
  }

  test("a new worker installs and WAITS; it takes over only when the page asks", async () => {
    const w = loadWorker();
    let pending: Promise<unknown> = Promise.resolve();
    w.listeners["install"]?.({ waitUntil: (p: Promise<unknown>) => (pending = p) });
    await pending;
    expect(w.skipped()).toBe(0);
    w.listeners["message"]?.({ data: { type: "something-else" } });
    expect(w.skipped()).toBe(0);
    w.listeners["message"]?.({ data: { type: "SKIP_WAITING" } });
    expect(w.skipped()).toBe(1);
  });

  test("the page is told about a waiting version only when an older one controls it", () => {
    const ready: unknown[] = [];
    const waiting = { postMessage: () => undefined };
    watchForUpdates(
      { waiting },
      { serviceWorker: { register: () => Promise.resolve(), controller: {} } },
      (w) => ready.push(w),
    );
    expect(ready).toEqual([waiting]);
    watchForUpdates({ waiting }, { serviceWorker: { register: () => Promise.resolve() } }, (w) =>
      ready.push(w),
    );
    expect(ready).toHaveLength(1);
    // found later: announced when the new worker reaches "installed"
    let found: (() => void) | undefined;
    let changed: (() => void) | undefined;
    const installing = {
      state: "installing",
      postMessage: () => undefined,
      addEventListener: (_: "statechange", fn: () => void) => {
        changed = fn;
      },
    };
    watchForUpdates(
      {
        installing,
        addEventListener: (_: "updatefound", fn: () => void) => {
          found = fn;
        },
      },
      { serviceWorker: { register: () => Promise.resolve(), controller: {} } },
      (w) => ready.push(w),
    );
    found?.();
    changed?.();
    expect(ready).toHaveLength(1);
    installing.state = "installed";
    changed?.();
    expect(ready).toEqual([waiting, installing]);
  });
});

describe("the manifest", () => {
  const manifest = JSON.parse(
    readFileSync(join(import.meta.dir, "..", "..", "public", "manifest.webmanifest"), "utf8"),
  ) as {
    name: string;
    start_url: string;
    scope: string;
    display: string;
    icons: Array<{ src: string; sizes: string; purpose: string }>;
  };

  test("installable: name, start, scope, standalone, and 192/512 icons of both purposes", () => {
    expect(manifest.name).toBe("PrediGol");
    expect(manifest.start_url).toBe("/home");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
    for (const purpose of ["any", "maskable"]) {
      const sizes = manifest.icons.filter((i) => i.purpose === purpose).map((i) => i.sizes);
      expect(sizes).toEqual(["192x192", "512x512"]);
    }
  });

  test("every icon it names is in public/", () => {
    for (const icon of manifest.icons) {
      expect(() =>
        readFileSync(join(import.meta.dir, "..", "..", "public", icon.src)),
      ).not.toThrow();
    }
  });
});

describe("a new version never leaves anyone on a broken one (plan UX, A15)", () => {
  type Listener = (event?: unknown) => void;
  /** public/sw.js with a cache store that remembers what was deleted. */
  function loadWorker(keys: string[]) {
    const listeners: Record<string, Listener> = {};
    const deleted: string[] = [];
    let claimed = 0;
    const self = {
      location: new URL(ORIGIN),
      addEventListener: (type: string, fn: Listener) => {
        listeners[type] = fn;
      },
      skipWaiting: () => undefined,
      clients: {
        claim: () => {
          claimed += 1;
          return Promise.resolve();
        },
      },
    };
    const caches = {
      keys: () => Promise.resolve([...keys]),
      delete: (key: string) => {
        deleted.push(key);
        return Promise.resolve(true);
      },
      open: () => Promise.resolve({ addAll: () => Promise.resolve() }),
    };
    const source = readFileSync(join(import.meta.dir, "..", "..", "public", "sw.js"), "utf8");
    const version = /const VERSION = "([^"]+)"/.exec(source)?.[1] ?? "";
    new Function("self", "caches", "fetch", source)(self, caches, () => undefined);
    return { listeners, deleted, claimed: () => claimed, version };
  }

  test("taking over, it retires every cache of an older version (and anything not its own) and claims the tabs", async () => {
    const w = loadWorker(["predigol-v1-static", "predigol-v2-static", "something-else"]);
    const current = `${w.version}-static`;
    const all = loadWorker(["predigol-v1-static", current, "predigol-v2-static", "something-else"]);
    let pending: Promise<unknown> = Promise.resolve();
    all.listeners["activate"]?.({ waitUntil: (p: Promise<unknown>) => (pending = p) });
    await pending;
    expect(all.deleted.sort()).toEqual([
      "predigol-v1-static",
      "predigol-v2-static",
      "something-else",
    ]);
    expect(all.deleted).not.toContain(current);
    expect(all.claimed()).toBe(1);
    expect(w.version).toMatch(/^predigol-v\d+$/);
  });

  test("the offline page is cached at install, so a new version can show it without the network", () => {
    const source = readFileSync(join(import.meta.dir, "..", "..", "public", "sw.js"), "utf8");
    expect(source).toMatch(/const PRECACHE = \[OFFLINE_URL/);
  });
});

describe("installing PrediGol (plan UX, A15)", () => {
  test("the installed app is told apart from a browser tab - Safari's own flag or the display mode", () => {
    expect(isStandalone({ navigator: { standalone: true } })).toBe(true);
    expect(
      isStandalone({
        matchMedia: (q: string) => ({ matches: q === "(display-mode: standalone)" }),
      }),
    ).toBe(true);
    expect(isStandalone({ matchMedia: () => ({ matches: false }), navigator: {} })).toBe(false);
    expect(isStandalone({})).toBe(false);
    expect(isStandalone(undefined)).toBe(false);
  });

  test("the steps of this device come first: an iPhone or iPad (also one asking for the desktop site), an Android, the rest", () => {
    const iphone =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
    const ipadDesktop =
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
    const android =
      "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36";
    expect(installPlatform({ userAgent: iphone })).toBe("ios");
    expect(installPlatform({ userAgent: ipadDesktop, maxTouchPoints: 5 })).toBe("ios");
    expect(installPlatform({ userAgent: ipadDesktop, maxTouchPoints: 0 })).toBe("other");
    expect(installPlatform({ userAgent: android })).toBe("android");
    expect(installPlatform({ userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" })).toBe(
      "other",
    );
    expect(installPlatform(undefined)).toBe("other");
    expect(installOrder("android")).toEqual(["android", "ios", "other"]);
    expect(installOrder("ios")).toEqual(["ios", "android", "other"]);
    expect(installOrder("other")).toEqual(["other", "ios", "android"]);
  });

  test("pwa_installed is owed once per device: the first opening of the installed app, never again", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    };
    expect(markInstalledOnce(storage)).toBe(true);
    expect(markInstalledOnce(storage)).toBe(false);
    expect([...store.keys()]).toEqual(["predigol.pwa_installed"]);
    expect(store.get("predigol.pwa_installed")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  test("without storage it never says yes, so a reader who refuses storage is not counted at every opening", () => {
    const refusing = {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("SecurityError");
      },
    };
    expect(markInstalledOnce(refusing)).toBe(false);
    const forgetting = { getItem: () => null, setItem: () => undefined };
    expect(markInstalledOnce(forgetting)).toBe(false);
  });
});

describe("a page open across a deploy (plan UX, A15)", () => {
  test("a script chunk the server no longer has reloads the page once - not in a loop", () => {
    const listeners: Array<(e: { preventDefault: () => void }) => void> = [];
    const store = new Map<string, string>();
    let reloads = 0;
    let prevented = 0;
    const scope = globalThis as { window?: unknown };
    const before = scope.window;
    scope.window = {
      addEventListener: (_: string, fn: (e: { preventDefault: () => void }) => void) =>
        listeners.push(fn),
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
      location: {
        reload: () => {
          reloads += 1;
        },
      },
    };
    try {
      reloadOnStaleChunks();
      const event = { preventDefault: () => void (prevented += 1) };
      listeners.forEach((fn) => fn(event));
      expect([reloads, prevented]).toEqual([1, 1]);
      // the reloaded page meets the same missing chunk at once: no second reload within 30 s
      listeners.forEach((fn) => fn(event));
      expect([reloads, prevented]).toEqual([1, 1]);
    } finally {
      scope.window = before;
    }
  });
});
