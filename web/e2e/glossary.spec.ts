/**
 * The one glossary (plan UX, A3), in the browser: a term inside a card opens its definition with a click, with the
 * keyboard (Enter, Escape) and with a finger, the definition says what the glossary says and leads to its entry,
 * on a 320 px phone it is a sheet from the bottom that fits the screen and closes with a tap, and /help/glossary
 * lists every term with its one definition and narrows them as the reader types. Runs at a desk (project user-es)
 * and as a touch phone (project mobile).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { L, assertClean, note, settle, watch } from "./support";

const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];

/** axe on one part of the page (or all of it): the new pieces of A3 start with no violation at all. */
async function axeViolations(page: Page, include?: string): Promise<string[]> {
  const builder = new AxeBuilder({ page }).withTags(WCAG);
  const result = await (include ? builder.include(include) : builder).analyze();
  return result.violations.map(
    (v) => `${v.id} (${v.impact ?? "?"}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
}

const G = L.es.glossary;
type Term = keyof typeof G.terms;
const TERMS = Object.keys(G.terms) as Term[];

function phone(): boolean {
  return test.info().project.name.startsWith("mobile");
}

/** The definition that opened: a card beside the word at a desk, a sheet from the bottom on a phone. */
function opened(page: Page): Locator {
  return page.locator('[data-testid="glossary-card"], [data-testid="glossary-sheet"]');
}

/**
 * A term inside a card: the expected value of a pick card (Picks), or - when the QA data has no pick today - the
 * return of a group card in Mis picks, which is always there.
 */
async function termInACard(page: Page): Promise<{ term: Locator; key: Term }> {
  await page.goto("/picks");
  await settle(page);
  const inPick = page
    .getByTestId("pick-card-figures")
    .locator('[data-glossary="expectedValue"]')
    .first();
  if (await inPick.count()) return { term: inPick, key: "expectedValue" };
  note(test.info(), "no pick card today: the term of a Mis picks card instead");
  await page.goto("/my-picks");
  await settle(page);
  return { term: page.locator('article [data-glossary="roi"]').first(), key: "roi" };
}

test("a term inside a card opens its definition, by click and by keyboard, and leads to its entry", async ({
  page,
}) => {
  test.skip(phone(), "the desk's card; the phone's sheet is the next test");
  const w = watch(page);
  const { term, key } = await termInACard(page);
  await expect(term).toBeVisible();
  const url = page.url();

  await term.click();
  const card = page.getByTestId("glossary-card");
  await expect(card).toBeVisible();
  await expect(card.getByRole("heading")).toHaveText(G.terms[key].name);
  await expect(card.getByTestId("glossary-short")).toHaveText(G.terms[key].short);
  await expect(term).toHaveAttribute("aria-expanded", "true");
  expect(page.url(), "the tap opened the definition, not the card's match").toBe(url);
  expect(
    await axeViolations(page, '[data-testid="glossary-card"]'),
    "axe on the open card",
  ).toEqual([]);

  await page.keyboard.press("Escape");
  await expect(card).toHaveCount(0);
  await expect(term).toBeFocused();
  await expect(term).toHaveAttribute("aria-expanded", "false");

  await page.keyboard.press("Enter");
  await expect(page.getByTestId("glossary-card")).toBeVisible();
  await page.getByTestId("glossary-more").click();
  await expect(page).toHaveURL(new RegExp(`/help/glossary#term-${key}$`));
  const entry = page.locator(`#term-${key}`);
  await expect(entry).toBeVisible();
  await expect(entry).toBeInViewport();
  await expect(entry).toContainText(G.terms[key].short);
  await assertClean(page, w);
});

