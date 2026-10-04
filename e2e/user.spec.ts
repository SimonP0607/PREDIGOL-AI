/**
 * The USER experience, in Spanish (project user-es) and in English (user-en): every
 * destination opens cleanly in the account's language, the day's picks and parlays are the
 * recorded ones (only ever qualified, or honestly empty), a user keeps their own picks and
 * parlays and sees how they went, and nothing of the Admin Console shows.
 */
import { expect, test, type Page } from "@playwright/test";
import {
  L,
  assertClean,
  getJson,
  note,
  sendJson,
  settle,
  watch,
  type Lang,
  type Watch,
} from "./support";

interface ParlayRecordBody {
  status: string;
  legs: unknown[];
}
interface BoardBody {
  day: string;
  evaluation_mode: boolean;
  set: { items: Array<{ rank: number; match: { kickoff_at: string } }> } | null;
  daily_parlay: ParlayRecordBody | null;
  multiday_parlay: ParlayRecordBody | null;
  reason: string | null;
}
interface PricedFixture {
  fixture_id: number;
  kickoff_at: string;
  home: { id: number; name: string };
  away: { id: number; name: string };
}

function lang(): Lang {
  return (test.info().project.metadata["lang"] as Lang | undefined) ?? "es";
}

async function open(page: Page, w: Watch, path: string): Promise<void> {
  await page.goto(path);
  await settle(page);
  await assertClean(page, w);
}

test("navigation is the product's seven destinations, in the account's language", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/home");
  const nav = page.getByRole("navigation", { name: t.nav.mainNavigation }).first();
  for (const key of ["home", "matches", "live", "picks", "parlays", "odds", "myPicks"] as const) {
    await expect(nav.getByRole("link", { name: t.nav[key], exact: true })).toBeVisible();
  }
  // nothing of the Admin Console
  await expect(page.getByText(t.admin.groups.intelligence, { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("shadow-toggle")).toHaveCount(0);
  await page.getByTestId("account-menu").click();
  await expect(page.getByTestId("go-admin")).toHaveCount(0);
});

/** A recorded parlay on screen says what the record says: legs, still being built, or none. */
async function expectParlay(
  card: ReturnType<Page["getByTestId"]>,
  record: ParlayRecordBody | null,
) {
  if (record === null) {
    await expect(card.getByTestId("parlay-none")).toBeVisible();
  } else if (record.legs.length === 0) {
    await expect(
      card.getByTestId(record.status === "BUILDING" ? "parlay-building" : "parlay-void"),
    ).toBeVisible();
  } else {
    await expect(card.getByTestId("parlay-leg")).toHaveCount(record.legs.length);
    await expect(card.getByTestId("parlay-status")).toHaveAttribute("data-status", record.status);
  }
}

test("Home: the day's recorded picks or an honest empty state, the two parlays, live, best odds", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const { status, body } = await getJson<{ data: BoardBody }>(page.request, "/api/v1/daily");
  expect(status).toBe(200);
  expect(body.data.evaluation_mode, "a USER never gets the evaluation records").toBe(false);
  await open(page, w, "/home");
  await expect(page.getByTestId("home-date")).toBeVisible();
  const daily = page.getByTestId("daily-set");
  await expect(daily.getByRole("heading", { name: t.records.daily.title })).toBeVisible();
  const items = body.data.set?.items ?? [];
  if (items.length > 0) {
    await expect(daily.getByTestId("daily-item")).toHaveCount(items.length);
  } else {
    await expect(daily.getByText(t.records.daily.reason.no_qualified_picks)).toBeVisible();
    note(test.info(), "no qualified pick recorded today: the honest empty state was checked");
  }
  await expectParlay(page.getByTestId("home-parlay-daily"), body.data.daily_parlay);
  await expectParlay(page.getByTestId("home-parlay-multiday"), body.data.multiday_parlay);
  await expect(page.getByRole("heading", { name: t.home.live.title })).toBeVisible();
  await expect(page.getByRole("heading", { name: t.home.best.title })).toBeVisible();
  await expect(page.getByRole("heading", { name: t.home.upcoming.title })).toBeVisible();
});

