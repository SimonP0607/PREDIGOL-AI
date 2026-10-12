/**
 * The product on phones and tablets (mobile UX audit, October 2026): every destination at every phone width from
 * 320 px, tablets in both orientations and a phone held sideways. Nothing scrolls sideways, every label of the tab
 * bar is whole, a control answers a finger (44 x 44 px, the "tap" reach included), a form field never makes iOS
 * zoom in, team names are whole in the cards, the Match Center's tab strip says when more tabs wait beyond the
 * screen's edge, and the parlay slip works under a thumb. The project runs as a touch phone (Pixel 7).
 */
import { expect, test, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { assertClean, getJson, note, settle, watch } from "./support";

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
const PHONES = [320, 360, 375, 390, 412, 430];

/** Labels of the tab bar that do not fit their cell (an ellipsis). */
async function cutLabels(page: Page): Promise<string[]> {
  return page.$$eval('[data-testid="tab-label"]', (els) =>
    els
      .filter((e) => e.getBoundingClientRect().width > 0 && e.scrollWidth > e.clientWidth + 1)
      .map((e) => e.textContent ?? ""),
  );
}

/** Team names drawn with an ellipsis. */
async function cutNames(page: Page): Promise<string[]> {
  return page.$$eval('[data-testid="team-name"]', (els) =>
    els
      .filter((e) => {
        const s = getComputedStyle(e);
        return (
          e.getBoundingClientRect().width > 0 &&
          s.textOverflow === "ellipsis" &&
          e.scrollWidth > e.clientWidth + 1
        );
      })
      .map((e) => e.textContent ?? ""),
  );
}

/**
 * The controls a finger cannot hit at 44 x 44 px: the box, widened by the "tap" utilities' ::after, cut by a
 * clipping parent the control sits inside. Inline text links are exempt (WCAG 2.5.8).
 */
async function smallTargets(page: Page, scope = "body"): Promise<string[]> {
  return page.evaluate((root) => {
    const out: string[] = [];
    const container = document.querySelector(root);
    if (!container) return out;
    const sel =
      'a[href], button, [role="tab"], input:not([type="hidden"]), select, textarea, summary, [role="switch"]';
    for (const control of Array.from(container.querySelectorAll<HTMLElement>(sel))) {
      // A native select or date field laid invisibly over its chip (opacity 0): the chip is what a finger aims at.
      const el =
        getComputedStyle(control).opacity === "0" && control.parentElement
          ? control.parentElement
          : control;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      if (!r.width || !r.height || s.visibility === "hidden" || s.display === "none") continue;
      if (el.tagName === "A" && s.display === "inline") continue;
      // A control under another layer (an open sheet's backdrop) is not in reach anyway.
      const hitTest = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (
        hitTest &&
        !el.contains(hitTest) &&
        !hitTest.contains(el) &&
        r.top >= 0 &&
        r.bottom <= innerHeight
      )
        continue;
      let top = r.top;
      let bottom = r.bottom;
      let left = r.left;
      let right = r.right;
      const a = getComputedStyle(el, "::after");
      if (
        a.content &&
        a.content !== "none" &&
        a.content !== "normal" &&
        a.position === "absolute"
      ) {
        top = Math.min(top, r.top + parseFloat(a.top));
        bottom = Math.max(bottom, r.bottom - parseFloat(a.bottom));
        left = Math.min(left, r.left + parseFloat(a.left));
        right = Math.max(right, r.right - parseFloat(a.right));
      }
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ps = getComputedStyle(p);
        if (ps.overflowX === "visible" && ps.overflowY === "visible") continue;
        const pr = p.getBoundingClientRect();
        if (r.top >= pr.top - 0.5 && r.bottom <= pr.bottom + 0.5) {
          top = Math.max(top, pr.top);
          bottom = Math.min(bottom, pr.bottom);
        }
        if (r.left >= pr.left - 0.5 && r.right <= pr.right + 0.5) {
          left = Math.max(left, pr.left);
          right = Math.min(right, pr.right);
        }
      }
      if (right - left < 43.5 || bottom - top < 43.5) {
        const name = (control.getAttribute("aria-label") ?? control.textContent ?? "")
          .trim()
          .slice(0, 40);
        out.push(
          `${el.tagName.toLowerCase()} "${name}" ${Math.round(right - left)}x${Math.round(bottom - top)}`,
        );
      }
    }
    return out;
  }, scope);
}

