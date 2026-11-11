/**
 * The product on phones and tablets (mobile UX audit, October 2026): every destination at every phone width from
 * 320 px, tablets in both orientations and a phone held sideways. Nothing scrolls sideways, every label of the tab
 * bar is whole, a control answers a finger (44 x 44 px, the "tap" reach included), a form field never makes iOS
 * zoom in, team names are whole in the cards, the Match Center's tab strip says when more tabs wait beyond the
 * screen's edge, and the parlay slip works under a thumb. The project runs as a touch phone (Pixel 7).
 *
 * Plan UX, A15 (gate G11): five destinations - Inicio, Partidos, Picks, Mis picks and «Más» - whole at 320 px with
 * 12 px labels; Perfil, Ayuda and Transparencia two taps away from any page; no reader's text under 12 px; filters in a
 * sheet that comes up from the bottom; En vivo a filter of Partidos whose board keeps its address; the desk's top bar
 * with the same groups; the pages of A4 to A14 in the tour of widths.
 */
import { expect, test, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { assertClean, getJson, L, note, sendJson, settle, smallTargets, watch } from "./support";
import { ellipsized, lengthenNames, splitWords } from "./textfit";

const PAGES = [
  "/home",
  "/matches",
  "/live",
  "/picks",
  "/parlays",
  "/odds",
  "/my-picks",
  "/profile",
  "/help",
  // the pages of A3, A4 and A12 the reader reaches from «Más» or a footer (plan UX, A15)
  "/help/glossary",
  "/transparency",
  "/legal/terms",
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

// One test per width, not one loop over all of them: a browser tab that loads forty-odd pages in a row keeps
// every page's decoded fonts and images in shared memory until it closes (about 300 MB per page load in headless
// Chromium) and a small CI machine or a laptop's sandbox ends with "page crashed". A test per width gets a fresh
// tab, tells which width broke, and runs on its own worker.
/** The labels of the tab bar, with their size: five cells, 12 px each (plan UX, A15). */
async function tabLabels(page: Page): Promise<Array<{ text: string; size: number }>> {
  return page.$$eval('[data-testid="tab-label"]', (els) =>
    els
      .filter((e) => e.getBoundingClientRect().width > 0)
      .map((e) => ({ text: e.textContent ?? "", size: parseFloat(getComputedStyle(e).fontSize) })),
  );
}

/**
 * A reader's text under 12 px (plan UX, section 36). Not text to read, so not counted: a pictogram (a logo's initials,
 * aria-hidden), a diagram (the lineup pitch, role="img") and the logo's own tagline.
 */
async function smallText(page: Page, scope = "body"): Promise<string[]> {
  return page.evaluate((root) => {
    const out: string[] = [];
    const container = document.querySelector(root);
    if (!container) return out;
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const seen = new Set<Element>();
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = (n.textContent ?? "").trim();
      const el = n.parentElement;
      if (!text || !el || seen.has(el)) continue;
      seen.add(el);
      const r = el.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) continue;
      let skip = false;
      for (let p: Element | null = el; p; p = p.parentElement) {
        const ps = getComputedStyle(p);
        if (ps.display === "none" || ps.visibility === "hidden" || Number(ps.opacity) === 0)
          skip = true;
        if (
          p.getAttribute("aria-hidden") === "true" ||
          p.getAttribute("role") === "img" ||
          p.hasAttribute("data-brand-tagline")
        )
          skip = true;
        if (skip) break;
      }
      if (skip) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < 11.95) out.push(`${size}px «${text.slice(0, 40)}»`);
    }
    return out;
  }, scope);
}

for (const width of PHONES) {
  test(`every product page fits a ${width} px phone, with the whole tab bar`, async ({
    context,
  }) => {
    test.setTimeout(180_000);
    for (const path of PAGES) {
      // A tab of its own for each page (see «One test per width» above): twelve pages in one tab ran Chromium out of
      // memory («page crashed») once A15 added the glossary, transparency and the legal texts to the tour.
      const page = await context.newPage();
      const w = watch(page);
      await page.setViewportSize({ width, height: width < 360 ? 568 : 844 });
      await page.goto(path);
      await settle(page);
      await expect(page.getByTestId("tab-home"), `the tab bar at ${width} px`).toBeVisible();
      expect(await cutLabels(page), `tab bar labels cut at ${width} px on ${path}`).toEqual([]);
      // Plan UX, A15: five cells - Inicio, Partidos, Picks, Mis picks and «Más» -, every label 12 px or more.
      const labels = await tabLabels(page);
      expect(
        labels.map((l) => l.text),
        `the five destinations at ${width} px on ${path}`,
      ).toEqual([L.es.nav.home, L.es.nav.matches, L.es.nav.picks, L.es.nav.myPicks, L.es.nav.more]);
      expect(
        labels.filter((l) => l.size < 11.95),
        `tab labels under 12 px at ${width} px`,
      ).toEqual([]);
      expect(await smallText(page), `text under 12 px at ${width} px on ${path}`).toEqual([]);
      await assertClean(page, w);
      await page.close();
    }
  });
}

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
  // The Match Center's summary: the form beside its chips and the standings table cut "Zorya Luh…" at 320 px.
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    "/api/v1/matches?limit=3&order=desc",
  );
  for (const { id } of body.data ?? []) {
    await page.goto(`/matches/${id}`);
    await settle(page);
    expect(await cutNames(page), `team names cut on /matches/${id}`).toEqual([]);
    await assertClean(page, w);
  }
});

