/**
 * Every route at every width the product supports: nothing leaks, nothing
 * scrolls sideways, nothing is left loading, nothing errors.
 */
import { test } from "@playwright/test";
import { api, assertClean, settle, watch } from "./support";

const WIDTHS = [1440, 1280, 1024, 768, 390] as const;

const ROUTES = [
  "/",
  "/matches",
  "/live",
  "/odds",
  "/models",
  "/picks",
  "/performance",
  "/analytics",
  "/backtesting",
  "/competitions",
  "/teams",
  "/players",
  "/rankings",
  "/data-quality",
  "/admin",
  "/ai-analyst",
  "/settings",
] as const;

test.describe.configure({ mode: "parallel" });

for (const width of WIDTHS) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: width < 768 ? 844 : 900 } });

    for (const route of ROUTES) {
      test(route, async ({ page }) => {
        const w = watch(page);
        await page.goto(route);
        await settle(page);
        await assertClean(page, w);
      });
    }

    test("/players/:id", async ({ page }) => {
      const list = await api<Array<{ id: number }>>("/api/v1/players?limit=1");
      const first = list.data[0];
      test.skip(first === undefined, "no player statistics in the last 30 days");
      const w = watch(page);
      await page.goto(`/players/${first!.id}`);
      await settle(page);
      await assertClean(page, w);
    });

    test("/matches/:id", async ({ page }, info) => {
      const list = await api<Array<{ id: number }>>("/api/v1/matches?limit=1");
      const first = list.data[0];
      test.skip(first === undefined, "no fixture on this database");
      info.annotations.push({ type: "fixture", description: String(first?.id) });
      const w = watch(page);
      await page.goto(`/matches/${first!.id}`);
      await settle(page);
      await assertClean(page, w);
    });
  });
}
