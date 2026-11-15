/**
 * Preferences belong to the account: the language and the time zone survive a reload,
 * and every time on screen follows the zone (the stored data stays UTC). Runs serially
 * on its own QA account, which it puts back as it found it.
 */
import { expect, test } from "@playwright/test";
import { L, getJson, sendJson, settle, watch, assertClean } from "./support";

test.describe.configure({ mode: "serial" });

test("changing the language switches every label and is remembered", async ({ page }) => {
  const w = watch(page);
  await page.goto("/home");
  await settle(page);
  const nav = page.getByRole("navigation", { name: L.es.nav.mainNavigation }).first();
  await expect(nav.getByRole("link", { name: L.es.nav.home, exact: true })).toBeVisible();
  // the language is in «Más» since it left the top bar (plan maestro UX/UI 2026, wave 3)
  await page.getByTestId("nav-more").click();
  await page.getByTestId("lang-en").click();
  const navEn = page.getByRole("navigation", { name: L.en.nav.mainNavigation }).first();
  await expect(navEn.getByRole("link", { name: L.en.nav.home, exact: true })).toBeVisible();
  await page.reload();
  await settle(page);
  await expect(navEn.getByRole("link", { name: L.en.nav.matches, exact: true })).toBeVisible();
  await page.getByTestId("nav-more").click();
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
    await page.goto("/profile/region");
    await settle(page);
    await page.getByTestId("timezone-search").fill(zone.split("/")[1] ?? zone);
    await page.getByTestId(`tz-${zone}`).click();
    await expect(page.getByTestId("current-timezone")).toContainText(zone);
    // Plan UX, A1 (F09): the zone in words, in the reader's language - never the raw id alone
    await expect(page.getByTestId("current-timezone-name")).toHaveText(
      zone === "Europe/Madrid"
        ? /Europa central \(GMT\+[12]\)$/
        : "hora estándar de Colombia (GMT-5)",
    );
    await page.goto(`/matches/${fixture.id}`);
    await settle(page);
    await expect(page.getByTestId("match-center")).toContainText(
      wallClock(fixture.kickoff_at, zone),
    );
    // the picks' day is Bogotá's: a reader on another clock is told so; one on Bogotá's is not
    await page.goto("/picks");
    await settle(page);
    if (zone === "Europe/Madrid") {
      await expect(page.getByTestId("daily-zone")).toHaveText(
        "Días de picks en hora estándar de Colombia (GMT-5)",
      );
    } else {
      await expect(page.getByTestId("daily-zone")).toHaveCount(0);
    }
  }
  await assertClean(page, w);
});

test("the settings of presentation (decision 8): the clock, the price format and the animations change what is written, and are kept", async ({
  page,
}) => {
  const w = watch(page);
  const reset = {
    time_format: "24h",
    odds_format: "decimal",
    reduce_motion: false,
    home_default: "auto",
  };
  try {
    await page.goto("/profile/region");
    await settle(page);
    const settings = page.getByTestId("display-settings");
    await expect(settings.getByTestId("display-odds-decimal")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(settings.getByTestId("display-time-24h")).toHaveAttribute("aria-checked", "true");
    await expect(page.locator("html")).not.toHaveAttribute("data-motion", "reduce");
    // the price format: the same price, written another way - and kept by the account
    await page.getByTestId("display-odds-american").click();
    await expect(page.getByTestId("display-odds-american")).toHaveAttribute("aria-checked", "true");
    await page.getByTestId("display-time-12h").click();
    await expect(page.getByTestId("display-time-12h")).toHaveAttribute("aria-checked", "true");
    await page.getByTestId("display-motion").click();
    await expect(page.locator("html")).toHaveAttribute("data-motion", "reduce");
    const me = await getJson<{ display: Record<string, unknown> }>(page.request, "/api/v1/auth/me");
    expect(me.body.display).toEqual({
      time_format: "12h",
      odds_format: "american",
      reduce_motion: true,
      home_default: null,
    });
    await page.goto("/odds");
    await settle(page);
    const prices = await page.locator("main").innerText();
    expect(prices, "prices are written the American way").toMatch(/[+−]\d{3}/);
    expect(prices, "no decimal price is left on the page").not.toMatch(/\b\d,\d{2}\b/);
    expect(prices, "hours are written with the 12-hour clock").toMatch(/\d{1,2}:\d{2}\s(am|pm)/);
    await page.reload();
    await settle(page);
    await expect(page.locator("html")).toHaveAttribute("data-motion", "reduce");
    await assertClean(page, w);
  } finally {
    await sendJson(page.request, "PATCH", "/api/v1/auth/me/preferences", reset);
  }
});