// Between 640 and 767 px - a phone held sideways, a folding phone, the narrowest browser window of a laptop - a match
// row's line has under 30 rem, so its teams go one per line as on a phone (UX-094; UX-076 wrapped them there), and a
// name is cut with an ellipsis only where its side has 240 px. A test per width, for the reason given above.
for (const width of [640, 658, 700, 767]) {
  test(`team names are whole in the match rows of a ${width} px window`, async ({ page }) => {
    test.setTimeout(120_000);
    const w = watch(page);
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/matches", "/live"]) {
      await page.goto(path);
      await settle(page);
      expect(await cutNames(page), `team names cut on ${path} at ${width} px`).toEqual([]);
      await assertClean(page, w);
    }
  });
}

// No word broken between its letters (mobile UX plan, UX-094), with production's long names: a row squeezed by the odds,
// a state or the bookmakers beside it left a team 66 px on a 320 px phone («Gana Sandefjord» a few letters a line in
// Mis parlays, «Berkhamsted» in two halves in Partidos) and 114 px a side at 640 px («Mönchengladbach» cut in two). The
// QA data's names are shorter than production's, so the page gets long real ones before it is measured. The ten widths
// of the plan, a test per width for the reason given above.
for (const width of [320, 360, 375, 390, 430, 600, 640, 768, 820, 1024]) {
  test(`no word is broken between its letters at ${width} px, even with long team names`, async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const w = watch(page);
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/home", "/matches", "/live", "/picks", "/parlays", "/my-picks"]) {
      await page.goto(path);
      await settle(page);
      expect(await splitWords(page), `${path} at ${width} px, as served`).toEqual([]);
      await lengthenNames(page);
      expect(await splitWords(page), `${path} at ${width} px, long names`).toEqual([]);
      await assertClean(page, w);
    }
  });
}

// Nothing a reader needs cut with «…» (mobile UX plan, UX-095): a section's title («Todas las selecciones que cumplen
// la regla» on a 320 px phone), the bookmaker with the best price in Cuotas («William Hill · 9 ca…» up to 390 px) and
// the logo's tagline. The ten widths of the plan, a test per width.
for (const width of [320, 360, 375, 390, 430, 600, 640, 768, 820, 1024]) {
  test(`titles, bookmakers and the logo are whole at ${width} px`, async ({ page }) => {
    test.setTimeout(150_000);
    const w = watch(page);
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/home", "/picks", "/odds", "/parlays", "/my-picks"]) {
      await page.goto(path);
      await settle(page);
      expect(await ellipsized(page, "main h2"), `${path}: a title cut at ${width} px`).toEqual([]);
      expect(
        await ellipsized(page, '[data-testid="explorer-price"]'),
        `${path}: a bookmaker cut at ${width} px`,
      ).toEqual([]);
      expect(await ellipsized(page, "header"), `${path}: the top bar cut at ${width} px`).toEqual(
        [],
      );
      await assertClean(page, w);
    }
  });
}

// Tablets in both orientations and a phone held sideways - a test per screen, for the reason given above.
const SCREENS: Array<[number, number]> = [
  [768, 1024],
  [820, 1180],
  [1024, 1366],
  [1024, 768],
  [1180, 820],
  [844, 390],
];
for (const [width, height] of SCREENS) {
  test(`every product page fits a ${width} x ${height} screen`, async ({ context }) => {
    test.setTimeout(150_000);
    for (const path of PAGES) {
      // a tab of its own for each page, as in the phones' tour: a tablet's larger screen holds even more of each page
      const page = await context.newPage();
      const w = watch(page);
      await page.setViewportSize({ width, height });
      await page.goto(path);
      await settle(page);
      await assertClean(page, w);
      await page.close();
    }
  });
}

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

// The five phone widths of the plan (UX, section 36; A1 asks 44 px on all of them).
for (const width of [320, 360, 390, 412, 430]) {
  test(`controls answer a finger: 44 x 44 px on a ${width} px touch phone`, async ({ context }) => {
    test.setTimeout(150_000);
    for (const path of PAGES) {
      // a tab of its own for each page, as in the tour above
      const page = await context.newPage();
      const w = watch(page);
      await page.setViewportSize({ width, height: 844 });
      await page.goto(path);
      await settle(page);
      expect(await smallTargets(page), `controls under 44 px at ${width} px on ${path}`).toEqual(
        [],
      );
      await assertClean(page, w);
      await page.close();
    }
  });
}

