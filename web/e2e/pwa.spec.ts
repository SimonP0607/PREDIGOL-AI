/**
 * The installable app, as a phone sees it: the manifest and its icons, a service worker that controls the
 * site, never answers for the API, and shows its own offline page - never a stale copy of a page - when
 * there is no connection.
 *
 * Plan UX, A15 (section 35, gate G11): Chrome finds nothing that stops the install; opening PrediGol never asks for a
 * permission; and a new version of the worker installs and WAITS, the page says so, the reader decides, and taking
 * over retires the old version's caches - nobody is left on a broken mix of two versions. The install itself, the
 * safe areas and the offline page on a real iPhone and a real Android are the manual check of section 35.
 *
 * Production builds only (the dev server never registers the worker): run with E2E_PWA=1 against the
 * deployed stack, e.g. E2E_PWA=1 E2E_BASE_URL=https://predigol.localhost bun run test:e2e --project=pwa
 */
import { existsSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { statePath } from "./accounts";

test.skip(!process.env["E2E_PWA"], "needs a production build (E2E_PWA=1)");

interface Manifest {
  name: string;
  start_url: string;
  scope: string;
  display: string;
  icons: Array<{ src: string; sizes: string; purpose: string; type: string }>;
}

test("the manifest is served, and every icon it names", async ({ request }) => {
  const res = await request.get("/manifest.webmanifest");
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"] ?? "").toMatch(/manifest\+json|application\/json/);
  const manifest = (await res.json()) as Manifest;
  expect(manifest.name).toBe("PrediGol");
  expect(manifest.display).toBe("standalone");
  expect(manifest.scope).toBe("/");
  for (const icon of manifest.icons) {
    const img = await request.get(icon.src);
    expect(img.status(), icon.src).toBe(200);
    expect(img.headers()["content-type"], icon.src).toBe("image/png");
  }
});

test("the page links the manifest and the worker controls the site", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator('link[rel="manifest"]')).toHaveAttribute(
    "href",
    "/manifest.webmanifest",
  );
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  expect(new URL(scope).pathname).toBe("/");
  await page.reload();
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
});

test("the worker never answers for the API, and serves the app's own files from its cache", async ({
  page,
}) => {
  await page.goto("/login");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  const fromWorker: Record<string, boolean> = {};
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path.startsWith("/api/") || path.startsWith("/assets/")) {
      fromWorker[path] = response.fromServiceWorker();
    }
  });
  await page.reload();
  await page.evaluate(async () => {
    await fetch("/api/v1/health", { credentials: "same-origin" });
  });
  await page.waitForTimeout(500);
  const api = Object.entries(fromWorker).filter(([path]) => path.startsWith("/api/"));
  const assets = Object.entries(fromWorker).filter(([path]) => path.startsWith("/assets/"));
  expect(api.length, "the page called the API").toBeGreaterThan(0);
  expect(
    api.filter(([, viaWorker]) => viaWorker),
    "no API answer comes from the worker",
  ).toEqual([]);
  expect(assets.length).toBeGreaterThan(0);
  expect(
    assets.every(([, viaWorker]) => viaWorker),
    "hashed static files come from the cache",
  ).toBe(true);
});

test("offline, a page shows the offline page - never a stale copy - and online again the site is back", async ({
  page,
  context,
}) => {
  await page.goto("/login");
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  // Chromium's offline emulation does not reach the service worker's own requests, so the network is cut for
  // them explicitly: every page request fails as it would with no connection (the worker's network events are
  // routed when PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS=1, as the pwa project sets).
  await context.route(
    (url) => !url.pathname.startsWith("/assets/") && !url.pathname.startsWith("/brand/"),
    (route) => route.abort("internetdisconnected"),
  );
  await context.setOffline(true);
  await page.goto("/home");
  await expect(page.getByTestId("offline-page")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Sin conexión");
  await context.unrouteAll();
  await context.setOffline(false);
  await page.goto("/login");
  await expect(page.getByTestId("offline-page")).toHaveCount(0);
});

/** The page under a worker that controls it (the first load installs it; the reload is the first controlled one). */
async function controlled(page: Page, path = "/login"): Promise<void> {
  await page.goto(path);
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  await expect
    .poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null))
    .toBe(true);
}

test("installable as Chrome sees it: no installability error", async ({ page }) => {
  await controlled(page);
  const cdp = await page.context().newCDPSession(page);
  const { installabilityErrors } = (await cdp.send("Page.getInstallabilityErrors")) as {
    installabilityErrors: Array<{ errorId: string }>;
  };
  expect(installabilityErrors.map((e) => e.errorId)).toEqual([]);
});

