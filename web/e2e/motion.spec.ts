/**
 * The motion system (closing plan 5.1), in the browser: with «reduce motion» nothing on the product animates or
 * transitions for longer than a blink, and the phone's three screens that matter (Inicio, Picks, a match's list) do not
 * shift their layout while they load (CLS under 0.1, the plan's budget of 5.2).
 */
import { expect, test, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { settle } from "./support";

test.use({ storageState: statePath("user") });

/** The longest animation or transition duration, in ms, among the elements of the page that are not spinners. */
async function longestMotion(page: Page): Promise<number> {
  return page.evaluate(() => {
    const ms = (v: string) =>
      Math.max(
        ...v
          .split(",")
          .map((x) => (x.trim().endsWith("ms") ? parseFloat(x) : parseFloat(x) * 1000) || 0),
      );
    let longest = 0;
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      if (el.classList.contains("animate-spin")) continue;
      const s = getComputedStyle(el);
      longest = Math.max(longest, ms(s.animationDuration), ms(s.transitionDuration));
    }
    return longest;
  });
}

test("with reduced motion, nothing animates or transitions for longer than a blink", async ({
  browser,
}) => {
  const context = await browser.newContext({
    storageState: statePath("user"),
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  for (const path of ["/home", "/picks", "/matches"]) {
    await page.goto(path);
    await settle(page);
    expect(await longestMotion(page), path).toBeLessThanOrEqual(1);
  }
  await context.close();
});

test("the three screens that matter do not shift while they load (CLS < 0.1)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  // once, before the loop: it runs again in every new document, and two observers would count each shift twice
  await page.addInitScript(() => {
    (window as unknown as { __cls: number }).__cls = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as unknown as Array<{
        value: number;
        hadRecentInput: boolean;
      }>) {
        if (!entry.hadRecentInput) (window as unknown as { __cls: number }).__cls += entry.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
  for (const path of ["/home", "/picks", "/matches"]) {
    await page.goto(path);
    await settle(page);
    const cls = await page.evaluate(() => (window as unknown as { __cls: number }).__cls);
    expect(cls, path).toBeLessThan(0.1);
  }
});