for (const path of ["/matches", "/odds", "/parlays", "/picks", "/profile"]) {
  test(`form fields never make iOS zoom in (16 px at least on a touch screen): ${path}`, async ({
    page,
  }) => {
    const w = watch(page);
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
  });
}

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

test("a match's Análisis and Postpartido fit every phone width and the tablets, the tabs in a finger's reach", async ({
  page,
}) => {
  // Plan UX, A9: «RESPONSIVE: Inicio y partido en los cinco anchos y en tablet» - Inicio is in the tour above.
  test.setTimeout(240_000);
  const after = new Date().toISOString();
  const upcoming = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=scheduled&order=asc&limit=1&kickoff_after=${encodeURIComponent(after)}`,
  );
  const finished = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    "/api/v1/matches?status=finished&order=desc&limit=1",
  );
  const paths = [
    upcoming.body.data[0] ? `/matches/${upcoming.body.data[0].id}?s=analisis` : null,
    finished.body.data[0] ? `/matches/${finished.body.data[0].id}` : null,
  ].filter((x): x is string => x !== null);
  if (paths.length === 0) {
    note(test.info(), "no match to open");
    return;
  }
  for (const width of [...PHONES, 768, 1024]) {
    // A fresh tab per width (see «One test per width» above): sixteen match pages loaded in one tab kept their decoded
    // fonts and images until it closed, and the test machine's memory limit ended the browser («page crashed»).
    const tab = await page.context().newPage();
    const w = watch(tab);
    await tab.setViewportSize({ width, height: width >= 768 ? 1024 : 800 });
    for (const path of paths) {
      await tab.goto(path);
      await settle(tab);
      const sideways = await tab.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(sideways, `${path} at ${width} px scrolls sideways`).toBeLessThanOrEqual(1);
      expect(await smallTargets(tab, '[role="tablist"]'), `${path} at ${width} px: tabs`).toEqual(
        [],
      );
    }
    await assertClean(tab, w);
    await tab.close();
  }
});

test("a match's Noticias at every phone width: cards stacked, the status in words, the link in a finger's reach", async ({
  page,
}) => {
  // Plan UX, A10: «RESPONSIVE: tarjetas a 320 px» and «ACCESSIBILITY: el estado se lee sin depender del color».
  test.setTimeout(180_000);
  const w = watch(page);
  const today = await getJson<{ data: { matches: { data: Array<{ fixture_id: number }> } } }>(
    page.request,
    "/api/v1/today",
  );
  let id: number | null = null;
  for (const m of today.body.data.matches.data) {
    const r = await getJson<{ status: string }>(
      page.request,
      `/api/v1/matches/${m.fixture_id}/news`,
    );
    if (r.body.status === "ok") {
      id = m.fixture_id;
      break;
    }
  }
  if (id === null) {
    note(test.info(), "no match with news on this database");
    return;
  }
  const labels = Object.values(L.es.match.news.status).map((s) => s.label);
  for (const width of PHONES) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/matches/${id}?s=noticias`);
    await settle(page);
    const cards = page.getByTestId("news-card");
    await expect(cards.first()).toBeVisible();
    const closed = page.locator('[data-testid="match-news"] details:not([open]) > summary');
    while ((await closed.count()) > 0) await closed.first().click();
    const sideways = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(sideways, `Noticias at ${width} px scrolls sideways`).toBeLessThanOrEqual(1);
    const wider = await cards.evaluateAll(
      (els, vw) => els.filter((e) => e.getBoundingClientRect().right > vw + 1).length,
      width,
    );
    expect(wider, `cards wider than ${width} px`).toBe(0);
    expect(await smallTargets(page, '[data-testid="match-news"]'), `${width} px`).toEqual([]);
    for (const text of await page.getByTestId("news-status").allInnerTexts()) {
      expect(
        labels.some((label) => text.trim().startsWith(label)),
        `the status is written, not only coloured: ${text}`,
      ).toBe(true);
    }
  }
  await assertClean(page, w);
});

