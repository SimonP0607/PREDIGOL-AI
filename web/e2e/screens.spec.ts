/**
 * Reference screenshots of the product on phones (phase A0 of the UX plan: "capturas de referencia
 * 320/360/390/412/430"). Runs only when asked (E2E_SCREENS=1, project "screens"): every product destination,
 * signed in as the Spanish QA user, at each width, the whole page. The pictures go to the test's output folder
 * (<width>/<page>.png); they are a record to compare later phases with by eye, not a pixel test - the data under
 * them changes every day. Nothing is checked here except that each page loads and settles.
 */
import { test } from "@playwright/test";
import { statePath } from "./accounts";
import { settle } from "./support";

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
const WIDTHS = [320, 360, 390, 412, 430];

test.use({ storageState: statePath("user") });

// A test per width: a fresh tab each time (see responsive.spec.ts on why one tab must not load forty pages).
for (const width of WIDTHS) {
  test(`reference screenshots at ${width} px`, async ({ page }, info) => {
    test.setTimeout(150_000);
    await page.setViewportSize({ width, height: width < 360 ? 568 : 844 });
    for (const path of PAGES) {
      await page.goto(path);
      await settle(page);
      await page.screenshot({
        path: info.outputPath(`${width}`, `${path.slice(1).replace(/\W+/g, "_")}.png`),
        fullPage: true,
      });
    }
  });
}
