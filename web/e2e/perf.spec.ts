/**
 * The performance budget on a phone (closing plan 5.2), in the browser: the LCP and the CLS of Inicio, a match and Picks,
 * on a Pixel 7 with the reader's session. Runs when asked (E2E_PERF=1, project "perf"), best against `vite preview` or
 * the staging site rather than `vite dev`, whose unminified bundle is slower than anything a reader gets. The budget is
 * the «good» line of the web vitals: CLS under 0.1 and LCP under 2.5 s; E2E_LCP_MS raises the LCP line for a slow
 * machine (the number stays in the report either way, as an annotation).
 * Since the 2026 redesign's wave 0 a second test writes down, without judging them, the LCP and the CLS of every
 * reader's destination and the slowest interaction of opening and closing «Más» on each (what the INP is made of):
 * vitals.json in the test's output folder, the baseline a wave's result is compared with.
 */
import { expect, test, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { statePath } from "./accounts";
import { READER_PAGES } from "./inventory";
import { settle } from "./support";

const LCP_MS = Number(process.env["E2E_LCP_MS"] ?? 2500);
const CLS_MAX = 0.1;

test.use({ storageState: statePath("phone") });

interface Vitals {
  lcp: number;
  cls: number;
  /** The longest interaction seen so far, in ms (0: none): the INP of a visit is its slowest but a few. */
  inp: number;
}

type Vwin = { __vitals: Vitals };

async function observe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const v = { lcp: 0, cls: 0, inp: 0 };
    (window as unknown as Vwin).__vitals = v;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) v.lcp = e.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as Array<{
        value: number;
        hadRecentInput: boolean;
      }>) {
        if (!e.hadRecentInput) v.cls += e.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
    try {
      new PerformanceObserver((list) => {
        for (const e of list.getEntries() as unknown as Array<{
          duration: number;
          interactionId?: number;
        }>) {
          if (e.interactionId && e.duration > v.inp) v.inp = e.duration;
        }
      }).observe({
        type: "event",
        buffered: true,
        durationThreshold: 16,
      } as PerformanceObserverInit);
    } catch {
      // a browser without the Event Timing API: the interaction stays at 0
    }
  });
}

async function vitals(page: Page): Promise<Vitals> {
  return page.evaluate(() => ({ ...(window as unknown as Vwin).__vitals }));
}

async function firstMatchPath(page: Page): Promise<string> {
  await page.goto("/matches");
  await settle(page);
  const href = await page.locator('a[href^="/matches/"]').first().getAttribute("href");
  if (!href) throw new Error("no match to measure on /matches");
  return href.split(/[?#]/)[0] ?? href;
}

test("Inicio, a match and Picks stay inside the web vitals' «good» line on a phone", async ({
  page,
}, info) => {
  test.setTimeout(120_000);
  await observe(page);
  const match = await firstMatchPath(page);
  for (const path of ["/home", match, "/picks"]) {
    await page.goto(path);
    await settle(page);
    // the LCP is final once the reader acts or the page is hidden; a short wait lets the last paint land
    await page.waitForTimeout(500);
    const v = await vitals(page);
    info.annotations.push({
      type: "vitals",
      description: `${path}: LCP ${Math.round(v.lcp)} ms, CLS ${v.cls.toFixed(3)}`,
    });
    expect(v.cls, `${path}: CLS`).toBeLessThan(CLS_MAX);
    expect(v.lcp, `${path}: LCP`).toBeLessThan(LCP_MS);
  }
});

test("the vitals of every destination, written down", async ({ page }, info) => {
  test.setTimeout(300_000);
  await observe(page);
  const match = await firstMatchPath(page);
  const rows: Array<{ path: string; lcp: number; cls: number; inp: number }> = [];
  for (const path of [...READER_PAGES, match]) {
    await page.goto(path);
    await settle(page);
    await page.waitForTimeout(500);
    // one interaction every page has on a phone: «Más» opens its sheet and Escape closes it
    const more = page.getByTestId("tab-more");
    if (await more.isVisible()) {
      await more.click();
      await page.getByTestId("more-sheet").waitFor();
      await page.keyboard.press("Escape");
      await page.getByTestId("more-sheet").waitFor({ state: "hidden" });
      await page.waitForTimeout(300);
    }
    const v = await vitals(page);
    const row = {
      path: path === match ? "/matches/:id" : path,
      lcp: Math.round(v.lcp),
      cls: Number(v.cls.toFixed(3)),
      inp: Math.round(v.inp),
    };
    rows.push(row);
    info.annotations.push({
      type: "vitals",
      description: `${row.path}: LCP ${row.lcp} ms, CLS ${row.cls}, interaction ${row.inp} ms`,
    });
  }
  writeFileSync(info.outputPath("vitals.json"), JSON.stringify(rows, null, 2));
});
