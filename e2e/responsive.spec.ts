/**
 * The product at phone width (390 px): every destination fits, nothing scrolls
 * sideways, and the bottom tab bar is there. Then Home at the other review widths.
 */
import { expect, test } from "@playwright/test";
import { assertClean, settle, watch } from "./support";

const PAGES = [
  "/home",
  "/matches",
  "/live",
  "/picks",
  "/parlays",
  "/odds",
  "/my-picks",
  "/profile",
];

test("every product page fits a 390 px phone", async ({ page }) => {
  test.setTimeout(120_000);
  const w = watch(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of PAGES) {
    await page.goto(path);
    await settle(page);
    await expect(page.getByTestId("tab-home"), "the bottom tab bar").toBeVisible();
    await assertClean(page, w);
  }
});

for (const width of [768, 1024, 1280, 1440]) {
  test(`Home at ${width} px`, async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/home");
    await settle(page);
    await assertClean(page, w);
  });
}