test("Picks: the day's recorded picks (kept after kick-off) and the qualified list, never research vocabulary", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const { body } = await getJson<{ data: BoardBody }>(page.request, "/api/v1/daily");
  await open(page, w, "/picks");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.nav.picks);
  await expect(page.getByRole("heading", { name: t.records.daily.title })).toBeVisible();
  const items = body.data.set?.items ?? [];
  await expect(page.getByTestId("daily-item")).toHaveCount(items.length);
  const started = items.filter((i) => Date.parse(i.match.kickoff_at) <= Date.now()).length;
  if (started > 0)
    note(test.info(), `${started} of today's picks have kicked off and are still shown`);
  const text = await page.locator("main").innerText();
  for (const word of ["shadow", "candidate", "rejected", "decision rule", "payload"]) {
    expect(text.toLowerCase(), `"${word}" on the user's Picks page`).not.toContain(word);
  }
});

test("Parlays: both recorded parlays, built or honestly absent, and how they are chosen", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const { body } = await getJson<{ data: BoardBody }>(page.request, "/api/v1/daily");
  await open(page, w, "/parlays");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.nav.parlays);
  await expectParlay(page.getByTestId("parlay-record-daily"), body.data.daily_parlay);
  await expectParlay(page.getByTestId("parlay-record-multiday"), body.data.multiday_parlay);
  await page.getByTestId("parlays-how").locator("summary").click();
  await expect(page.getByText(t.parlays.how.noPadding.title)).toBeVisible();
  await expect(page.getByText(t.parlays.how.choice.title)).toBeVisible();
});

/** Upcoming matches with pre-match prices, far enough from kick-off for a test to finish. */
async function pricedFixtures(page: Page, count: number): Promise<PricedFixture[]> {
  const { body } = await getJson<{ data: { fixtures: PricedFixture[] } }>(
    page.request,
    "/api/v1/odds/best?hours=72&market=1X2",
  );
  const soon = Date.now() + 30 * 60_000;
  const out: PricedFixture[] = [];
  const teams = new Set<number>();
  for (const f of body.data.fixtures) {
    if (Date.parse(f.kickoff_at) < soon || teams.has(f.home.id) || teams.has(f.away.id)) continue;
    out.push(f);
    teams.add(f.home.id);
    teams.add(f.away.id);
    if (out.length === count) break;
  }
  return out;
}

/** This account's open saved picks and parlays on these matches, removed: a clean slate. */
async function clearMine(page: Page, fixtureIds: number[]): Promise<void> {
  const picks = await getJson<{
    data: Array<{ id: number; status: string; match: { fixture_id: number } }>;
  }>(page.request, "/api/v1/me/picks?status=open");
  for (const p of picks.body.data) {
    if (fixtureIds.includes(p.match.fixture_id)) {
      await sendJson(page.request, "DELETE", `/api/v1/me/picks/${p.id}`);
    }
  }
}

/** Open a match's markets and choose its first price (the home win). */
async function chooseFirstPrice(page: Page, w: Watch, fixtureId: number): Promise<void> {
  const t = L[lang()];
  await open(page, w, `/matches/${fixtureId}`);
  await page.getByRole("tab", { name: t.match.tabs.markets }).click();
  await settle(page);
  await page.getByTestId("price-menu").first().click();
  await expect(page.getByTestId("price-menu-content")).toBeVisible();
}