test("a match's chronicle (A11, UX-025) at every phone width: the lead first, one flowing paragraph per section, nothing sideways", async ({
  page,
}) => {
  // Plan UX, A11 and UX-025: a text read from top to bottom on a phone, no folds, no horizontal scroll at 320 px.
  test.setTimeout(180_000);
  const w = watch(page);
  const after = new Date().toISOString();
  const upcoming = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=scheduled&order=asc&limit=20&kickoff_after=${encodeURIComponent(after)}`,
  );
  let id: number | null = null;
  for (const m of upcoming.body.data) {
    const r = await getJson<{ data: { narrative?: unknown } | null }>(
      page.request,
      `/api/v1/matches/${m.id}/reading`,
    );
    if (r.body.data?.narrative) {
      id = m.id;
      break;
    }
  }
  if (id === null) {
    note(test.info(), "no chronicle on this database");
    return;
  }
  for (const width of PHONES) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`/matches/${id}?s=analisis`);
    await settle(page);
    const block = page.getByTestId("reading-narrative");
    await expect(block).toBeVisible();
    const first = await block
      .locator('[data-testid^="narrative-section-"]')
      .first()
      .getAttribute("data-testid");
    expect(first, `${width} px: the lead first`).toBe("narrative-section-summary");
    expect(await block.locator("details").count(), `${width} px: nothing folds`).toBe(0);
    const sideways = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(sideways, `the chronicle at ${width} px scrolls sideways`).toBeLessThanOrEqual(1);
    expect(await smallTargets(page, '[data-testid="reading-narrative"]'), `${width} px`).toEqual(
      [],
    );
  }
  await assertClean(page, w);
});

test("«Cómo le va a PrediGol» (A12) at every phone width: the blocks stacked as cards, each figure with its n, the list of days under a 44 px fold, nothing sideways", async ({
  page,
}) => {
  // Plan UX, A12: «MÓVIL: bloques en tarjetas con la cifra y su n juntas»; «RESPONSIVE: tablas convertidas en tarjetas a 320 px».
  test.setTimeout(180_000);
  const w = watch(page);
  const { body } = await getJson<{ status: string }>(page.request, "/api/v1/transparency");
  if (body.status !== "ok") {
    note(test.info(), "the page is not open to readers on this database");
    return;
  }
  for (const width of PHONES) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/transparency");
    await settle(page);
    await expect(page.getByTestId("transparency-body")).toBeVisible();
    // the three periods one under the other: a card per period, never a table squeezed sideways
    const tops = await page
      .locator('[data-testid^="transparency-period-"]')
      .evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
    tops
      .slice(1)
      .forEach((top, i) =>
        expect(top, `${width} px: period ${i + 2} under the one before`).toBeGreaterThan(
          tops[i] ?? 0,
        ),
      );
    const list = page.getByTestId("transparency-day-list");
    if ((await list.count()) > 0) {
      const summary = list.locator("summary");
      expect(
        (await summary.boundingBox())!.height,
        `${width} px: the days' fold under a finger`,
      ).toBeGreaterThanOrEqual(43.5);
      await summary.click();
    }
    // plan de cierre UX, 1.5: the picks one by one stacked as cards, «ver más» and the history's fold under a finger
    const rows = page.getByTestId("published-pick");
    if ((await rows.count()) > 1) {
      const tops = await rows.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
      tops
        .slice(1)
        .forEach((top, i) =>
          expect(top, `${width} px: pick ${i + 2} under the one before`).toBeGreaterThan(
            tops[i] ?? 0,
          ),
        );
    }
    const folds = page.getByTestId("transparency-changes-more");
    if ((await folds.count()) > 0) {
      expect(
        (await folds.locator("summary").boundingBox())!.height,
        `${width} px: the history's fold under a finger`,
      ).toBeGreaterThanOrEqual(43.5);
      await folds.locator("summary").click();
    }
    const sideways = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(sideways, `the page at ${width} px scrolls sideways`).toBeLessThanOrEqual(1);
    expect(await smallTargets(page, '[data-testid="transparency-page"]'), `${width} px`).toEqual(
      [],
    );
  }
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
  // Plan UX, A1 (F53): the cleared slip can be put back for five seconds - its button within a thumb's reach -
  // and then the offer goes.
  await expect(sheet.getByTestId("slip-undo")).toBeVisible();
  expect(
    await smallTargets(page, '[data-testid="slip-undo"]'),
    "the undo button under 44 px",
  ).toEqual([]);
  await sheet.getByTestId("slip-undo-button").click();
  await expect(sheet.getByTestId("slip-leg")).toHaveCount(2);
  await sheet.getByTestId("slip-clear").click();
  await expect(sheet.getByTestId("slip-undo")).toBeVisible();
  await expect(sheet.getByTestId("slip-undo")).toHaveCount(0, { timeout: 8_000 });
  await expect(sheet.getByTestId("slip-leg")).toHaveCount(0);
  await assertClean(page, w);
});