test("every product page fits every phone width, with the whole tab bar", async ({ page }) => {
  test.setTimeout(420_000);
  const w = watch(page);
  for (const width of PHONES) {
    await page.setViewportSize({ width, height: width < 360 ? 568 : 844 });
    for (const path of PAGES) {
      await page.goto(path);
      await settle(page);
      await expect(page.getByTestId("tab-home"), `the tab bar at ${width} px`).toBeVisible();
      expect(await cutLabels(page), `tab bar labels cut at ${width} px on ${path}`).toEqual([]);
      await assertClean(page, w);
    }
  }
});

test("team names are whole in the cards of a 320 px phone", async ({ page }) => {
  test.setTimeout(180_000);
  const w = watch(page);
  await page.setViewportSize({ width: 320, height: 568 });
  for (const path of ["/home", "/matches", "/picks", "/parlays", "/odds", "/my-picks"]) {
    await page.goto(path);
    await settle(page);
    expect(await cutNames(page), `team names cut on ${path}`).toEqual([]);
    await assertClean(page, w);
  }
});

test("tablets in both orientations and a phone held sideways", async ({ page }) => {
  test.setTimeout(300_000);
  const w = watch(page);
  const sizes: Array<[number, number]> = [
    [768, 1024],
    [820, 1180],
    [1024, 1366],
    [1024, 768],
    [1180, 820],
    [844, 390],
  ];
  for (const [width, height] of sizes) {
    await page.setViewportSize({ width, height });
    for (const path of PAGES) {
      await page.goto(path);
      await settle(page);
      await assertClean(page, w);
    }
  }
});

test("a phone held sideways gives the screen to the content", async ({ page }) => {
  const w = watch(page);
  await page.setViewportSize({ width: 844, height: 390 });
  await page.goto("/home");
  await settle(page);
  // The top bar scrolls away with the page; the tab bar is the short one (icon and label in a row).
  const header = page.locator("header").first();
  expect(await header.evaluate((e) => getComputedStyle(e).position)).toBe("static");
  const bar = page
    .getByRole("navigation", { name: /./ })
    .filter({ has: page.getByTestId("tab-home") });
  const box = await bar.boundingBox();
  expect(box?.height ?? 0, "the sideways tab bar's height").toBeLessThanOrEqual(48);
  await assertClean(page, w);
});

test("controls answer a finger: 44 x 44 px on a touch phone", async ({ page }) => {
  test.setTimeout(240_000);
  const w = watch(page);
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const path of PAGES) {
      await page.goto(path);
      await settle(page);
      expect(await smallTargets(page), `controls under 44 px at ${width} px on ${path}`).toEqual(
        [],
      );
      await assertClean(page, w);
    }
  }
});

test("form fields never make iOS zoom in (16 px at least on a touch screen)", async ({ page }) => {
  test.setTimeout(180_000);
  const w = watch(page);
  for (const path of ["/matches", "/odds", "/parlays", "/picks", "/profile"]) {
    await page.goto(path);
    await settle(page);
    const small = await page.$$eval("input, select, textarea", (els) =>
      els
        .filter((e) => {
          const t = (e as HTMLInputElement).type;
          return (
            e.getBoundingClientRect().width > 0 &&
            !["checkbox", "radio", "range", "color", "file", "hidden"].includes(t)
          );
        })
        .map((e) => `${e.getAttribute("data-testid") ?? e.tagName} ${getComputedStyle(e).fontSize}`)
        .filter((s) => parseFloat(s.split(" ").pop() ?? "0") < 16),
    );
    expect(small, `form fields under 16 px on ${path}`).toEqual([]);
    await assertClean(page, w);
  }
});

