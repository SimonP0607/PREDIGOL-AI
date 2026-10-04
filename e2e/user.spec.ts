/**
 * The USER experience, in Spanish (project user-es) and in English (user-en): every
 * destination opens cleanly in the account's language, picks and parlays are only ever
 * qualified (or honestly empty), and nothing of the Admin Console shows.
 */
import { expect, test, type Page } from "@playwright/test";
import { L, assertClean, getJson, note, settle, watch, type Lang, type Watch } from "./support";

interface Section<T> {
  status: string;
  data: T;
  reason: string | null;
}
interface HomeBody {
  source: string;
  top_picks: Section<unknown[]>;
  daily_parlay: { status: string; legs: unknown[] };
  multiday_parlay: { status: string };
  live: Section<unknown[]>;
}

function lang(): Lang {
  return (test.info().project.metadata["lang"] as Lang | undefined) ?? "es";
}

async function open(page: Page, w: Watch, path: string): Promise<void> {
  await page.goto(path);
  await settle(page);
  await assertClean(page, w);
}

test("navigation is the product's six destinations, in the account's language", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/home");
  const nav = page.getByRole("navigation", { name: t.nav.mainNavigation }).first();
  for (const key of ["home", "matches", "live", "picks", "parlays", "odds"] as const) {
    await expect(nav.getByRole("link", { name: t.nav[key], exact: true })).toBeVisible();
  }
  // nothing of the Admin Console
  await expect(page.getByText(t.admin.groups.intelligence, { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("shadow-toggle")).toHaveCount(0);
  await page.getByTestId("account-menu").click();
  await expect(page.getByTestId("go-admin")).toHaveCount(0);
});

test("Home: today, top picks or an honest empty state, the two parlays, live, best odds", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const home = await getJson<{ data: HomeBody }>(page.request, "/api/v1/home");
  expect(home.status).toBe(200);
  expect(home.body.data.source).toBe("qualified");
  await open(page, w, "/home");
  await expect(page.getByTestId("home-date")).toBeVisible();
  await expect(page.getByRole("heading", { name: t.home.picks.title })).toBeVisible();
  if (home.body.data.top_picks.status === "ok") {
    await expect(page.getByTestId("home-top-picks").getByTestId("pick-card").first()).toBeVisible();
  } else {
    await expect(page.getByText(t.markets.reason.no_qualified_picks).first()).toBeVisible();
    note(test.info(), "no qualified pick today: the honest empty state was checked");
  }
  for (const kind of ["daily", "multiday"] as const) {
    const parlay = home.body.data[`${kind}_parlay`];
    const card = page.getByTestId(`home-parlay-${kind}`);
    await expect(card).toBeVisible();
    if (parlay.status === "no_valid_parlay") {
      await expect(card.getByTestId("no-valid-parlay")).toBeVisible();
      await expect(card.getByTestId("parlay-leg")).toHaveCount(0);
    } else {
      await expect(card.getByTestId("parlay-leg").first()).toBeVisible();
    }
  }
  await expect(page.getByRole("heading", { name: t.home.live.title })).toBeVisible();
  await expect(page.getByRole("heading", { name: t.home.best.title })).toBeVisible();
  await expect(page.getByRole("heading", { name: t.home.upcoming.title })).toBeVisible();
});

test("Picks: Top 5 today and the qualified list, never research vocabulary", async ({ page }) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/picks");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.nav.picks);
  await expect(page.getByRole("heading", { name: t.picks.top.title })).toBeVisible();
  const body = await page.locator("main").innerText();
  for (const word of ["shadow", "candidate", "rejected", "decision rule", "payload"]) {
    expect(body.toLowerCase(), `"${word}" on the user's Picks page`).not.toContain(word);
  }
});

test("Parlays: both parlays, valid or honestly absent, and how they are built", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/parlays");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.nav.parlays);
  for (const kind of ["daily", "multiday"] as const) {
    const { body } = await getJson<{ data: { status: string } }>(
      page.request,
      `/api/v1/parlays/${kind}`,
    );
    const card = page.getByTestId(`parlay-card-${kind}`);
    if (body.data.status === "no_valid_parlay") {
      await expect(card.getByText(t.parlays.empty.title)).toBeVisible();
    } else {
      await expect(card.getByTestId("parlay-combined-odds")).toBeVisible();
    }
  }
  await page.getByTestId("parlays-how").locator("summary").click();
  await expect(page.getByText(t.parlays.how.noPadding.title)).toBeVisible();
});

