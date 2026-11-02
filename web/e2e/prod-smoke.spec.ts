/**
 * Read-only checks of a deployed site (plan UX, A2, project "prod-smoke"): what a reader's browser meets before
 * signing in. No account, no sign-in, nothing written - safe against production:
 *
 *   E2E_PROD_SMOKE=1 E2E_BASE_URL=https://predigolai.com bunx playwright test --project=prod-smoke
 *
 * Over https it also checks the headers the front door must send.
 */
import { expect, test } from "@playwright/test";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const HTTPS = BASE.startsWith("https://");

test("the sign-in page opens in the reader's language", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator("html")).toHaveAttribute("lang", "es");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});

test("the server writes <html lang> from the browser's language", async ({ request }) => {
  for (const lang of ["es", "en"]) {
    const res = await request.get(`${BASE}/login`, {
      headers: { "accept-language": `${lang};q=1.0` },
    });
    expect(res.status()).toBe(200);
    expect(/<html[^>]*\blang="([a-z-]+)"/i.exec(await res.text())?.[1]).toBe(lang);
  }
});

test("health answers, and the product is closed without a session", async ({ request }) => {
  const health = await request.get(`${BASE}/api/v1/health`);
  expect(health.status()).toBe(200);
  expect(["ok", "degraded", "warning"]).toContain(
    ((await health.json()) as { status: string }).status,
  );
  expect((await request.get(`${BASE}/api/v1/auth/me`)).status()).toBe(401);
  expect((await request.get(`${BASE}/api/v1/home`)).status()).toBe(401);
});

test("the browser learns where to report errors - never Sentry itself", async ({ request }) => {
  const res = await request.get(`${BASE}/api/v1/monitoring/client`);
  expect(res.status()).toBe(200);
  const body = (await res.json()) as { enabled: boolean; tunnel: string };
  expect(body.tunnel).toBe("/api/v1/monitoring/envelope");
  expect(typeof body.enabled).toBe("boolean");
});

test("a document navigation to the server-function path never comes back as markup", async ({
  request,
}) => {
  const mark = `predigol-smoke-${Date.now()}`;
  const res = await request.get(
    `${BASE}/_serverFn/predigol-probe?payload=%3Cb%3E${mark}%3C%2Fb%3E`,
    {
      headers: { "sec-fetch-mode": "navigate", "sec-fetch-dest": "document", accept: "text/html" },
    },
  );
  const html = (res.headers()["content-type"] ?? "").includes("text/html");
  expect(html && (await res.text()).includes(`<b>${mark}</b>`)).toBe(false);
});

test("over https, the front door sends its security headers", async ({ request }) => {
  test.skip(!HTTPS, "the local stack has no front door");
  const res = await request.get(`${BASE}/login`);
  const headers = res.headers();
  expect(headers["strict-transport-security"]).toContain("max-age=");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["content-security-policy"] ?? "").toContain("default-src");
});