test("the Match Center's tab strip says when more tabs wait beyond the edge", async ({ page }) => {
  const w = watch(page);
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    "/api/v1/matches?limit=1&order=desc",
  );
  const id = body.data[0]?.id;
  if (!id) {
    note(test.info(), "no match to open");
    return;
  }
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto(`/matches/${id}`);
  await settle(page);
  const strip = page.getByRole("tablist").first();
  const overflows = await strip.evaluate((e) => e.scrollWidth > e.clientWidth + 1);
  if (!overflows) {
    note(test.info(), "the tabs fit at 320 px: no cue needed");
    return;
  }
  await expect(strip).toHaveAttribute("data-fade-end", "");
  await expect(strip).not.toHaveAttribute("data-fade-start", "");
  await strip.evaluate((e) => e.scrollTo({ left: e.scrollWidth }));
  await expect(strip).toHaveAttribute("data-fade-start", "");
  await expect(strip).not.toHaveAttribute("data-fade-end", "");
  // The last tab can be reached and opened.
  await page.getByRole("tab").last().click();
  await expect(page.getByRole("tab").last()).toHaveAttribute("aria-selected", "true");
  await assertClean(page, w);
});

test("the parlay slip under a thumb: a 44 px close, nothing on its title, its fields at 16 px", async ({
  page,
}) => {
  const w = watch(page);
  const { body } = await getJson<{
    data: { fixtures: Array<{ fixture_id: number; kickoff_at: string }> };
  }>(page.request, "/api/v1/odds/best?hours=72&market=1X2");
  const soon = Date.now() + 30 * 60_000;
  const ids = body.data.fixtures
    .filter((f) => Date.parse(f.kickoff_at) > soon)
    .map((f) => f.fixture_id)
    .slice(0, 2);
  if (ids.length < 2) {
    note(test.info(), "fewer than two upcoming matches with a 1X2 price");
    return;
  }
  await page.setViewportSize({ width: 390, height: 844 });
  for (const id of ids) {
    await page.goto(`/matches/${id}#markets`);
    await settle(page);
    const add = page.getByTestId("odds-add-to-parlay").first();
    await add.click();
    await expect(add).toHaveAttribute("aria-pressed", "true");
  }
  await page.getByTestId("slip-open").click();
  const sheet = page.getByTestId("slip-sheet");
  await expect(sheet.getByTestId("slip-leg")).toHaveCount(2);
  // Opening the slip clears the "added" notices: none covers its title or its close button.
  await expect(page.locator("[data-sonner-toast]")).toHaveCount(0);
  expect(
    await smallTargets(page, '[data-testid="slip-sheet"]'),
    "slip controls under 44 px",
  ).toEqual([]);
  const size = await sheet.getByTestId("slip-name").evaluate((e) => getComputedStyle(e).fontSize);
  expect(parseFloat(size)).toBeGreaterThanOrEqual(16);
  await expect(sheet.getByTestId("slip-save")).toBeInViewport();
  await sheet.getByTestId("slip-clear").click();
  await expect(sheet.getByTestId("slip-leg")).toHaveCount(0);
  await assertClean(page, w);
});

/** Every module of the Admin Console (src/routes/admin.*). */
const ADMIN_PAGES = [
  "/admin/overview",
  "/admin/picks",
  "/admin/users",
  "/admin/ai-layer",
  "/admin/ai-analyst",
  "/admin/evolution",
  "/admin/performance",
  "/admin/odds",
  "/admin/models",
  "/admin/backtesting",
  "/admin/analytics",
  "/admin/competitions",
  "/admin/teams",
  "/admin/players",
  "/admin/rankings",
  "/admin/data-quality",
  "/admin/data-truth",
  "/admin/migration",
  "/admin/system",
  "/admin/audit",
  "/admin/settings",
];