test("Odds: the best-odds board per market", async ({ page }) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/odds");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.nav.odds);
  const tabs = page.getByTestId("odds-market-tabs");
  await tabs.getByRole("tab", { name: t.odds.tabs.OU }).click();
  await settle(page);
  await assertClean(page, w);
  const fixtures = page.getByTestId("odds-fixture");
  if ((await fixtures.count()) === 0) note(test.info(), "no fixture with prices in the window");
  else await expect(fixtures.first().getByTestId("odds-cell").first()).toBeVisible();
});

test("Matches: today in the reader's zone, and a match opens its centre", async ({ page }) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/matches");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.nav.matches);
  const rows = page.getByTestId("match-row");
  if ((await rows.count()) === 0) {
    note(test.info(), "no fixture today");
    return;
  }
  await rows.first().click();
  await expect(page).toHaveURL(/\/matches\/\d+$/);
  await settle(page);
  await expect(page.getByTestId("match-center")).toBeVisible();
  for (const key of ["summary", "stats", "markets", "lineups"] as const) {
    await expect(page.getByRole("tab", { name: t.match.tabs[key] })).toBeVisible();
  }
  await expect(page.getByRole("tab", { name: t.match.tabs.advanced })).toHaveCount(0);
  for (const key of ["stats", "markets", "lineups"] as const) {
    await page.getByRole("tab", { name: t.match.tabs[key] }).click();
    await settle(page);
    await assertClean(page, w);
  }
});

test("A league table in the Match Center says how current it is", async ({ page }) => {
  const w = watch(page);
  const t = L[lang()];
  const after = new Date().toISOString();
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=scheduled&order=asc&limit=30&kickoff_after=${encodeURIComponent(after)}`,
  );
  let id: number | null = null;
  for (const m of body.data) {
    const c = await getJson<{ data: { standings: { data: unknown[] } } | null }>(
      page.request,
      `/api/v1/matches/${m.id}/center`,
    );
    if ((c.body.data?.standings.data.length ?? 0) > 0) {
      id = m.id;
      break;
    }
  }
  if (id === null) {
    note(test.info(), "no upcoming match with a league table among the next 30");
    return;
  }
  await open(page, w, `/matches/${id}`);
  // before kick-off the table is laid out twice (phone column and wide column); read the one shown
  const freshness = page.locator('[data-testid="table-freshness"]:visible').first();
  await expect(freshness).toBeVisible();
  await expect(freshness).toContainText(t.match.standings.updated.split("{")[0]?.trim() ?? "");
});

test("A market without a bookmaker price says why, and never shows a made-up price", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const after = new Date().toISOString();
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=scheduled&order=asc&limit=40&kickoff_after=${encodeURIComponent(after)}`,
  );
  let found: { id: number; market: string; status: string } | null = null;
  for (const m of body.data) {
    const v = await getJson<{
      data: { price_status?: Array<{ market_key: string; status: string }> };
    }>(page.request, `/api/v1/matches/${m.id}`);
    const unpriced = (v.body.data.price_status ?? []).find((p) =>
      ["PRICE_PENDING", "PRICE_UNAVAILABLE", "NOT_COVERED"].includes(p.status),
    );
    if (unpriced) {
      found = { id: m.id, market: unpriced.market_key, status: unpriced.status };
      break;
    }
  }
  if (!found) {
    note(test.info(), "every upcoming match among the next 40 has a price in each core market");
    return;
  }
  await open(page, w, `/matches/${found.id}`);
  const row = page.locator(`[data-testid="price-status-${found.market}"]:visible`).first();
  await expect(row).toBeVisible();
  const reason = t.match.priceStatus[found.status as "PRICE_PENDING"];
  await expect(row).toContainText(reason);
});

test("Live: richest matches first, or an honest empty board", async ({ page }) => {
  const w = watch(page);
  const t = L[lang()];
  const { body } = await getJson<{
    data: { matches: Array<{ completeness: { score: number } | null }> };
  }>(page.request, "/api/v1/live");
  await open(page, w, "/live");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.nav.live);
  const scores = body.data.matches.map((m) => m.completeness?.score ?? 0);
  expect(scores, "the API orders live matches by data completeness").toEqual(
    [...scores].sort((a, b) => b - a),
  );
  if (scores.length === 0) {
    await expect(page.getByText(t.markets.reason.no_live_matches).first()).toBeVisible();
  } else {
    await expect(
      page.locator('[data-testid="live-card"], [data-testid="live-row"]').first(),
    ).toBeVisible();
  }
});

test("Profile shows the account's language and time zone", async ({ page }) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/profile");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.profile.title);
  const tz = lang() === "es" ? "America/Bogota" : "Europe/Madrid";
  await expect(page.getByTestId("current-timezone")).toContainText(tz);
  await expect(page.getByTestId(`profile-lang-${lang()}`)).toHaveAttribute("aria-checked", "true");
});