/** Counts every request for a permission the page makes (notifications, push, location) - none is expected. */
async function spyPermissions(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const asked: string[] = [];
    (window as unknown as { __asked: string[] }).__asked = asked;
    if ("Notification" in window) {
      window.Notification.requestPermission = (() => {
        asked.push("notifications");
        return Promise.resolve("default");
      }) as typeof Notification.requestPermission;
    }
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition = () => void asked.push("location");
      navigator.geolocation.watchPosition = () => {
        asked.push("location");
        return 0;
      };
    }
    const subscribe = window.PushManager?.prototype.subscribe;
    if (subscribe) {
      window.PushManager.prototype.subscribe = function (...args) {
        asked.push("push");
        return subscribe.apply(this, args);
      };
    }
  });
}

test("opening PrediGol never asks for a permission (notifications arrive with B7, in context)", async ({
  page,
}) => {
  await spyPermissions(page);
  await controlled(page);
  await page.waitForTimeout(1_500);
  expect(await page.evaluate(() => (window as unknown as { __asked: string[] }).__asked)).toEqual(
    [],
  );
});

test.describe("signed in", () => {
  test.skip(!existsSync(statePath("phone")), "no signed-in state (the setup project writes it)");
  test.use({ storageState: statePath("phone") });

  test("the product's pages never ask for a permission either", async ({ page }) => {
    await spyPermissions(page);
    for (const path of ["/home", "/matches", "/picks", "/my-picks", "/profile"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle").catch(() => undefined);
    }
    expect(await page.evaluate(() => (window as unknown as { __asked: string[] }).__asked)).toEqual(
      [],
    );
  });
});

test("a new version waits for the reader, takes over when accepted, and retires the old version's caches", async ({
  page,
}) => {
  // A new version comes from the server, as after a deploy: the browser fetches the worker's script for an update by
  // itself, beyond a test's request routing. The QA front door can answer /sw.js as a new version (GET /__qa/sw?next=1);
  // a deployed site cannot, and there this flow is the manual check of section 35.
  const hook = await page.request.get("/__qa/sw?next=0");
  test.skip(
    hook.status() !== 200,
    "no QA front door that can serve a new worker (a deployed site)",
  );
  await controlled(page);
  const original = await (await page.request.get("/sw.js")).text();
  const version = /const VERSION = "([^"]+)";/.exec(original)?.[1];
  expect(version, "the worker names its version").toBeTruthy();
  expect(await page.evaluate(() => caches.keys())).toEqual([`${version}-static`]);
  try {
    expect((await page.request.get("/__qa/sw?next=1")).status()).toBe(200);
    // The page looks for it (every 30 minutes and on coming back to it; here at once): it installs and WAITS.
    await page.evaluate(async () => {
      await (await navigator.serviceWorker.getRegistration())?.update();
    });
    const notice = page.getByTestId("update-toast");
    await expect(notice).toBeVisible();
    expect(
      await page.evaluate(async () => {
        const r = await navigator.serviceWorker.getRegistration();
        return { waiting: r?.waiting?.state ?? null, active: r?.active?.state ?? null };
      }),
      "the new one waits; the old one still serves this page",
    ).toEqual({ waiting: "installed", active: "activated" });
    // «Más tarde»: nothing changes under the reader - not the code, not the caches.
    await page.getByTestId("update-later").click();
    await expect(notice).toHaveCount(0);
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => caches.keys())).toContain(`${version}-static`);
    expect(
      await page.evaluate(
        async () => (await navigator.serviceWorker.getRegistration())?.waiting?.state ?? null,
      ),
    ).toBe("installed");
    // On the next visit the waiting version is offered again; «Actualizar ahora» switches once: one reload, on it.
    await page.reload();
    await expect(notice).toBeVisible();
    const reloaded = page.waitForEvent("load");
    await page.getByTestId("update-now").click();
    await reloaded;
    await expect
      .poll(() => page.evaluate(() => caches.keys()), { timeout: 15_000 })
      .toEqual([`${version}-next-static`]);
    expect(
      await page.evaluate(async () => {
        const r = await navigator.serviceWorker.getRegistration();
        return { waiting: r?.waiting ?? null, active: r?.active?.state ?? null };
      }),
    ).toEqual({ waiting: null, active: "activated" });
    expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
    // the new version cached its own offline page at its install: without a connection it still shows it
    expect(
      await page.evaluate(async () => {
        const cache = await caches.open((await caches.keys())[0] ?? "");
        return (await cache.match("/offline.html")) !== undefined;
      }),
    ).toBe(true);
  } finally {
    await page.request.get("/__qa/sw?next=0");
  }
});