test.describe("the Admin Console on a phone", () => {
  test.use({ storageState: statePath("admin"), locale: "en-GB" });

  // The Audit page's action filter (a label and a select that would not wrap) pushed the page 21 px sideways at
  // 320 px: a module that works at a desk must at least not scroll sideways in an operator's hand.
  test("no module scrolls sideways at 320 or 390 px", async ({ context }) => {
    test.setTimeout(360_000);
    for (const width of [320, 390]) {
      for (const path of ADMIN_PAGES) {
        // A page of its own for each module: forty-two loads of the dev server's unbundled modules in one page run
        // Chromium out of resources (ERR_INSUFFICIENT_RESOURCES) - a test artefact, not the app's.
        const page = await context.newPage();
        const w = watch(page);
        await page.setViewportSize({ width, height: 800 });
        await page.goto(path);
        await settle(page);
        await assertClean(page, w);
        await page.close();
      }
    }
  });
});

test.describe("the Admin Console on a touch tablet", () => {
  test.use({ storageState: statePath("admin"), locale: "en-GB" });

  test("no page scrolls sideways; the header and the menu answer a finger", async ({ page }) => {
    test.setTimeout(240_000);
    const w = watch(page);
    for (const [width, height] of [
      [768, 1024],
      [1024, 768],
      [1180, 820],
    ] as const) {
      await page.setViewportSize({ width, height });
      for (const path of ["/admin/overview", "/admin/picks", "/admin/users", "/admin/ai-layer"]) {
        await page.goto(path);
        await settle(page);
        expect(
          await smallTargets(page, "header"),
          `header controls at ${width} px on ${path}`,
        ).toEqual([]);
        await assertClean(page, w);
      }
    }
  });

  // The overview's panel links ("Live" was 21 px wide), the explained "—" (cut to 7 x 16 px by a truncating value
  // cell) and the definitions in table headers (38 px under the table's scroll box) were out of a finger's reach.
  test("the modules' own controls answer a finger, not only the header's", async ({ page }) => {
    test.setTimeout(240_000);
    const w = watch(page);
    for (const [width, height] of [
      [768, 1024],
      [1024, 768],
    ] as const) {
      await page.setViewportSize({ width, height });
      for (const path of ["/admin/overview", "/admin/picks", "/admin/models", "/admin/system"]) {
        await page.goto(path);
        await settle(page);
        expect(await smallTargets(page, "main"), `controls at ${width} px on ${path}`).toEqual([]);
        await assertClean(page, w);
      }
    }
  });

  test("Users: a card per account with its actions in reach below 1280 px, the table from there", async ({
    page,
  }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1024, height: 1366 });
    await page.goto("/admin/users");
    await settle(page);
    await expect(page.getByTestId("users-cards")).toBeVisible();
    await expect(page.getByTestId("users-table")).toBeHidden();
    expect(await smallTargets(page, '[data-testid="users-cards"]'), "account actions").toEqual([]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await expect(page.getByTestId("users-table")).toBeVisible();
    await assertClean(page, w);
  });

  test("a definition opens with a tap (a tooltip is never mouse-only)", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1024, height: 768 });
    let tip = null;
    for (const path of ["/admin/overview", "/admin/models", "/admin/picks"]) {
      await page.goto(path);
      await settle(page);
      const found = page.getByRole("button", { name: /^What is/ }).first();
      if (await found.count()) {
        tip = found;
        break;
      }
    }
    if (!tip) {
      note(test.info(), "no metric definition on screen with the QA data");
      return;
    }
    await tip.scrollIntoViewIfNeeded();
    await tip.tap();
    await expect(page.getByRole("tooltip")).toBeVisible();
    await tip.tap();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await assertClean(page, w);
  });
});
