/**
 * The installable app, as a phone sees it: the manifest and its icons, a service worker that controls the
 * site, never answers for the API, and shows its own offline page - never a stale copy of a page - when
 * there is no connection.
 *
 * Production builds only (the dev server never registers the worker): run with E2E_PWA=1 against the
 * deployed stack, e.g. E2E_PWA=1 E2E_BASE_URL=https://predigol.localhost bun run test:e2e --project=pwa
 */
import { expect, test } from "@playwright/test";

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