test("on a 320 px phone the definition is a sheet from the bottom that fits, and a tap closes it", async ({
  page,
}) => {
  const w = watch(page);
  await page.setViewportSize({ width: 320, height: 640 });
  const { term, key } = await termInACard(page);
  await term.scrollIntoViewIfNeeded();
  if (phone()) await term.tap();
  else await term.click();
  const sheet = page.getByTestId("glossary-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("heading")).toHaveText(G.terms[key].name);
  await expect(sheet.getByTestId("glossary-short")).toHaveText(G.terms[key].short);
  // The sheet slides up from the bottom: measured once it has arrived (A3's e2e caught it 3.6 px below the screen,
  // mid-slide, under load).
  await expect
    .poll(
      async () => {
        const b = await sheet.boundingBox();
        return b ? b.y + b.height : Number.POSITIVE_INFINITY;
      },
      { message: "the sheet ends inside the screen" },
    )
    .toBeLessThanOrEqual(640 + 0.5);
  const box = await sheet.boundingBox();
  expect(box, "the sheet is on the screen").not.toBeNull();
  if (box) {
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(320 + 0.5);
    expect(box.y + box.height).toBeLessThanOrEqual(640 + 0.5);
  }
  expect(
    await sheet.evaluate((el) => el.scrollWidth <= el.clientWidth + 1),
    "nothing in the sheet scrolls sideways",
  ).toBe(true);
  expect(
    await axeViolations(page, '[data-testid="glossary-sheet"]'),
    "axe on the open sheet",
  ).toEqual([]);
  // its close button answers a finger (44 px with its reach) and closes it
  await sheet.getByRole("button", { name: G.ui.close }).click();
  await expect(sheet).toHaveCount(0);
  await expect(term).toBeFocused();
  // a tap outside it closes it too
  if (phone()) await term.tap();
  else await term.click();
  await expect(page.getByTestId("glossary-sheet")).toBeVisible();
  await page.mouse.click(160, 40);
  await expect(page.getByTestId("glossary-sheet")).toHaveCount(0);
  await expect(opened(page)).toHaveCount(0);
  await assertClean(page, w);
});

test("the glossary lists every term with its one definition, and a search narrows it without accents", async ({
  page,
}) => {
  const w = watch(page);
  await page.goto("/help/glossary");
  await settle(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(G.page.title);
  await expect(page.getByTestId("explain-layers")).toBeVisible();
  expect(await axeViolations(page), "axe on the glossary page").toEqual([]);
  const entries = page.getByTestId("glossary-entry");
  await expect(entries).toHaveCount(TERMS.length);
  for (const key of ["fairOdds", "predigolOdds", "push", "void", "halfWon"] as const) {
    const entry = page.locator(`#term-${key}`);
    await expect(entry.getByRole("heading")).toHaveText(G.terms[key].name);
    await expect(entry).toContainText(G.terms[key].short);
    await expect(entry).toContainText(G.terms[key].long);
  }
  // «handicap» without its accent finds «hándicap», which only the line's definition says
  await page.getByTestId("glossary-search").fill("handicap");
  await expect(entries).toHaveCount(1);
  await expect(entries.first()).toHaveAttribute("data-term", "line");
  await page.getByTestId("glossary-search").fill("zzzz");
  await expect(entries).toHaveCount(0);
  await expect(page.getByText(G.page.noResults.replace("{query}", "zzzz"))).toBeVisible();
  await page.getByTestId("glossary-search").fill("");
  await expect(entries).toHaveCount(TERMS.length);
  // a related term is one tap away, at its own anchor
  await page.locator("#term-fairOdds").getByRole("link", { name: G.terms.margin.name }).click();
  await expect(page).toHaveURL(/#term-margin$/);
  await expect(page.locator("#term-margin")).toBeInViewport();
  if (phone()) {
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
      "the page fits the phone",
    ).toBe(true);
  }
  await assertClean(page, w);
});

test("the account menu leads to the glossary", async ({ page }) => {
  test.skip(phone(), "the desk's header; the phone's menu is A15's");
  const w = watch(page);
  await page.goto("/home");
  await settle(page);
  await page.getByTestId("account-menu").click();
  await page.getByTestId("go-glossary").click();
  await expect(page).toHaveURL(/\/help\/glossary$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(G.page.title);
  await assertClean(page, w);
});