test("the update notice floats above the tab bar and the parlay button, its buttons in a finger's reach", async ({
  page,
}) => {
  // Plan UX, A1 (F33): the "new version" notice sat on the tab bar. It is raised by the service worker when a new
  // version waits (src/lib/pwa.ts); here the same event is sent by hand.
  const w = watch(page);
  // A leg in the slip, so the parlay button shows too (the slip lives in this tab's session storage).
  await page.addInitScript(() =>
    window.sessionStorage.setItem(
      "predigol.slip",
      JSON.stringify([
        {
          fixture_id: 999_999,
          market_key: "1X2",
          selection: "Home",
          line: "0",
          home: "Local",
          away: "Visitante",
          kickoff_at: "2099-01-01T18:00:00Z",
          odds: "2.00",
          bookmaker: null,
        },
      ]),
    ),
  );
  for (const [width, height] of [
    [320, 700],
    [390, 844],
    [844, 390],
  ] as const) {
    await page.setViewportSize({ width, height });
    await page.goto("/home");
    await settle(page);
    await page.evaluate(() =>
      window.dispatchEvent(
        new CustomEvent("predigol:update-ready", { detail: { postMessage: () => undefined } }),
      ),
    );
    const notice = page.getByTestId("update-toast");
    await expect(notice).toBeVisible();
    const box = await notice.boundingBox();
    const bar = await page.getByRole("navigation", { name: L.es.nav.mainNavigation }).boundingBox();
    expect(box && bar, `notice and tab bar at ${width}x${height}`).toBeTruthy();
    if (!box || !bar) return;
    expect(
      box.y + box.height,
      `the notice ends above the tab bar at ${width}x${height}`,
    ).toBeLessThanOrEqual(bar.y);
    const slip = await page.getByTestId("slip-open").boundingBox();
    expect(slip, "the parlay button shows").toBeTruthy();
    if (slip) {
      const apart =
        box.y + box.height <= slip.y ||
        slip.y + slip.height <= box.y ||
        box.x + box.width <= slip.x ||
        slip.x + slip.width <= box.x;
      expect(apart, `the notice covers the parlay button at ${width}x${height}`).toBe(true);
    }
    expect(await smallTargets(page, '[data-testid="update-toast"]'), "notice buttons").toEqual([]);
    await page.getByTestId("update-later").click();
    await expect(notice).toHaveCount(0);
  }
  await assertClean(page, w);
});

test("a figure's help opens with a tap inside a card's link, and that tap does not open the match", async ({
  page,
}) => {
  // Plan UX, A1 (F16): a card is one link, and the help on its figures could not be read with a finger - a tap
  // followed the link. A [data-hint] now shows its help, and only the rest of the card opens the match.
  // Plan UX, A9: Inicio's rows say why they show («Sugerida») - a figure's help inside the row's link.
  const w = watch(page);
  await page.goto("/home");
  await settle(page);
  const badge = page.getByTestId("today-why").first();
  if ((await badge.count()) === 0) {
    note(test.info(), "no match of the suggested leagues on Inicio");
    return;
  }
  await badge.tap();
  await expect(page.getByTestId("title-tap")).toHaveText(L.es.home.today.whyHelp);
  await page.waitForTimeout(800); // the click that followed the tap was the link's: it must not navigate
  await expect(page).toHaveURL(/\/home$/);
  await page.getByTestId("today-row").first().getByTestId("matchup").tap();
  await expect(page).toHaveURL(/\/matches\/\d+/);
  await assertClean(page, w);
});

test("Mis picks with an open pick, its confirmation, and a match's markets: 44 px at the five phone widths", async ({
  page,
}) => {
  // Plan UX, A1 (F33): Mis picks had 32 px buttons (your price, remove) and the line selector of a match's markets
  // 32 px; they show only with an open saved pick and a priced match, so the check makes one and removes it.
  test.setTimeout(180_000);
  const w = watch(page);
  const { body } = await getJson<{
    data: { fixtures: Array<{ fixture_id: number; kickoff_at: string }> };
  }>(page.request, "/api/v1/odds/best?hours=72&market=1X2");
  const soon = Date.now() + 30 * 60_000;
  const fixture = body.data.fixtures.find((f) => Date.parse(f.kickoff_at) > soon);
  if (!fixture) {
    note(test.info(), "no upcoming match with a 1X2 price");
    return;
  }
  const open = await getJson<{ data: Array<{ id: number; match: { fixture_id: number } }> }>(
    page.request,
    "/api/v1/me/picks?status=open",
  );
  for (const p of open.body.data.filter((x) => x.match.fixture_id === fixture.fixture_id)) {
    await sendJson(page.request, "DELETE", `/api/v1/me/picks/${p.id}`);
  }
  const saved = await sendJson<{ data: { id: number } }>(page.request, "POST", "/api/v1/me/picks", {
    fixture_id: fixture.fixture_id,
    market_key: "1X2",
    selection: "Home",
  });
  expect(saved.status, "the pick is saved").toBe(201);
  try {
    for (const width of [320, 360, 390, 412, 430]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto("/my-picks");
      await settle(page);
      const row = page.locator(
        `[data-testid="saved-pick"][data-fixture-id="${fixture.fixture_id}"]`,
      );
      await expect(row).toBeVisible();
      expect(await smallTargets(page, "main"), `Mis picks at ${width} px`).toEqual([]);
      await row.getByTestId("saved-pick-remove").click();
      const dialog = page.getByTestId("confirm-remove-pick");
      await expect(dialog).toBeVisible();
      // Measured once it has finished opening: during its zoom-in the buttons are drawn at 95 % of their size.
      await dialog.evaluate((el) =>
        Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)),
      );
      expect(
        await smallTargets(page, '[data-testid="confirm-remove-pick"]'),
        `the confirmation at ${width} px`,
      ).toEqual([]);
      await page.getByTestId("confirm-remove-pick-cancel").click();
      await page.goto(`/matches/${fixture.fixture_id}`);
      await settle(page);
      await page.getByRole("tab", { name: L.es.match.tabs.markets }).click();
      await settle(page);
      expect(await smallTargets(page, "main"), `a match's markets at ${width} px`).toEqual([]);
    }
  } finally {
    await sendJson(page.request, "DELETE", `/api/v1/me/picks/${saved.body.data.id}`);
  }
  await assertClean(page, w);
});

