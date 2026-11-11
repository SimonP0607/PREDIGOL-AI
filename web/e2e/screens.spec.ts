/**
 * Reference screenshots of the product (phase A0 of the UX plan: "capturas de referencia 320/360/390/412/430"; since
 * the 2026 redesign's wave 0, every screen of e2e/inventory.ts on phones, tablets and at a desk). Runs only when asked
 * (E2E_SCREENS=1, project "screens"): the whole page, signed in as the Spanish QA reader at every width, as the
 * English one at 390 and 1440 px, without a session for the pages before the product, and as the owner for the Admin
 * Console at 1440 px. The pictures go to the test's output folder (<es|en>/<width>/<page>.png); they are a record to
 * compare a wave's result with by eye, not a pixel test - the data under them changes every day. Nothing is checked
 * here except that each page loads and settles, and that the API answered it (see watchApi).
 *   E2E_SCREENS_ONLY=reader|public|console|match limits the run to one group (a wave that touches one module).
 */
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { statePath } from "./accounts";
import {
  CONSOLE_PAGES,
  DESK_WIDTHS,
  MATCH_TABS,
  PHONE_WIDTHS,
  PUBLIC_PAGES,
  READER_PAGES,
  TABLET_WIDTHS,
  firstMatchPath,
  heightFor,
  slugOf,
} from "./inventory";
import { settle } from "./support";

const ONLY = process.env["E2E_SCREENS_ONLY"];
const wants = (group: string): boolean => !ONLY || ONLY === group;

// A desk is not a wide phone: no touch, a mouse's pointer, one device pixel per CSS pixel.
const DESK = { isMobile: false, hasTouch: false, deviceScaleFactor: 1 } as const;

/**
 * What makes a picture worthless as a reference: the API refusing the run (429: FBI_API_RATE_LIMIT too low for a few
 * hundred pages) or failing (5xx), and the «no connection» screen that follows. A page that shows either fails here
 * instead of leaving a picture of the wrong thing.
 */
function watchApi(page: Page): string[] {
  const refused: string[] = [];
  page.on("response", (r) => {
    const status = r.status();
    if (r.url().includes("/api/v1/") && (status === 429 || status >= 500))
      refused.push(`${status} ${new URL(r.url()).pathname}`);
  });
  return refused;
}

async function shoot(
  page: Page,
  info: TestInfo,
  lang: string,
  width: number,
  name: string,
  refused: string[],
): Promise<void> {
  await settle(page);
  expect(refused, `${name} at ${width} px: the API refused or failed`).toEqual([]);
  await expect(page.getByTestId("connection-problem"), `${name} at ${width} px`).toHaveCount(0);
  await page.screenshot({ path: info.outputPath(lang, `${width}`, `${name}.png`), fullPage: true });
}

async function shootAll(
  page: Page,
  info: TestInfo,
  lang: string,
  width: number,
  paths: readonly string[],
): Promise<void> {
  const refused = watchApi(page);
  await page.setViewportSize({ width, height: heightFor(width) });
  for (const path of paths) {
    await page.goto(path);
    await shoot(page, info, lang, width, slugOf(path), refused);
  }
}

async function shootMatch(page: Page, info: TestInfo, lang: string, width: number): Promise<void> {
  const refused = watchApi(page);
  await page.setViewportSize({ width, height: heightFor(width) });
  const match = await firstMatchPath(page);
  test.skip(match === null, "no match on /matches today");
  for (const tab of MATCH_TABS) {
    // a full load per section: a change of hash alone keeps the section the page already shows
    await page.goto("about:blank");
    await page.goto(`${match}#${tab}`);
    await shoot(page, info, lang, width, `match_${tab}`, refused);
  }
}

// A fresh tab every few pages (see responsive.spec.ts on why one tab must not load forty pages).
function chunks<T>(items: readonly T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}
const READER_CHUNKS = chunks(READER_PAGES, 5);
const CONSOLE_CHUNKS = chunks(CONSOLE_PAGES, 7);

test.describe("the reader, in Spanish", () => {
  test.use({ storageState: statePath("user") });
  for (const width of [...PHONE_WIDTHS, ...TABLET_WIDTHS]) {
    for (const [i, pages] of READER_CHUNKS.entries()) {
      test(`reference screenshots at ${width} px, part ${i + 1}`, async ({ page }, info) => {
        test.skip(!wants("reader"));
        test.setTimeout(150_000);
        await shootAll(page, info, "es", width, pages);
      });
    }
    test(`reference screenshots of a match at ${width} px`, async ({ page }, info) => {
      test.skip(!wants("match"));
      test.setTimeout(150_000);
      await shootMatch(page, info, "es", width);
    });
  }
  test.describe("at a desk", () => {
    test.use(DESK);
    for (const width of DESK_WIDTHS) {
      for (const [i, pages] of READER_CHUNKS.entries()) {
        test(`reference screenshots at ${width} px, part ${i + 1}`, async ({ page }, info) => {
          test.skip(!wants("reader"));
          test.setTimeout(150_000);
          await shootAll(page, info, "es", width, pages);
        });
      }
      test(`reference screenshots of a match at ${width} px`, async ({ page }, info) => {
        test.skip(!wants("match"));
        test.setTimeout(150_000);
        await shootMatch(page, info, "es", width);
      });
    }
  });
});

test.describe("the reader, in English", () => {
  test.use({ storageState: statePath("userEn"), locale: "en-GB", timezoneId: "Europe/Madrid" });
  for (const [i, pages] of READER_CHUNKS.entries()) {
    test(`reference screenshots at 390 px, part ${i + 1}`, async ({ page }, info) => {
      test.skip(!wants("reader"));
      test.setTimeout(150_000);
      await shootAll(page, info, "en", 390, pages);
    });
  }
  test.describe("at a desk", () => {
    test.use(DESK);
    for (const [i, pages] of READER_CHUNKS.entries()) {
      test(`reference screenshots at 1440 px, part ${i + 1}`, async ({ page }, info) => {
        test.skip(!wants("reader"));
        test.setTimeout(150_000);
        await shootAll(page, info, "en", 1440, pages);
      });
    }
  });
});

test.describe("the pages before the product", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  for (const width of [320, 390, 820]) {
    test(`reference screenshots at ${width} px`, async ({ page }, info) => {
      test.skip(!wants("public"));
      test.setTimeout(150_000);
      await shootAll(page, info, "es", width, PUBLIC_PAGES);
    });
  }
  test.describe("at a desk", () => {
    test.use(DESK);
    test("reference screenshots at 1440 px", async ({ page }, info) => {
      test.skip(!wants("public"));
      test.setTimeout(150_000);
      await shootAll(page, info, "es", 1440, PUBLIC_PAGES);
    });
  });
});

test.describe("the Admin Console", () => {
  // the console is the owner's desk tool: one width, the one its pages are laid out for
  test.use({ storageState: statePath("admin"), locale: "en-GB", ...DESK });
  for (const [i, pages] of CONSOLE_CHUNKS.entries()) {
    test(`reference screenshots at 1440 px, part ${i + 1}`, async ({ page }, info) => {
      test.skip(!wants("console"));
      test.setTimeout(240_000);
      await shootAll(page, info, "admin", 1440, pages);
    });
  }
});
