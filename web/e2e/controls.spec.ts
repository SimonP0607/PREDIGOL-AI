/**
 * Layout guards (Plan Maestro de Correcciones, AP-Q03 and AP-Q04): the pages where the owner's audit found text drawn as a
 * column of letters («Profundizar», the parlay's total) and rows of chips a mouse cannot reach («Mitades»), measured at
 * the plan's nine widths.
 *
 * Every defect the audit found is LISTED below with the piece that fixes it. A listed defect that still happens is
 * tolerated; one that no longer happens must leave the list (the test fails until it does); one that is not listed
 * fails. So the guard is green today, red the day a layout breaks again, and each fix is forced to delete its line.
 *   AP_PROBE=1 prints what each page shows, to build or check the list.
 */
import { expect, test, type Page } from "@playwright/test";
import { firstMatchPath, MATCH_TABS } from "./inventory";
import { cascades, NINE_WIDTHS, overflowing, unreachableStrips, type Finding } from "./layoutguard";
import { settle } from "./support";

/**
 * Each defect the audit or the guard found, with the piece of the plan that fixes it and the widths where it happens
 * («kind|path|address»). A width's test must find exactly the defects listed for it.
 */
const KNOWN: Readonly<Record<string, { piece: string; widths: readonly number[] }>> = {
  // The day selector of Partidos is wider than the bar that holds it on a desk.
  "overflow|/matches|[day-nav] div.scroll-strip.-my-1.flex": {
    piece: "AP-P04",
    widths: [1024, 1280, 1440, 1920],
  },
};

const PROBE = process.env["AP_PROBE"] === "1";

function heightFor(width: number): number {
  return width < 600 ? 844 : width < 1024 ? 1180 : 900;
}

/** Identifies a defect without its numbers or its text, so the same one at two widths or on two days is one line. */
function key(path: string, f: Finding): string {
  const where = path.replace(/\/matches\/\d+/, "/matches/:id");
  return `${f.kind}|${where}|${f.at.replace(/\d+ px/g, "N px").replace(/\s*«[^»]*»/, "")}`;
}

/** Opens the folded blocks of the page («Profundizar»' rows, market groups): a defect inside one is a defect all the same. */
async function openFolds(page: Page): Promise<void> {
  for (let round = 0; round < 3; round++) {
    const closed = page.locator(
      'main [aria-expanded="false"]:not([role="tab"]):not([aria-haspopup])',
    );
    const n = Math.min(await closed.count(), 16);
    if (n === 0) return;
    for (let i = 0; i < n; i++) {
      await closed
        .nth(i)
        .click({ timeout: 1500, trial: false })
        .catch(() => undefined);
    }
    await page.waitForTimeout(400);
  }
}

async function survey(page: Page, path: string, width: number): Promise<string[]> {
  await page.setViewportSize({ width, height: heightFor(width) });
  await page.goto(path);
  await settle(page);
  await openFolds(page);
  const found = [...(await cascades(page)), ...(await overflowing(page))];
  if (width >= 1024) found.push(...(await unreachableStrips(page)));
  return found.map((f) => key(path, f));
}

async function pagesToSurvey(page: Page): Promise<string[]> {
  const match = await firstMatchPath(page);
  const pages = [
    "/home",
    "/matches",
    "/picks",
    "/parlays",
    "/odds",
    "/my-picks",
    "/teams",
    "/news",
    "/help",
  ];
  if (match) for (const tab of MATCH_TABS) pages.push(`${match}#${tab}`);
  return pages;
}

for (const width of NINE_WIDTHS) {
  test(`no column of letters, no block past its box, no chip row out of reach: ${width} px`, async ({
    page,
  }) => {
    test.setTimeout(240_000);
    const found = new Set<string>();
    for (const path of await pagesToSurvey(page)) {
      for (const k of await survey(page, path.split("#")[0] ?? path, width)) found.add(k);
    }
    if (PROBE) console.log(`PROBE ${width} ` + JSON.stringify([...found].sort(), null, 1));
    const listed = Object.entries(KNOWN)
      .filter(([, v]) => v.widths.includes(width))
      .map(([k]) => k);
    expect(
      [...found].filter((k) => !listed.includes(k)),
      "a layout defect that is not on the list",
    ).toEqual([]);
    expect(
      listed.filter((k) => !found.has(k)),
      "listed defects that no longer happen at this width: remove them from the list",
    ).toEqual([]);
  });
}

/**
 * The detectors themselves, on markup that has the audit's defects: the QA data does not always draw «Profundizar»'s
 * three-column rows or a row of chips wider than its box, so the guard is proved on a page made for it.
 */
test("the guards catch the defects the audit found", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.setContent(`<main style="width:1000px">
    <div style="display:grid;grid-template-columns:1fr 1fr 9ch;width:340px">
      <p>Más de 2,5 goles</p><p>Ambos marcan</p><p style="width:24px;margin:0;word-break:break-all">Profundizar</p>
    </div>
    <div style="width:300px;overflow-x:auto;scrollbar-width:none;display:flex;gap:4px"><button style="flex:none;width:200px">Mitades</button><button style="flex:none;width:200px">Corners</button></div>
    <div style="width:200px"><div style="width:260px;height:20px">más ancho que su caja</div></div>
  </main>`);
  expect((await cascades(page)).length).toBe(1);
  expect((await unreachableStrips(page)).length).toBe(1);
  expect((await overflowing(page)).length).toBeGreaterThan(0);
  // and a strip with arrows next to it is reachable
  await page.setContent(`<main><div><button data-strip-arrow>‹</button>
    <div style="width:300px;overflow-x:auto;scrollbar-width:none;display:flex"><button style="flex:none;width:400px">Mitades</button></div></div></main>`);
  expect((await unreachableStrips(page)).length).toBe(0);
});
