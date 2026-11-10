/**
 * The app installed on an iPhone (mobile UX plan, UX-093): the page runs under the status bar, so nothing a finger
 * needs may sit under the clock, the Dynamic Island or the notch - in portrait and held sideways, at the ten widths of
 * the plan. The insets are simulated (./safearea.ts): no engine Playwright drives reports them.
 *
 * Before UX-093 the sign-in page's language switch sat 19 px from the top, under the status bar (59 px), at every
 * width; and the owner's «Viendo como usuario» notice, drawn above the top bar, put its button under the clock.
 *
 * The pages before the product need no account: E2E_SAFEAREA_PUBLIC=1 runs only them, against any site (production
 * included: nothing is written).
 */
import { expect, test, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import {
  controlsUnderSystemBars,
  IPAD,
  IPHONE_LANDSCAPE,
  IPHONE_PORTRAIT,
  simulateInsets,
  type Insets,
} from "./safearea";

const WIDTHS = [320, 360, 375, 390, 430, 600, 640, 768, 820, 1024];
const PUBLIC_ONLY = !!process.env["E2E_SAFEAREA_PUBLIC"];

/** The pages before the product: the sign-in, the account pages (AccountShell) and the legal texts (PublicShell). */
const BEFORE = [
  "/login",
  "/register",
  "/forgot-password",
  "/reset-password?token=e2e",
  "/legal/terms",
];

/** A phone below 600 px has the iPhone's status bar; from 600 px it is a tablet's (an iPad). */
function portrait(width: number): Insets {
  return width < 600 ? IPHONE_PORTRAIT : IPAD;
}

async function load(page: Page, path: string, insets: Insets): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 20_000 });
  await simulateInsets(page, insets);
}

test.describe("before the product, no account", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  for (const width of WIDTHS) {
    test(`no control under the status bar at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width < 600 ? 844 : 1180 });
      const insets = portrait(width);
      for (const path of BEFORE) {
        await load(page, path, insets);
        // the language switch is there, and below the status bar
        await expect(page.getByTestId("lang-es").first()).toBeVisible();
        expect(await controlsUnderSystemBars(page, insets), `${path} at ${width} px`).toEqual([]);
      }
    });
  }

  test("held sideways: nothing under the notch or the rounded corners", async ({ page }) => {
    await page.setViewportSize({ width: 844, height: 390 });
    for (const path of BEFORE) {
      await load(page, path, IPHONE_LANDSCAPE);
      expect(await controlsUnderSystemBars(page, IPHONE_LANDSCAPE), path).toEqual([]);
    }
  });

  test("a browser keeps the page as it was: the switch 16 px from the top and the right", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/login");
    await expect(page.getByTestId("lang-es")).toBeVisible();
    const bar = await page.getByTestId("account-top-bar").boundingBox();
    const group = await page.getByRole("group").first().boundingBox();
    expect(bar?.y).toBe(0);
    expect(group?.y).toBe(16);
    expect(Math.round((group?.x ?? 0) + (group?.width ?? 0))).toBe(390 - 16);
  });
});

test.describe("the product, a reader", () => {
  test.skip(PUBLIC_ONLY, "E2E_SAFEAREA_PUBLIC: the pages before the product only");
  test.use({ storageState: statePath("phone") });

  for (const width of [320, 390, 430, 768, 1024]) {
    test(`the top bar stays below the status bar at ${width} px, on load and after a scroll`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: width < 600 ? 844 : 1180 });
      const insets = portrait(width);
      for (const path of ["/home", "/matches", "/picks", "/odds", "/my-picks", "/profile"]) {
        await load(page, path, insets);
        expect(await controlsUnderSystemBars(page, insets), `${path} on load`).toEqual([]);
        await page.mouse.wheel(0, 900);
        await page.waitForTimeout(250);
        expect(await controlsUnderSystemBars(page, insets, "header"), `${path} scrolled`).toEqual(
          [],
        );
        const top = await page.locator("header").first().boundingBox();
        expect(Math.round(top?.y ?? -1), `${path}: the bar sticks below the status bar`).toBe(
          insets.top,
        );
      }
    });
  }
});

test.describe("the owner previewing the product", () => {
  test.skip(PUBLIC_ONLY, "E2E_SAFEAREA_PUBLIC: the pages before the product only");
  test.use({ storageState: statePath("admin") });

  test("«Viendo como usuario» and its button stay below the status bar", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/admin/overview");
    await page.getByTestId("preview-as-user").click();
    await expect(page).toHaveURL(/\/home$/);
    await load(page, "/home", IPHONE_PORTRAIT);
    await expect(page.getByTestId("preview-banner")).toBeVisible();
    expect(await controlsUnderSystemBars(page, IPHONE_PORTRAIT)).toEqual([]);
    const banner = await page.getByTestId("preview-banner").boundingBox();
    expect(Math.round(banner?.y ?? -1)).toBe(IPHONE_PORTRAIT.top);
    // and back: the owner leaves the preview as the test found it
    await page.getByTestId("exit-preview").click();
    await expect(page).toHaveURL(/\/admin\/overview$/);
  });
});