// ---------------------------------------------------------------------------------------------------------------------
// Plan UX, A15 · navegación móvil y PWA base (gate G11)

/** «Más» from the bar, open: its sheet under the thumb, inside the screen and clear of the notch and the home bar. */
async function openMore(page: Page) {
  await page.getByTestId("tab-more").click();
  const sheet = page.getByTestId("more-sheet");
  await expect(sheet).toBeVisible();
  // measured once it has finished coming up: during its slide its rows are below the screen
  await sheet.evaluate((el) =>
    Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)),
  );
  return sheet;
}

for (const width of [320, 390]) {
  test(`«Más» on a ${width} px phone: Perfil, Ayuda and Transparencia two taps away from any page, every row in a finger's reach`, async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const w = watch(page);
    await page.setViewportSize({ width, height: width < 360 ? 568 : 844 });
    const { body: me } = await getJson<{ transparency?: boolean }>(page.request, "/api/v1/auth/me");
    const targets: Array<[string, string, RegExp]> = [
      ["/odds", "more-profile", /\/profile$/],
      ["/matches", "more-help", /\/help$/],
      ["/my-picks", "more-glossary", /\/help\/glossary$/],
      ["/home", "more-parlays", /\/parlays$/],
      ["/picks", "more-odds", /\/odds$/],
    ];
    if (me.transparency) targets.push(["/live", "more-transparency", /\/transparency$/]);
    else
      note(
        test.info(),
        "«Cómo le va a PrediGol» is not open to readers on this database: not offered",
      );
    for (const [from, row, to] of targets) {
      await page.goto(from);
      await settle(page);
      const sheet = await openMore(page);
      await expect(page.getByTestId("tab-more")).toHaveAttribute("aria-expanded", "true");
      const box = await sheet.boundingBox();
      const vh = page.viewportSize()?.height ?? 0;
      expect(
        box && Math.abs(box.y + box.height - vh) <= 1,
        "the sheet comes up from the bottom",
      ).toBe(true);
      expect(
        await smallTargets(page, '[data-testid="more-sheet"]'),
        `«Más» at ${width} px`,
      ).toEqual([]);
      expect(await smallText(page, '[data-testid="more-sheet"]'), "«Más» text").toEqual([]);
      // tap 1: «Más»; tap 2: the row
      await sheet.getByTestId(row).click();
      await expect(page).toHaveURL(to);
      await expect(page.getByTestId("more-sheet")).toHaveCount(0);
      await settle(page);
      // the page of «Más» lights its cell
      await expect(page.getByTestId("tab-more")).toHaveAttribute("data-active", "");
    }
    // Transparencia waits for the owner: never offered while closed
    await page.goto("/home");
    await settle(page);
    // the language left the top bar (plan maestro UX/UI 2026, wave 3): «Más» has it, in a row of its own
    await expect(page.locator("header").getByTestId("lang-es")).toHaveCount(0);
    const sheet = await openMore(page);
    await expect(sheet.getByTestId("more-transparency")).toHaveCount(me.transparency ? 1 : 0);
    await expect(sheet.getByTestId("more-language").getByTestId("lang-es")).toBeVisible();
    await expect(sheet.getByTestId("more-language").getByTestId("lang-en")).toBeVisible();
    // the install steps (a browser tab, not the installed app), then «Cerrar sesión» last
    await sheet.getByTestId("more-install-toggle").click();
    await expect(sheet.getByTestId("more-install-steps")).toBeVisible();
    // this device's steps first: an iPhone (WebKit's project) or an Android (Chromium's)
    const ua = await page.evaluate(() => navigator.userAgent);
    await expect(
      sheet.getByTestId("more-install-steps").locator("[data-platform]").first(),
    ).toHaveAttribute("data-platform", /iPhone|iPad/.test(ua) ? "ios" : "android");
    await expect(sheet.getByTestId("more-sign-out")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("more-sheet")).toHaveCount(0);
    await expect(page.getByTestId("tab-more")).toHaveAttribute("aria-expanded", "false");
    // with a keyboard: «Más» opens with Enter, the focus goes into the sheet and comes back to «Más» when it closes
    await page.getByTestId("tab-more").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("more-sheet")).toBeVisible();
    expect(
      await page.evaluate(() => !!document.activeElement?.closest('[data-testid="more-sheet"]')),
      "the focus is inside the sheet",
    ).toBe(true);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("more-sheet")).toHaveCount(0);
    await expect(page.getByTestId("tab-more")).toBeFocused();
    await assertClean(page, w);
  });
}

