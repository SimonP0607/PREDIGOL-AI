/**
 * The owner's banners (closing plan 4.3), in the browser with the API's answer replaced by a fixed one - nothing is
 * published, so the suite leaves no communiqué behind (a published one is retracted, never deleted). The sign-in page
 * is where a maintenance notice has to reach someone who cannot get in:
 *
 * * an incident and a general notice show, the incident first, in the reader's language;
 * * a reader closes one and it stays closed after a reload; the other stays;
 * * nothing to say, nothing shown; a failing notice route shows nothing and the page works;
 * * on a 320 px phone nothing goes sideways.
 */
import { expect, test } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } });

const HOUR = 3600 * 1000;
const iso = (offset: number) => new Date(Date.now() + offset).toISOString();
const notice = (id: number, kind: string, title: string) => ({
  id,
  kind,
  title_es: title,
  title_en: `${title} (en)`,
  body_es: `Cuerpo de ${title}`,
  body_en: `Body of ${title}`,
  starts_at: iso(-HOUR),
  ends_at: iso(HOUR),
  critical: kind === "incident",
});

test.describe("the owner's banners", () => {
  test("they show, the most urgent first, and a closed one stays closed", async ({ page }) => {
    await page.route("**/api/v1/announcements/active", (route) =>
      route.fulfill({
        json: {
          banners: [notice(1, "general", "Aviso general"), notice(2, "incident", "Incidencia")],
          updates: [],
        },
      }),
    );
    await page.goto("/login");
    const banners = page.getByTestId("announcement");
    await expect(banners).toHaveCount(2);
    await expect(banners.first()).toHaveAttribute("data-kind", "incident");
    await banners.first().getByTestId("announcement-close").click();
    await expect(banners).toHaveCount(1);
    await page.reload();
    await expect(page.getByTestId("announcement")).toHaveCount(1);
    await expect(page.getByTestId("announcement")).toHaveAttribute("data-kind", "general");
  });

  test("nothing to say shows nothing; a failing route changes nothing", async ({ page }) => {
    await page.route("**/api/v1/announcements/active", (route) =>
      route.fulfill({ json: { banners: [], updates: [] } }),
    );
    await page.goto("/login");
    await expect(page.getByTestId("announcements")).toHaveCount(0);
    await page.unroute("**/api/v1/announcements/active");
    await page.route("**/api/v1/announcements/active", (route) => route.fulfill({ status: 500 }));
    await page.reload();
    await expect(page.getByTestId("announcements")).toHaveCount(0);
    await expect(page.locator('input[type="password"]')).toBeVisible();
  });

  test("on a 320 px phone nothing goes sideways", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await page.route("**/api/v1/announcements/active", (route) =>
      route.fulfill({
        json: { banners: [notice(3, "maintenance", "Mantenimiento")], updates: [] },
      }),
    );
    await page.goto("/login");
    await expect(page.getByTestId("announcement")).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
