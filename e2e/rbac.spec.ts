/**
 * Authorization is the server's: no session is 401, a USER on any admin route is 403
 * (even knowing the URL), a SUPER_ADMIN gets through. The browser only follows.
 */
import { expect, request, test } from "@playwright/test";
import { statePath } from "./accounts";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const H = { "x-requested-with": "predigol" };
const ADMIN_ROUTES = [
  "/api/v1/admin/overview",
  "/api/v1/admin/system",
  "/api/v1/admin/users",
  "/api/v1/admin/audit",
  "/api/v1/admin/models",
  "/api/v1/admin/performance",
  "/api/v1/admin/picks",
  "/api/v1/admin/data-quality/issues",
  "/api/v1/admin/analytics/migration",
  "/api/v1/admin/ops/jobs",
  "/api/v1/admin/provider",
];

test("without a session the product is closed and health stays open", async () => {
  const anon = await request.newContext({ baseURL: BASE, extraHTTPHeaders: H });
  expect((await anon.get("/health")).status()).toBeLessThan(600);
  for (const path of ["/api/v1/home", "/api/v1/matches", "/api/v1/auth/me", ...ADMIN_ROUTES]) {
    expect((await anon.get(path)).status(), path).toBe(401);
  }
  await anon.dispose();
});

test("a USER gets the product and 403 on every admin route, and no shadow preview", async () => {
  const user = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: H,
    storageState: statePath("user"),
  });
  for (const path of [
    "/api/v1/home",
    "/api/v1/picks",
    "/api/v1/parlays/daily",
    "/api/v1/odds/best",
    "/api/v1/live",
  ]) {
    expect((await user.get(path)).status(), path).toBe(200);
  }
  for (const path of ADMIN_ROUTES) {
    const res = await user.get(path);
    expect(res.status(), path).toBe(403);
    expect(((await res.json()) as { error: { code: string } }).error.code).toBe("forbidden");
  }
  expect((await user.get("/api/v1/home?preview=shadow")).status()).toBe(403);
  expect(
    (await user.patch("/api/v1/admin/users/1", { data: { role: "SUPER_ADMIN" } })).status(),
  ).toBe(403);
  await user.dispose();
});

test("a SUPER_ADMIN reaches the admin API", async () => {
  const admin = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: H,
    storageState: statePath("admin"),
  });
  for (const path of ADMIN_ROUTES) expect((await admin.get(path)).status(), path).toBe(200);
  expect((await admin.get("/api/v1/home?preview=shadow")).status()).toBe(200);
  await admin.dispose();
});

test("a state-changing request without the same-site header is refused", async () => {
  const bare = await request.newContext({ baseURL: BASE, storageState: statePath("user") });
  const res = await bare.patch("/api/v1/auth/me/preferences", { data: { language: "en" } });
  expect(res.status()).toBe(403);
  expect(((await res.json()) as { error: { code: string } }).error.code).toBe("csrf");
  await bare.dispose();
});

test.describe("a USER opening an admin page", () => {
  test.use({ storageState: statePath("user") });
  test("sees no-access, not the console", async ({ page }) => {
    await page.goto("/admin/overview");
    await expect(page.getByTestId("forbidden")).toBeVisible();
    await expect(page.getByTestId("admin-nav-overview")).toHaveCount(0);
    await page.getByTestId("account-menu").click();
    await expect(page.getByTestId("go-admin")).toHaveCount(0);
    await expect(page.getByTestId("toggle-preview")).toHaveCount(0);
  });
});
