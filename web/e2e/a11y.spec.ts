/**
 * Accessibility, measured (phase A0 of the UX plan: "medición inicial con axe"). Runs only when asked
 * (E2E_A11Y=1, project "a11y"): axe-core reads the sign-in page and every product destination at a desk and on a
 * 390 px phone, against WCAG 2.2 A and AA. Since the closing plan (5.2) it is a gate: a CRITICAL or SERIOUS violation
 * fails the test, naming the rule and the elements; moderate and minor ones are still written down. The counts by
 * impact go to the report as an annotation and the whole result to axe-<page>-<width>.json in the test's output folder.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { statePath } from "./accounts";
import { settle } from "./support";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const PRODUCT = [
  "/home",
  "/matches",
  "/live",
  "/picks",
  "/parlays",
  "/odds",
  "/my-picks",
  "/profile",
  "/help/glossary",
  "/help/how-it-works",
  "/help",
  // plan UX, A15: the pages of A4 and A12 the reader reaches from «Más» or a footer
  "/transparency",
  "/legal/terms",
];
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
  expect(blocking, `${path} @ ${width}px: axe`).toEqual([]);
}

for (const [width, height] of WIDTHS) {
  test(`axe on the sign-in page at ${width} px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height });
    await page.goto("/login");
    await settle(page);
    await measure(page, info, "/login", width);
  });
}

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
