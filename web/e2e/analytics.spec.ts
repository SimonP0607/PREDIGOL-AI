/**
 * Product analytics (plan UX, A6), in the browser: the events of a reader's journey leave in the background - at once
 * when the page hides - carry only the catalog's properties, and reach the owner's view. The QA API measures
 * (FBI_PRODUCT_EVENTS=on) and shows figures from one reader on (FBI_PRODUCT_MIN_SUBJECTS=1); production measures
 * nothing until the owner decides.
 */
import { expect, request, test } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";

interface Sent {
  events: Array<{ name: string; props: Record<string, unknown> }>;
}

test("a reader's journey leaves its events in the background, and the owner sees them", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const w = watch(page);
  const sent: Sent["events"] = [];
  const statuses: number[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/api/v1/events")) {
      sent.push(...((req.postDataJSON() as Sent | null)?.events ?? []));
    }
  });
  page.on("response", (res) => {
    if (res.request().method() === "POST" && res.url().endsWith("/api/v1/events"))
      statuses.push(res.status());
  });

  // 1. Home, then a match from it, then one of its sections
  await page.goto("/home");
  const match = page.locator('a[href^="/matches/"]').first();
  await expect(match).toBeVisible();
  const href = (await match.getAttribute("href")) ?? "";
  const matchId = Number(/\/matches\/(\d+)/.exec(href)?.[1]);
  await match.click();
  await expect(page.getByTestId("match-center")).toBeVisible();
  await page.locator("#match-tab-markets").click();
  await expect(page.locator("#match-panel-markets")).toBeVisible();
  await expect
    .poll(() => sent.map((e) => e.name), { timeout: 20_000 })
    .toEqual(expect.arrayContaining(["session_started", "match_opened", "match_section_opened"]));

  // 2. the page hides right after a section opens: its event leaves at once, not seconds later
  await page.locator("#match-tab-stats").click();
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect
    .poll(
      () =>
        sent.filter((e) => e.name === "match_section_opened" && e.props["section"] === "stats")
          .length,
      {
        timeout: 2_500,
      },
    )
    .toBe(1);

  // 3. what left: the catalog's properties, nothing else
  expect(sent.find((e) => e.name === "match_opened")?.props).toEqual({
    match_id: matchId,
    origin: "home",
  });
  expect(sent.find((e) => e.name === "match_section_opened")?.props).toEqual({
    section: "markets",
    match_id: matchId,
  });
  const started = sent.find((e) => e.name === "session_started")?.props ?? {};
  expect(Object.keys(started).sort()).toEqual(["client", "device", "lang", "width"]);
  expect(started["device"]).toBe("desktop");
  expect(JSON.stringify(sent)).not.toMatch(/@|password|email/i);
  await expect.poll(() => statuses.length).toBeGreaterThan(0);
  expect(statuses.every((s) => s === 200)).toBe(true);
  await assertClean(page, w);

  // 4. the owner's view counts them
  const owner = await request.newContext({ baseURL: BASE, storageState: statePath("admin") });
  const overview = await getJson<{
    status: string;
    mode: string;
    usage: Array<{ name: string; events_7d: number }>;
  }>(owner, "/api/v1/admin/product");
  expect(overview.body.mode, "the QA API must measure (FBI_PRODUCT_EVENTS=on)").toBe("on");
  expect(overview.body.status).toBe("ok");
  const used = new Map(overview.body.usage.map((u) => [u.name, u.events_7d]));
  for (const name of ["session_started", "match_opened", "match_section_opened"])
    expect(used.get(name) ?? 0, name).toBeGreaterThanOrEqual(1);
  await owner.dispose();
});

test("the console's Product page shows the figures to the owner and nothing to a reader", async ({
  browser,
}) => {
  const reader = await request.newContext({
    baseURL: BASE,
    storageState: statePath("user"),
    extraHTTPHeaders: { "x-requested-with": "predigol" },
  });
  const recorded = await sendJson<{ recorded: number }>(reader, "POST", "/api/v1/events", {
    events: [{ name: "match_opened", props: { origin: "matches", match_id: 1 } }],
  });
  expect(recorded.status).toBe(200);
  expect((await reader.get("/api/v1/admin/product")).status()).toBe(403);
  await reader.dispose();

  const ownerPage = await (
    await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
  ).newPage();
  const w = watch(ownerPage);
  await ownerPage.goto("/admin/product");
  await expect(ownerPage.getByTestId("product-state")).toContainText(L.en.admin.product.mode.on);
  await expect(ownerPage.getByTestId("product-usage")).toBeVisible();
  await expect(ownerPage.locator('[data-event="match_opened"]')).toBeVisible();
  await assertClean(ownerPage, w);
  await ownerPage.context().close();
});
