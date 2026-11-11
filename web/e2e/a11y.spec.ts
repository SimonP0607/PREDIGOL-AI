/**
 * Accessibility, measured (phase A0 of the UX plan: "medición inicial con axe"). Runs only when asked
 * (E2E_A11Y=1, project "a11y"): axe-core reads the sign-in page and every product destination at a desk and on a
 * 390 px phone, against WCAG 2.2 A and AA. Since the closing plan (5.2) it is a gate: a CRITICAL or SERIOUS violation
 * fails the test, naming the rule and the elements; moderate and minor ones are still written down. The counts by
 * impact go to the report as an annotation and the whole result to axe-<page>-<width>.json in the test's output folder.
 * Since the 2026 redesign's wave 0 it reads every screen of e2e/inventory.ts: the pages before the product, a match's
 * six sections and the Admin Console's menu too. E2E_A11Y_REPORT=1 writes the results down without failing: the
 * baseline of a wave, taken before it changes anything.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { statePath } from "./accounts";
import { CONSOLE_PAGES, MATCH_TABS, PUBLIC_PAGES, READER_PAGES, firstMatchPath } from "./inventory";
import { settle } from "./support";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const REPORT_ONLY = Boolean(process.env["E2E_A11Y_REPORT"]);
// plan UX, A15: the pages of A4 and A12 the reader reaches from «Más» or a footer are read signed in as well
const PRODUCT = [...READER_PAGES, "/legal/terms"];
const WIDTHS: ReadonlyArray<readonly [number, number]> = [
  [1440, 900],
  [390, 844],
];

async function measure(page: Page, info: TestInfo, path: string, width: number): Promise<void> {
  const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const byImpact: Record<string, number> = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  for (const v of result.violations)
    byImpact[v.impact ?? "minor"] = (byImpact[v.impact ?? "minor"] ?? 0) + 1;
  const nodes = result.violations.reduce((n, v) => n + v.nodes.length, 0);
  const rules = result.violations.map((v) => `${v.id} (${v.impact ?? "?"}, ${v.nodes.length})`);
  info.annotations.push({
    type: "axe",
    description: `${path} @ ${width}px: ${result.violations.length} rules broken on ${nodes} elements - critical ${byImpact["critical"]}, serious ${byImpact["serious"]}, moderate ${byImpact["moderate"]}, minor ${byImpact["minor"]}${rules.length ? ` | ${rules.join("; ")}` : ""}`,
  });
  // the gate: what blocks a reader (critical) or makes the page hard to use (serious) is a failure, not a note
  const blocking = result.violations
    .filter((v) => v.impact === "critical" || v.impact === "serious")
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
  const name = `axe-${path.replace(/\W+/g, "_").replace(/^_|_$/g, "") || "root"}-${width}.json`;
  writeFileSync(
    info.outputPath(name),
    JSON.stringify(
      {
        path,
        width,
        tags: TAGS,
        axe: result.testEngine.version,
        violations: result.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          help: v.help,
          nodes: v.nodes.map((n) => n.target.join(" ")),
        })),
        incomplete: result.incomplete.map((v) => ({ id: v.id, nodes: v.nodes.length })),
        passes: result.passes.length,
      },
      null,
      2,
    ),
  );
  if (!REPORT_ONLY) expect(blocking, `${path} @ ${width}px: axe`).toEqual([]);
}

test.describe("the pages before the product", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  for (const [width, height] of WIDTHS) {
    for (const path of PUBLIC_PAGES) {
      test(`axe on ${path} without a session at ${width} px`, async ({ page }, info) => {
        await page.setViewportSize({ width, height });
        await page.goto(path);
        await settle(page);
        await measure(page, info, path, width);
      });
    }
  }
});

test.describe("the product, signed in", () => {
  test.use({ storageState: statePath("user") });
  for (const [width, height] of WIDTHS) {
    for (const path of PRODUCT) {
      test(`axe on ${path} at ${width} px`, async ({ page }, info) => {
        await page.setViewportSize({ width, height });
        await page.goto(path);
        await settle(page);
        await measure(page, info, path, width);
      });
    }
  }
});

// Plan UX, B1: the account centre on a phone - folded (the eight headers and their lines) and with every block open.
test.describe("the account centre on a phone", () => {
  test.use({ storageState: statePath("user") });
  test("axe on the profile's eight blocks open at 390 px", async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/profile");
    await settle(page);
    for (const toggle of await page.locator('[data-testid^="profile-toggle-"]').all())
      await toggle.click();
    await settle(page);
    await measure(page, info, "/profile+open", 390);
  });
});

// Plan UX, A15: the bar's «Más» and the filters' sheet, open on a phone (focus, names, contrast inside the dialogs).
test.describe("the sheets of the phone, open", () => {
  test.use({ storageState: statePath("user") });
  test("axe on «Más» open at 390 px", async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/home");
    await settle(page);
    await page.getByTestId("tab-more").click();
    await page.getByTestId("more-sheet").waitFor();
    await page.getByTestId("more-install-toggle").click();
    await measure(page, info, "/home+more", 390);
  });
  test("axe on the filters of Partidos open at 390 px", async ({ page }, info) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/matches");
    await settle(page);
    await page.getByTestId("matches-filters-open").click();
    await page.getByTestId("matches-filters-sheet").waitFor();
    await measure(page, info, "/matches+filters", 390);
  });
});

// The 2026 redesign's wave 0: a match's six sections, which the product's list above never opened.
test.describe("a match, section by section", () => {
  test.use({ storageState: statePath("user") });
  for (const [width, height] of WIDTHS) {
    test(`axe on a match's six sections at ${width} px`, async ({ page }, info) => {
      test.setTimeout(150_000);
      await page.setViewportSize({ width, height });
      const match = await firstMatchPath(page);
      test.skip(match === null, "no match on /matches today");
      for (const tab of MATCH_TABS) {
        await page.goto(`${match}#${tab}`);
        await settle(page);
        await measure(page, info, `/matches/:id#${tab}`, width);
      }
    });
  }
});

// The Admin Console's menu at the owner's desk: measured since the 2026 redesign's wave 0 (its pages get the new
// primitives in wave 15).
test.describe("the Admin Console", () => {
  test.use({ storageState: statePath("admin"), locale: "en-GB" });
  for (const path of CONSOLE_PAGES) {
    test(`axe on ${path} at 1440 px`, async ({ page }, info) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(path);
      await settle(page);
      await measure(page, info, path, 1440);
    });
  }
});