test("the bar's cells name themselves and the page's own says so; En vivo is Partidos' and its board keeps its address", async ({
  page,
}) => {
  const w = watch(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [path, cell] of [
    ["/home", "tab-home"],
    ["/matches", "tab-matches"],
    ["/live", "tab-matches"],
    ["/picks", "tab-picks"],
    ["/my-picks", "tab-my-picks"],
  ] as const) {
    await page.goto(path);
    await settle(page);
    await expect(page.getByTestId(cell), `${path} lights ${cell}`).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.locator('nav [aria-current="page"]:visible')).toHaveCount(1);
  }
  // the board is at its address, with the way back to Partidos; the bar has no «En vivo» of its own
  await page.goto("/live");
  await settle(page);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(L.es.nav.live);
  await expect(page.getByTestId("tab-live")).toHaveCount(0);
  await page.getByTestId("live-back").click();
  await expect(page).toHaveURL(/\/matches$/);
  // En vivo, a filter of Partidos at one tap, in view at once
  await settle(page);
  const chips = page.getByTestId("status-chips");
  const live = chips.getByRole("button", { name: new RegExp(`^${L.es.matches.status.live}`) });
  await expect(live).toBeInViewport();
  await live.click();
  await expect(live).toHaveAttribute("aria-pressed", "true");
  const { body } = await getJson<{ data: { matches: Array<unknown> } }>(
    page.request,
    "/api/v1/live",
  );
  if (body.data.matches.length > 0) {
    // live now: the board is one tap further
    await expect(page.getByTestId("matches-live-board")).toBeVisible();
  } else {
    note(test.info(), "no match in play on this database: the board's link is not offered");
    await expect(page.getByTestId("matches-live-board")).toHaveCount(0);
  }
  // back to «Todos» for the next test of this account
  await chips.getByRole("button", { name: new RegExp(`^${L.es.matches.status.all}`) }).click();
  await assertClean(page, w);
});

test("the filters come up from the bottom on a 320 px phone: «Filtros» says how many are on, «Ver N» under the thumb, «Borrar filtros»", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const w = watch(page);
  await page.setViewportSize({ width: 320, height: 640 });
  for (const [path, base, field, show] of [
    ["/matches", "matches-filters", "match-search", L.es.matches.filters.show_other],
    ["/odds", "odds-filters", "odds-search", L.es.odds.filters.show_other],
  ] as const) {
    await page.goto(path);
    await settle(page);
    const open = page.getByTestId(`${base}-open`);
    await expect(open).toBeVisible();
    await expect(page.getByTestId(`${base}-count`)).toHaveCount(0);
    expect(await smallTargets(page, "main"), `${path}: the page's controls`).toEqual([]);
    await open.click();
    const sheet = page.getByTestId(`${base}-sheet`);
    await expect(sheet).toBeVisible();
    await sheet.evaluate((el) =>
      Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)),
    );
    const box = await sheet.boundingBox();
    expect(box && Math.abs(box.y + box.height - 640) <= 1, `${path}: from the bottom`).toBe(true);
    expect(await smallTargets(page, `[data-testid="${base}-sheet"]`), `${path}: the sheet`).toEqual(
      [],
    );
    expect(await smallText(page, `[data-testid="${base}-sheet"]`), `${path}: its text`).toEqual([]);
    // fields of 16 px: iOS never zooms in
    const sizes = await sheet
      .locator("input, select")
      .evaluateAll((els) => els.map((e) => parseFloat(getComputedStyle(e).fontSize)));
    expect(
      sizes.filter((x) => x < 16),
      `${path}: fields under 16 px`,
    ).toEqual([]);
    // a filter on: the list behind changes at once, the button counts it, «Ver N» closes
    await sheet.getByTestId(field).fill("zzzz-no-team");
    const showButton = sheet.getByTestId(`${base}-show`);
    await expect(showButton).toHaveText(
      new RegExp(show.replace("{count}", "0").replace(/[()]/g, ".")),
    );
    await expect(showButton).toBeInViewport();
    await showButton.click();
    await expect(sheet).toHaveCount(0);
    await expect(page.getByTestId(`${base}-count`)).toHaveText("1");
    // and cleared from the sheet
    await page.getByTestId(`${base}-open`).click();
    await page.getByTestId(`${base}-reset`).click();
    await expect(page.getByTestId(`${base}-reset`)).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId(`${base}-count`)).toHaveCount(0);
  }
  await assertClean(page, w);
});