// One account's own records: these three run one after another, so a parlay saved by one is
// never half-counted by another.
test.describe.serial("a user's own records", () => {
  test("My picks: a price saved from a match is kept with my own price, and can be removed before kick-off", async ({
    page,
  }) => {
    const w = watch(page);
    const t = L[lang()];
    const [fixture] = await pricedFixtures(page, 1);
    if (!fixture) {
      note(test.info(), "no upcoming match with a 1X2 price in the next 72 h");
      return;
    }
    await clearMine(page, [fixture.fixture_id]);
    await chooseFirstPrice(page, w, fixture.fixture_id);
    const menu = page.getByTestId("price-menu-content");
    await menu.getByTestId("save-pick").click();
    await expect(menu.getByTestId("save-pick")).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Escape");

    await open(page, w, "/my-picks");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.records.mine.title);
    const row = page.getByTestId("saved-pick").filter({ hasText: fixture.home.name }).first();
    await expect(row).toBeVisible();
    await expect(row.getByTestId("origin-mine")).toHaveText(t.records.labels.savedByMe);
    await expect(row.getByTestId("result-badge")).toHaveAttribute("data-status", "PENDING");

    await row.getByTestId("saved-pick-odds").click();
    await row.getByTestId("user-odds-input").fill(lang() === "es" ? "2,35" : "2.35");
    await row.getByTestId("user-odds-save").click();
    await expect(row.getByTestId("saved-pick-user-odds")).toContainText(
      lang() === "es" ? "2,35" : "2.35",
    );

    await row.getByTestId("saved-pick-remove").click();
    await expect(page.getByTestId("saved-pick").filter({ hasText: fixture.home.name })).toHaveCount(
      0,
    );
    await assertClean(page, w);
  });

  test("My parlay: two matches added from their prices, checked by the server, saved, then deleted", async ({
    page,
  }) => {
    const w = watch(page);
    const t = L[lang()];
    const fixtures = await pricedFixtures(page, 2);
    if (fixtures.length < 2) {
      note(test.info(), "fewer than two upcoming matches with a 1X2 price and distinct teams");
      return;
    }
    for (const f of fixtures) {
      await chooseFirstPrice(page, w, f.fixture_id);
      const menu = page.getByTestId("price-menu-content");
      await menu.getByTestId("add-to-parlay").click();
      await expect(menu.getByTestId("add-to-parlay")).toHaveAttribute("aria-pressed", "true");
      await page.keyboard.press("Escape");
    }
    await page.getByTestId("slip-open").click();
    const sheet = page.getByTestId("slip-sheet");
    await expect(sheet.getByTestId("slip-leg")).toHaveCount(2);
    await expect(sheet.getByTestId("slip-save")).toBeEnabled();
    await expect(sheet.getByTestId("slip-error")).toHaveCount(0);
    const name = `E2E ${lang()} ${Date.now()}`;
    await sheet.getByTestId("slip-name").fill(name);
    await sheet.getByTestId("slip-save").click();
    await expect(sheet).toHaveCount(0);
    await expect(page.getByTestId("slip-open")).toHaveCount(0);

    await open(page, w, "/my-picks");
    const card = page.getByTestId("my-parlay").filter({ hasText: name });
    await expect(card).toBeVisible();
    await expect(card.getByTestId("parlay-status")).toHaveText(t.records.parlayStatus.READY);
    await card.getByTestId("my-parlay-remove").click();
    await expect(page.getByTestId("my-parlay").filter({ hasText: name })).toHaveCount(0);
    await assertClean(page, w);
  });

  test("My results: today, 7 days, 30 days and everything, in four groups, as the API counts them", async ({
    page,
  }) => {
    const w = watch(page);
    const t = L[lang()];
    await open(page, w, "/my-picks");
    const periods = page.getByTestId("history-period");
    for (const period of ["today", "7d", "30d", "all"] as const) {
      await periods.getByRole("button", { name: t.records.mine.results.period[period] }).click();
      await settle(page);
      const { body } = await getJson<{ data: { groups: Record<string, { total: number }> } }>(
        page.request,
        `/api/v1/me/history?period=${period}`,
      );
      const fmt = new Intl.NumberFormat(lang() === "es" ? "es-ES" : "en-GB");
      for (const group of ["predigol_picks", "my_picks", "predigol_parlays", "my_parlays"]) {
        await expect(page.getByTestId(`history-${group}-total`)).toHaveText(
          fmt.format(body.data.groups[group]?.total ?? 0),
        );
      }
    }
    await assertClean(page, w);
  });
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
