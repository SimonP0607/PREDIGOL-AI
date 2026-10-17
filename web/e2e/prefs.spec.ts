/**
 * Preferences belong to the account: the language and the time zone survive a reload,
 * and every time on screen follows the zone (the stored data stays UTC). Runs serially
 * on its own QA account, which it puts back as it found it.
 */
import { expect, test } from "@playwright/test";
import { L, getJson, settle, watch, assertClean } from "./support";

test.describe.configure({ mode: "serial" });

test("changing the language switches every label and is remembered", async ({ page }) => {
  const w = watch(page);
  await page.goto("/home");
  await settle(page);
  const nav = page.getByRole("navigation", { name: L.es.nav.mainNavigation }).first();
  await expect(nav.getByRole("link", { name: L.es.nav.home, exact: true })).toBeVisible();
  await page.getByTestId("lang-en").click();
  const navEn = page.getByRole("navigation", { name: L.en.nav.mainNavigation }).first();
  await expect(navEn.getByRole("link", { name: L.en.nav.home, exact: true })).toBeVisible();
  await page.reload();
  await settle(page);
  await expect(navEn.getByRole("link", { name: L.en.nav.matches, exact: true })).toBeVisible();
  await page.getByTestId("lang-es").click();
  await expect(nav.getByRole("link", { name: L.es.nav.matches, exact: true })).toBeVisible();
  await assertClean(page, w);
});

function wallClock(iso: string, zone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso));
}

test("changing the time zone moves every kick-off, DST included", async ({ page }) => {
  const w = watch(page);
  const { body } = await getJson<{ data: Array<{ id: number; kickoff_at: string }> }>(
    page.request,
    "/api/v1/matches?status=scheduled&order=asc&limit=1&kickoff_after=" +
      encodeURIComponent(new Date().toISOString()),
  );
  const fixture = body.data[0];
  test.skip(!fixture, "no scheduled fixture to check");
  if (!fixture) return;
  for (const zone of ["Europe/Madrid", "America/Bogota"]) {
    await page.goto("/profile");
    await settle(page);
    await page.getByTestId("timezone-search").fill(zone.split("/")[1] ?? zone);
    await page.getByTestId(`tz-${zone}`).click();
    await expect(page.getByTestId("current-timezone")).toContainText(zone);
    await page.goto(`/matches/${fixture.id}`);
    await settle(page);
    await expect(page.getByTestId("match-center")).toContainText(
      wallClock(fixture.kickoff_at, zone),
    );
  }
  await assertClean(page, w);
});