test("from 1024 px the desk's top bar has the same groups and the filters sit in the page; under it, the phone's bar", async ({
  page,
}) => {
  const w = watch(page);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/matches");
  await settle(page);
  const top = page.getByRole("navigation", { name: L.es.nav.mainNavigation }).first();
  for (const id of ["nav-home", "nav-matches", "nav-picks", "nav-my-picks", "nav-more"]) {
    await expect(top.getByTestId(id)).toBeVisible();
  }
  await expect(page.getByTestId("tab-home")).toBeHidden();
  await expect(page.getByTestId("matches-facets")).toBeVisible();
  await expect(page.getByTestId("matches-filters-open")).toBeHidden();
  await top.getByTestId("nav-more").click();
  const menu = page.getByTestId("nav-more-menu");
  await expect(menu.getByTestId("nav-more-odds")).toBeVisible();
  await menu.getByTestId("nav-more-odds").click();
  await expect(page).toHaveURL(/\/odds$/);
  await settle(page);
  await page.setViewportSize({ width: 768, height: 1024 });
  await expect(page.getByTestId("tab-more")).toBeVisible();
  await expect(page.getByTestId("tab-more")).toHaveAttribute("data-active", "");
  await expect(page.getByTestId("odds-filters-open")).toBeVisible();
  await assertClean(page, w);
});

/** Every module of the Admin Console (src/routes/admin.*). */
const ADMIN_PAGES = [
  "/admin/overview",
  "/admin/picks",
  "/admin/users",
  "/admin/operation",
  "/admin/learning",
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

/**
 * Operación and Aprendizaje keep their sections behind tabs, and a tab is an address: each one has to hold on a phone, not only the first one
 * the page opens on (plan F13: the five pages that talked about the AI are these two).
 */
const AI_PAGES_PLACES = [
  "/admin/operation",
  "/admin/operation#tab=decisions",
  "/admin/operation#tab=match",
  "/admin/operation#tab=ai",
  "/admin/operation#tab=ai&view=research",
  "/admin/operation#tab=ai&view=reviews",
  "/admin/operation#tab=ai&view=evidence",
  "/admin/operation#tab=ai&view=sources",
  "/admin/operation#tab=agents",
  "/admin/operation#tab=costs",
  "/admin/operation#tab=runs",
  "/admin/learning",
  "/admin/learning#tab=learned",
  "/admin/learning#tab=postmortems",
  "/admin/learning#tab=memory",
  "/admin/learning#tab=memory&view=matches",
  "/admin/learning#tab=memory&view=notes",
  "/admin/learning#tab=memory&view=findings",
  "/admin/learning#tab=experiments",
  "/admin/learning#tab=calibration",
  "/admin/learning#tab=markets",
  "/admin/learning#tab=shadow",
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

  // Every tab and view of the two pages, each by its address: nothing scrolls sideways and every control is within a finger's reach.
  test("every tab and view of Operación and Aprendizaje holds at 320 and 390 px and answers a finger", async ({
    context,
  }) => {
    test.setTimeout(480_000);
    for (const width of [320, 390]) {
      for (const path of AI_PAGES_PLACES) {
        const page = await context.newPage();
        const w = watch(page);
        await page.setViewportSize({ width, height: 800 });
        await page.goto(path);
        await settle(page);
        expect(await smallTargets(page, "main"), `controls at ${width} px on ${path}`).toEqual([]);
        await assertClean(page, w);
        await page.close();
      }
    }
  });
});

test.describe("the Admin Console on a touch tablet", () => {
  test.use({ storageState: statePath("admin"), locale: "en-GB" });

  test("no page scrolls sideways; the header and the menu answer a finger", async ({ context }) => {
    test.setTimeout(240_000);
    for (const [width, height] of [
      [768, 1024],
      [1024, 768],
      [1180, 820],
    ] as const) {
      for (const path of ["/admin/overview", "/admin/picks", "/admin/users", "/admin/operation"]) {
        // A page of its own for each load (as in the phone test): a dozen loads of the dev server's unbundled modules in one
        // page run Chromium out of resources (ERR_INSUFFICIENT_RESOURCES), and Operación, which holds the views of five pages, is the heaviest.
        const page = await context.newPage();
        const w = watch(page);
        await page.setViewportSize({ width, height });
        await page.goto(path);
        await settle(page);
        expect(
          await smallTargets(page, "header"),
          `header controls at ${width} px on ${path}`,
        ).toEqual([]);
        await assertClean(page, w);
        await page.close();
      }
    }
  });

  // The overview's panel links ("Live" was 21 px wide), the explained "—" (cut to 7 x 16 px by a truncating value
  // cell) and the definitions in table headers (38 px under the table's scroll box) were out of a finger's reach.
  test("the modules' own controls answer a finger, not only the header's", async ({ context }) => {
    test.setTimeout(300_000);
    for (const [width, height] of [
      [768, 1024],
      [1024, 768],
    ] as const) {
      for (const path of [
        "/admin/overview",
        "/admin/picks",
        "/admin/models",
        "/admin/system",
        "/admin/operation",
        "/admin/operation#tab=match",
        "/admin/learning",
        "/admin/learning#tab=experiments",
      ]) {
        // A page of its own for each load (see the test above).
        const page = await context.newPage();
        const w = watch(page);
        await page.setViewportSize({ width, height });
        await page.goto(path);
        await settle(page);
        expect(await smallTargets(page, "main"), `controls at ${width} px on ${path}`).toEqual([]);
        await assertClean(page, w);
        await page.close();
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
