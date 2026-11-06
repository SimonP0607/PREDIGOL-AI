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

test("navigation is the product's five destinations, in the account's language", async ({
  page,
}) => {
  // Plan UX, A15: Inicio, Partidos, Picks, Mis picks and «Más» (Parlays, Cuotas, Ayuda, Perfil, Glosario and, once it
  // is open to readers, Transparencia) - at a desk the same groups as the phone's bar.
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/home");
  const nav = page.getByRole("navigation", { name: t.nav.mainNavigation }).first();
  for (const key of ["home", "matches", "picks", "myPicks"] as const) {
    await expect(nav.getByRole("link", { name: t.nav[key], exact: true })).toBeVisible();
  }
  for (const key of ["live", "parlays", "odds"] as const) {
    await expect(nav.getByRole("link", { name: t.nav[key], exact: true })).toHaveCount(0);
  }
  await nav.getByTestId("nav-more").click();
  const menu = page.getByTestId("nav-more-menu");
  for (const key of ["parlays", "odds", "help", "profile", "glossary"] as const) {
    await expect(menu.getByRole("menuitem", { name: new RegExp(`^${t.nav[key]}`) })).toBeVisible();
  }
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
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

interface TodayBody {
  day: string;
  matches: {
    data: Array<{
      fixture_id: number;
      kickoff_at: string;
      suggested: boolean;
      has_reading: boolean;
      status_group: string;
      forecast: { outcome: string; probability: string; calibrated: boolean } | null;
    }>;
  };
  no_pick: { data: { state: string; stage: string | null; reason: string | null } };
}

const VETOED: Record<Lang, RegExp> = {
  es: /\b(valor|seguro|segura|fijo|fija|garantizad[oa]s?|apuesta)\b/i,
  en: /\b(value|sure|guaranteed|lock|bet)\b/i,
};

interface NewsItemBody {
  id: string;
  status: string;
  kind: string;
  headline_es?: string | null;
  headline_en?: string | null;
  claims: Array<{
    text: string | null;
    text_en?: string | null;
    assertion: string;
    sources: Array<{ name: string; url: string | null }>;
  }>;
}
interface NewsBody {
  status: string;
  data: { items: NewsItemBody[] } | null;
}
interface TodayNewsBody {
  items: Array<{
    match: { fixture_id: number; kickoff_at: string; status_group: string };
    item: NewsItemBody;
  }>;
}

/** Whether an instant falls on today in a time zone (the reader's own day). */
function sameDay(iso: string, zone: string): boolean {
  const day = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: zone });
  return day(new Date(iso)) === day(new Date());
}

test("Home: today in the suggested leagues, the day's picks or why there are none, the parlays, results, live, best odds", async ({
  page,
}) => {
  // Plan UX, A9 (section 24): with or without picks, Inicio says what there is today - in that order.
  const w = watch(page);
  const t = L[lang()];
  const { status, body } = await getJson<{ data: BoardBody }>(page.request, "/api/v1/daily");
  expect(status).toBe(200);
  expect(body.data.evaluation_mode, "a USER never gets the evaluation records").toBe(false);
  const today = await getJson<{ data: TodayBody }>(page.request, "/api/v1/today");
  expect(today.status).toBe(200);
  await open(page, w, "/home");
  await expect(page.getByTestId("home-date")).toBeVisible();

  // 1 · Hoy en las ligas sugeridas: the suggested leagues named, each match says why it shows
  const block1 = page.getByTestId("home-today");
  await expect(block1.getByRole("heading", { name: t.home.today.title })).toBeVisible();
  await expect(block1.getByTestId("suggested-leagues")).toBeVisible();
  // the suggested leagues are PrediGol's, never «tuyas»: no «Para ti» until the reader chooses something
  await expect(page.getByTestId("layer-for-you")).toHaveCount(0);
  await expect(page.getByTestId("layer-predigol").getByTestId("home-today")).toBeVisible();
  const rows = block1.getByTestId("today-row");
  if ((await rows.count()) > 0) {
    await expect(rows.first().getByTestId("today-why")).toHaveText(t.home.today.why);
  } else {
    await expect(block1.getByTestId("today-empty")).toBeVisible();
    note(test.info(), "no match of the suggested leagues today: the block said so");
  }

  // 2 · Picks del día: the recorded set, or the honest sentence and its reason
  const daily = page.getByTestId("daily-set");
  await expect(daily.getByRole("heading", { name: t.records.daily.title })).toBeVisible();
  const items = body.data.set?.items ?? [];
  if (items.length > 0) {
    await expect(daily.getByTestId("daily-item")).toHaveCount(items.length);
  } else {
    const reason = today.body.data.no_pick.data;
    const empty = daily.getByTestId("no-pick");
    await expect(empty).toBeVisible();
    if (reason.state === "reviewing") {
      await expect(empty.getByTestId("no-pick-title")).toHaveText(t.records.noPick.reviewing);
    } else if (reason.reason === "no_matches") {
      await expect(empty.getByTestId("no-pick-title")).toHaveText(t.records.noPick.noMatches);
    } else if (reason.state === "none") {
      await expect(empty.getByTestId("no-pick-title")).toHaveText(t.records.noPick.honest);
      const known = reason.reason
        ? (t.records.noPick.reason as Record<string, string>)[reason.reason]
        : undefined;
      if (known) await expect(empty.getByTestId("no-pick-reason")).toContainText(known);
    }
    expect(await empty.innerText(), "an empty day never says «valor»").not.toMatch(VETOED[lang()]);
    note(
      test.info(),
      `no pick today (${reason.state}, ${reason.reason ?? "-"}): the honest empty state was checked`,
    );
  }
  const built = (p: ParlayRecordBody | null) => Boolean(p && p.legs.length > 0);
  if (!built(body.data.daily_parlay) && !built(body.data.multiday_parlay)) {
    await expect(page.getByTestId("home-parlays-none")).toBeVisible();
  } else {
    await expectParlay(page.getByTestId("home-parlay-daily"), body.data.daily_parlay);
    await expectParlay(page.getByTestId("home-parlay-multiday"), body.data.multiday_parlay);
  }

  // 6 · Resultados, then what is in play everywhere and the best prices
  const results = page.getByTestId("home-results");
  await expect(results.getByRole("heading", { name: t.home.results.title })).toBeVisible();
  await expect(
    results.getByTestId("results-list").or(results.getByTestId("results-empty")),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: t.home.live.title })).toBeVisible();
  await expect(page.getByRole("heading", { name: t.home.best.title })).toBeVisible();
  // 4 · Noticias (A10): the confirmed or probable news of today's suggested matches - only with content
  const news = await getJson<{ status: string; data: TodayNewsBody | null }>(
    page.request,
    "/api/v1/today/news",
  );
  expect(news.status).toBe(200);
  const me = await getJson<{ timezone: string }>(page.request, "/api/v1/auth/me");
  const zone = me.body.timezone; // the page cuts the reader's day in the account's own zone
  const todays = (news.body.data?.items ?? []).filter(
    (i) => i.match.status_group === "live" || sameDay(i.match.kickoff_at, zone),
  );
  const block4 = page.getByTestId("home-news");
  if (news.body.status === "ok" && todays.length > 0) {
    await expect(block4.getByRole("heading", { name: t.home.news.title })).toBeVisible();
    const cards = block4.getByTestId("news-card");
    await expect(cards).toHaveCount(Math.min(todays.length, 4));
    for (const status of await cards.evaluateAll((els) =>
      els.map((e) => e.getAttribute("data-status")),
    )) {
      expect(
        ["CONFIRMED", "PROBABLE"],
        "Inicio shows only what is confirmed or probable",
      ).toContain(status);
    }
    await expect(block4.getByTestId("home-news-match").first()).toHaveAttribute(
      "href",
      /\/matches\/\d+#news$/,
    );
  } else {
    await expect(block4).toHaveCount(0);
    note(
      test.info(),
      "no confirmed or probable news of today's suggested matches: the block stays out",
    );
  }
  // the blocks in the order of section 24
  const order = await page.$$eval(
    '[data-testid="home-today"], [data-testid="daily-set"], [data-testid="home-relevant"], [data-testid="home-news"], [data-testid="home-context"], [data-testid="home-results"]',
    (els) => els.map((e) => e.getAttribute("data-testid") ?? ""),
  );
  const seen = order.filter((x, i) => order.indexOf(x) === i);
  const SECTION_24 = [
    "home-today",
    "daily-set",
    "home-relevant",
    "home-news",
    "home-context",
    "home-results",
  ];
  expect(seen).toEqual(SECTION_24.filter((x) => seen.includes(x)));
  expect(seen).toEqual(expect.arrayContaining(["home-today", "daily-set", "home-results"]));
  await assertClean(page, w);
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
  if (items.length === 0) {
    // plan UX, A9: today's empty set says why, as Inicio does
    await expect(page.getByTestId("no-pick")).toBeVisible();
  }
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

/**
 * Open a match's markets and return its first price (the home win). Every price is chosen the Cuotas way
 * (REVIEW points 6 and 18): a tap toggles it in "Mi parlay", the bookmark beside it saves it.
 */
async function firstPrice(page: Page, w: Watch, fixtureId: number) {
  const t = L[lang()];
  await open(page, w, `/matches/${fixtureId}`);
  await page.getByRole("tab", { name: t.match.tabs.markets }).click();
  await settle(page);
  const price = page.getByTestId("selectable-price").first();
  await expect(price).toBeVisible();
  return price;
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
    const price = await firstPrice(page, w, fixture.fixture_id);
    await price.getByTestId("save-pick").click();
    await expect(price.getByTestId("save-pick")).toHaveAttribute("aria-pressed", "true");
    // Plan UX, A1 (F53): taking a saved pick out asks first; cancelling keeps it.
    await price.getByTestId("save-pick").click();
    await expect(page.getByTestId("confirm-unsave-pick")).toBeVisible();
    await page.getByTestId("confirm-unsave-pick-cancel").click();
    await expect(page.getByTestId("confirm-unsave-pick")).toHaveCount(0);
    await expect(price.getByTestId("save-pick")).toHaveAttribute("aria-pressed", "true");

    await open(page, w, "/my-picks");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.records.mine.title);
    // By the match, not by a team's name: the account's settled history can hold the same team (Brighton in
    // "Junior – Brighton"), which a removal never clears.
    const mine = page.locator(
      `[data-testid="saved-pick"][data-fixture-id="${fixture.fixture_id}"]`,
    );
    const row = mine.first();
    await expect(row).toBeVisible();
    // Plan UX, A1: the user's own selection says so ("Tu selección"), never mixed with PrediGol's picks.
    await expect(row.getByTestId("origin-mine")).toHaveText(t.records.labels.mine);
    await expect(row.getByTestId("result-badge")).toHaveAttribute("data-status", "PENDING");

    await row.getByTestId("saved-pick-odds").click();
    await row.getByTestId("user-odds-input").fill(lang() === "es" ? "2,35" : "2.35");
    await row.getByTestId("user-odds-save").click();
    await expect(row.getByTestId("saved-pick-user-odds")).toContainText(
      lang() === "es" ? "2,35" : "2.35",
    );

    // Removing asks first: cancel keeps the pick, confirm removes it.
    await row.getByTestId("saved-pick-remove").click();
    await expect(page.getByTestId("confirm-remove-pick")).toBeVisible();
    await page.getByTestId("confirm-remove-pick-cancel").click();
    await expect(row).toBeVisible();
    await row.getByTestId("saved-pick-remove").click();
    await page.getByTestId("confirm-remove-pick-ok").click();
    await expect(mine).toHaveCount(0);
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
      const price = await firstPrice(page, w, f.fixture_id);
      await price.getByTestId("odds-add-to-parlay").click();
      await expect(price.getByTestId("odds-add-to-parlay")).toHaveAttribute("aria-pressed", "true");
    }
    await page.getByTestId("slip-open").click();
    const sheet = page.getByTestId("slip-sheet");
    await expect(sheet.getByTestId("slip-leg")).toHaveCount(2);
    // Plan UX, A1 (F53): a leg taken out can be put back, as it was, for five seconds.
    await sheet.getByTestId("slip-remove").first().click();
    await expect(sheet.getByTestId("slip-leg")).toHaveCount(1);
    await sheet.getByTestId("slip-undo-button").click();
    await expect(sheet.getByTestId("slip-leg")).toHaveCount(2);
    await expect(sheet.getByTestId("slip-undo")).toHaveCount(0);
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
    await page.getByTestId("confirm-remove-parlay-ok").click();
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

test("One figure: over 30 days and over everything, the recap's profit and return are My results' own", async ({
  page,
}) => {
  // Plan UX, A1 (F53, F54): the recap counted its own "Rentabilidad" over the first 500 picks, with another formula
  // and another window than "Tus resultados". Now both count every record, the same way, over the same days.
  const w = watch(page);
  const t = L[lang()];
  await page.emulateMedia({ reducedMotion: "reduce" }); // the recap's figures count up; without motion they are final
  await open(page, w, "/my-picks");
  const recap = page.getByTestId("my-recap");
  const results = page.getByTestId("my-results");
  for (const [period, recapLabel] of [
    ["30d", t.records.recap.days_other.replace("{count}", "30")],
    ["all", t.records.recap.all],
  ] as const) {
    const { body } = await getJson<{
      data: { groups: { my_picks: { won: number; lost: number } } };
    }>(page.request, `/api/v1/me/history?period=${period}`);
    const g = body.data.groups.my_picks;
    if (g.won + g.lost === 0) {
      note(test.info(), `no settled pick of this account in the period ${period}`);
      continue;
    }
    await results
      .getByTestId("history-period")
      .getByRole("button", { name: t.records.mine.results.period[period] })
      .click();
    await recap.getByTestId("recap-period").getByRole("button", { name: recapLabel }).click();
    await settle(page);
    for (const [mine, theirs] of [
      ["recap-kpi-profit", "history-my_picks-profit"],
      ["recap-kpi-roi", "history-my_picks-roi"],
      ["recap-roi-sample", "history-my_picks-roi-sample"],
    ] as const) {
      await expect(recap.getByTestId(mine), `${mine} over ${period}`).toHaveText(
        (await results.getByTestId(theirs).innerText()).trim(),
      );
    }
  }
  await assertClean(page, w);
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
  for (const key of ["summary", "analysis", "stats", "markets", "lineups", "news"] as const) {
    await expect(page.getByRole("tab", { name: t.match.tabs[key] })).toBeVisible();
  }
  await expect(page.getByRole("tab", { name: t.match.tabs.advanced })).toHaveCount(0);
  for (const key of ["stats", "markets", "lineups", "news"] as const) {
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
  // before kick-off the table is under «Profundizar» (plan de cierre UX, 2.2): folded until the reader opens it
  const deepen = page.getByTestId("match-deepen").getByRole("button").first();
  await expect(deepen).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator('[data-testid="table-freshness"]')).toHaveCount(0);
  await deepen.click();
  await expect(deepen).toHaveAttribute("aria-expanded", "true");
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

test("A match's PrediGol analysis: only what a user may see, never value without a price, read from storage", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const after = new Date().toISOString();
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=scheduled&order=asc&limit=40&kickoff_after=${encodeURIComponent(after)}`,
  );
  let found: {
    id: number;
    cards: Array<{
      verdict: string;
      kind: string;
      qualified: boolean;
      odds: string | null;
      edge: string | null;
    }>;
    withheld: number;
  } | null = null;
  for (const m of body.data) {
    const a = await getJson<{
      status: string;
      data: {
        audience: string;
        cards: Array<{
          verdict: string;
          kind: string;
          qualified: boolean;
          odds: string | null;
          edge: string | null;
        }>;
        withheld: number;
      } | null;
    }>(page.request, `/api/v1/matches/${m.id}/analysis`);
    expect(a.status).toBe(200);
    if (a.body.data) {
      expect(a.body.data.audience).toBe("user");
      for (const c of a.body.data.cards) {
        expect(c.kind === "no_market" || c.qualified).toBe(true);
        if (c.kind === "no_market") expect([c.odds, c.edge]).toEqual([null, null]);
      }
      found = { id: m.id, cards: a.body.data.cards, withheld: a.body.data.withheld };
      break;
    }
  }
  const denied = await getJson<unknown>(
    page.request,
    `/api/v1/matches/${body.data[0]?.id ?? 1}/analysis?preview=shadow`,
  );
  expect(denied.status).toBe(403);
  if (!found) {
    note(
      test.info(),
      "no upcoming match has an analysis yet (the AI cycle has not run on this database)",
    );
    return;
  }
  await open(page, w, `/matches/${found.id}`);
  await expect(page.getByRole("heading", { name: t.match.analysis.title })).toBeVisible();
  if (found.cards.length) {
    await expect(page.getByTestId("analysis-card").first()).toBeVisible();
    if (found.cards.some((c) => c.verdict === "no_market"))
      await expect(page.getByText(t.match.analysis.noMarketBanner).first()).toBeVisible();
  }
  await expect(page.getByTestId("analysis-footer")).toBeVisible();
  note(
    test.info(),
    `analysis of ${found.id}: ${found.cards.length} cards, ${found.withheld} in evaluation`,
  );
});

interface NarrativeBody {
  version: string;
  data_at: string;
  es: Array<{ key: string; sentences: Array<{ text: string; refs: string[] }> }>;
  en: Array<{ key: string; sentences: Array<{ text: string; refs: string[] }> }>;
  sources?: Array<{ name: string }>;
}

interface ReadingBody {
  status: string;
  data: {
    complete: boolean;
    sections: Array<{ key: string; facts: Array<{ code: string; ref: string }> }>;
    narrative?: NarrativeBody | null;
  } | null;
}

/**
 * Today's matches with a reading's context (a packet) that are still to kick off - a QA match whose kick-off passed while its
 * status says scheduled shows «pending result» instead of the pre-match blocks.
 */
async function packedMatches(page: Page): Promise<number[]> {
  const today = await getJson<{ data: TodayBody }>(page.request, "/api/v1/today");
  const now = Date.now();
  return today.body.data.matches.data
    .filter(
      (m) => m.has_reading && m.status_group === "scheduled" && Date.parse(m.kickoff_at) > now,
    )
    .map((m) => m.fixture_id);
}

async function readingOf(page: Page, id: number): Promise<ReadingBody> {
  return (await getJson<ReadingBody>(page.request, `/api/v1/matches/${id}/reading`)).body;
}

/**
 * A match whose reading has its context (a packet) and no narrative - the facts are what A9 shows -, else any match to come:
 * the reading of either is checked.
 */
async function matchToRead(page: Page): Promise<{ id: number; withPacket: boolean } | null> {
  for (const id of await packedMatches(page)) {
    if (!(await readingOf(page, id)).data?.narrative) return { id, withPacket: true };
  }
  const after = new Date().toISOString();
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=scheduled&order=asc&limit=1&kickoff_after=${encodeURIComponent(after)}`,
  );
  const id = body.data[0]?.id;
  return id ? { id, withPacket: false } : null;
}

test("A match's Análisis PrediGol: six sections of facts with their references, the time of its data, a link in either language and the tabs by keyboard", async ({
  page,
}) => {
  // Plan UX, A9 (sections 25 and 26): the structured reading, no AI - every fact a template, each with its reference.
  const w = watch(page);
  const t = L[lang()];
  const target = await matchToRead(page);
  if (!target) {
    note(test.info(), "no match to come");
    return;
  }
  const api = await getJson<ReadingBody>(page.request, `/api/v1/matches/${target.id}/reading`);
  expect(api.status).toBe(200);
  const denied = await getJson<unknown>(
    page.request,
    `/api/v1/matches/${target.id}/reading?preview=shadow`,
  );
  expect(denied.status, "the owner's preview is not a reader's").toBe(403);
  await open(page, w, `/matches/${target.id}?s=analisis`);
  const tab = page.getByRole("tab", { name: t.match.tabs.analysis });
  await expect(tab).toHaveAttribute("aria-selected", "true");
  const block = page.getByTestId("match-reading");
  await expect(block).toBeVisible();
  if (api.body.status !== "ok" || !api.body.data) {
    await expect(block.getByTestId("reading-unavailable")).toBeVisible();
    note(test.info(), "the reading is turned off for readers here");
    return;
  }
  const reading = api.body.data;
  for (const section of reading.sections) {
    const shown = block.getByTestId(`reading-section-${section.key}`);
    await expect(shown).toBeVisible();
    await expect(shown.getByRole("heading", { level: 3 })).toHaveText(
      (t.match.readingBlock.sections as Record<string, string>)[section.key] ?? "",
    );
  }
  const facts = block.getByTestId("reading-fact");
  expect(await facts.count()).toBeGreaterThan(0);
  for (const ref of await facts.evaluateAll((els) => els.map((e) => e.getAttribute("data-ref")))) {
    expect(ref ?? "", "every fact carries its reference").toMatch(/^(packet|forecast)\b/);
  }
  const words = await block.innerText();
  expect(words).not.toMatch(/\b[a-z]+_[a-z_]+\b/); // never a raw code
  expect(words, "no certainty, no «valor»").not.toMatch(VETOED[lang()]);
  await expect(block.getByTestId("reading-caveat")).toHaveText(t.match.readingBlock.caveat);
  if (target.withPacket) {
    await expect(block.getByTestId("reading-data-at")).toBeVisible();
    expect(reading.sections.map((x) => x.key)).toEqual(
      expect.arrayContaining(["summary", "context", "data", "risks", "conclusion"]),
    );
  } else {
    await expect(block.getByTestId("reading-partial")).toBeVisible();
  }
  // the same section from an English link, and the tabs by keyboard (ARIA: arrows, Home, End)
  await page.goto(`/matches/${target.id}?s=analysis`);
  await settle(page);
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await tab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: t.match.tabs.stats })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("tab", { name: t.match.tabs.stats })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(page.getByRole("tab", { name: t.match.tabs.summary })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("End");
  await expect(page.getByRole("tab").last()).toHaveAttribute("aria-selected", "true");
  // the Resumen opens with the reading's summary and its two main risks, and the way to the whole analysis
  await page.getByRole("tab", { name: t.match.tabs.summary }).click();
  const highlights = page.getByTestId("reading-highlights");
  await expect(highlights).toBeVisible();
  await highlights.getByTestId("reading-see-all").click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await assertClean(page, w);
});

/** A match to come whose reading carries a narrative (A11), and another whose reading has none (refused, or never written). */
async function narrativeTargets(
  page: Page,
): Promise<{ withNarrative: number | null; withFacts: number | null }> {
  let withNarrative: number | null = null;
  let withFacts: number | null = null;
  const after = new Date().toISOString();
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=scheduled&order=asc&limit=20&kickoff_after=${encodeURIComponent(after)}`,
  );
  const ids = [...new Set([...(await packedMatches(page)), ...body.data.map((m) => m.id)])];
  for (const id of ids) {
    const reading = await readingOf(page, id);
    if (reading.status !== "ok" || !reading.data?.complete) continue;
    if (reading.data.narrative) withNarrative ??= id;
    else withFacts ??= id;
    if (withNarrative !== null && withFacts !== null) break;
  }
  return { withNarrative, withFacts };
}

test("A match's chronicle written with AI (A11, UX-025): a paragraph for each side under its team, its sources, labelled as checked against PrediGol's data, in the reader's language; without one, the facts", async ({
  page,
}) => {
  // Plan UX, A11 and UX-025: the chronicle only when the server validated it for THIS story; the facts otherwise.
  const w = watch(page);
  const t = L[lang()];
  const { withNarrative, withFacts } = await narrativeTargets(page);
  if (withNarrative === null) {
    note(
      test.info(),
      "no chronicle on this database (the owner keeps it off, or none was written)",
    );
    return;
  }
  const reading = (await readingOf(page, withNarrative)).data!;
  const narrative = reading.narrative!;
  expect(narrative.version).toBe("user-narrative-v2");
  const sections = narrative[lang()];
  expect(sections.map((x) => x.key)).toEqual(narrative.es.map((x) => x.key));
  await open(page, w, `/matches/${withNarrative}?s=analisis`);
  const block = page.getByTestId("match-reading");
  const chronicle = block.getByTestId("reading-narrative");
  await expect(chronicle).toBeVisible();
  await expect(block.getByTestId("reading-label")).toHaveText(t.match.readingBlock.narrative.label);
  await expect(block.getByTestId("reading-data-at")).toBeVisible();
  await expect(chronicle.getByTestId("reading-fact")).toHaveCount(0);
  // the lead, a paragraph for each side, the head-to-head and the risks - in that order, each only when it has something
  const order = await chronicle
    .locator('[data-testid^="narrative-section-"]')
    .evaluateAll((els) =>
      els.map((e) => e.getAttribute("data-testid")?.replace("narrative-section-", "")),
    );
  expect(order).toEqual(sections.map((x) => x.key));
  const ranked = ["summary", "home", "away", "h2h", "risks"];
  expect(order.map((k) => ranked.indexOf(k ?? ""))).toEqual(
    order.map((k) => ranked.indexOf(k ?? "")).sort((x, y) => x - y),
  );
  expect(order.every((k) => ranked.includes(k ?? ""))).toBe(true);
  // a paragraph is a single block of text, never a list of cards
  await expect(chronicle.locator("section > p")).toHaveCount(sections.length);
  const shown = chronicle.getByTestId("narrative-sentence");
  await expect(shown).toHaveCount(sections.reduce((n, x) => n + x.sentences.length, 0));
  for (const refs of await shown.evaluateAll((els) =>
    els.map((e) => e.getAttribute("data-refs")),
  )) {
    expect(refs ?? "", "every sentence carries its references").toMatch(/^(P|E):\S+( (P|E):\S+)*$/);
  }
  const outlets = (narrative.sources ?? []).map((o) => o.name);
  if (outlets.length) {
    await expect(chronicle.getByTestId("narrative-sources")).toContainText(outlets.join(", "));
  } else {
    await expect(chronicle.getByTestId("narrative-sources")).toHaveCount(0);
  }
  await expect(chronicle.getByTestId("narrative-apart")).toBeVisible();
  // the forecast and the market are not the chronicle's: they keep their own sections, from the reading's templates
  if (reading.sections.some((x) => x.key === "conclusion")) {
    await expect(block.getByTestId("reading-caveat")).toHaveText(t.match.readingBlock.caveat);
  }
  const words = await chronicle.innerText();
  expect(words, "never a raw code").not.toMatch(/\b[a-z]+_[a-z_]+\b/);
  expect(words, "no certainty, no «valor»").not.toMatch(VETOED[lang()]);
  const other = lang() === "es" ? narrative.en : narrative.es;
  expect(words, "only the reader's language").not.toContain(other[0]!.sentences[0]!.text);
  // a match whose reading has no chronicle shows its facts, as A9 does
  if (withFacts !== null) {
    await open(page, w, `/matches/${withFacts}?s=analisis`);
    await expect(block.getByTestId("reading-fact").first()).toBeVisible();
    await expect(block.getByTestId("reading-narrative")).toHaveCount(0);
    await expect(block.getByTestId("reading-label")).toHaveText(t.match.readingBlock.label);
  }
  await assertClean(page, w);
});

test("A finished match opens on its Postpartido: the result and what the forecast said, or that there was none", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    "/api/v1/matches?status=finished&order=desc&limit=1",
  );
  const id = body.data[0]?.id;
  if (!id) {
    note(test.info(), "no finished match");
    return;
  }
  await open(page, w, `/matches/${id}`);
  await expect(page.getByRole("tab", { name: t.match.tabs.postmatch })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(
    page.getByRole("heading", { name: t.match.result.title, exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: t.match.postmatch.title, exact: true }),
  ).toBeVisible();
  // an old link to the picks opens the Resumen, where the picks of the match now live
  await page.goto(`/matches/${id}#picks`);
  await settle(page);
  await expect(page.getByRole("tab", { name: t.match.tabs.summary })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await assertClean(page, w);
});

/** A match of the window with news (the QA database's «QA Primera A» match of today has them) and one without. */
async function newsTargets(
  page: Page,
): Promise<{ withNews: number | null; without: number | null }> {
  const today = await getJson<{ data: TodayBody }>(page.request, "/api/v1/today");
  let withNews: number | null = null;
  let without: number | null = null;
  for (const m of today.body.data.matches.data) {
    if (withNews !== null && without !== null) break;
    const r = await getJson<NewsBody>(page.request, `/api/v1/matches/${m.fixture_id}/news`);
    expect(r.status).toBe(200);
    if (r.body.status === "ok" && withNews === null) withNews = m.fixture_id;
    if (r.body.status === "empty" && without === null) without = m.fixture_id;
  }
  return { withNews, without };
}

const NEWS_ORDER = ["CONFIRMED", "PROBABLE", "CONTRADICTORY", "RUMOR", "OUTDATED"];

test("A match's Noticias: cards with their seven elements in the order of section 27, rumours last and labelled, the press's absences in Alineaciones, and the exact sentence without coverage", async ({
  page,
}) => {
  // Plan UX, A10 (sections 25 and 27): what PrediGol Intelligence verified in the press, never an article's text.
  const w = watch(page);
  const t = L[lang()];
  const sent: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/api/v1/events")) {
      const body = req.postDataJSON() as { events?: Array<{ name: string }> } | null;
      sent.push(...(body?.events ?? []).map((e) => e.name));
    }
  });
  const { withNews, without } = await newsTargets(page);
  const tab = page.getByRole("tab", { name: t.match.tabs.news });
  if (without !== null) {
    await open(page, w, `/matches/${without}?s=noticias`);
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("news-empty")).toHaveText(t.match.news.empty);
  } else {
    note(test.info(), "every match of the window has news");
  }
  if (withNews === null) {
    note(
      test.info(),
      "no match with news on this database (PrediGol Intelligence has not read the press here)",
    );
    return;
  }
  const api = await getJson<NewsBody>(page.request, `/api/v1/matches/${withNews}/news`);
  const items = api.body.data?.items ?? [];
  const ranks = items.map((i) => NEWS_ORDER.indexOf(i.status));
  expect(ranks, "confirmed first, rumours and the outdated last").toEqual(
    [...ranks].sort((a, b) => a - b),
  );
  await open(page, w, `/matches/${withNews}?s=news`);
  await expect(tab).toHaveAttribute("aria-selected", "true");
  const block = page.getByTestId("match-news");
  const cards = block.getByTestId("news-card");
  await expect(cards).toHaveCount(items.length);
  expect(await cards.evaluateAll((els) => els.map((e) => e.getAttribute("data-status")))).toEqual(
    items.map((i) => i.status),
  );
  // the rumours and the outdated are folded under what is verified: one tap opens each group
  // each group opened leaves the list of the closed ones: always the first one still closed
  const closed = block.locator("details:not([open]) > summary");
  while ((await closed.count()) > 0) await closed.first().click();
  const labels = t.match.news.status as Record<string, { label: string }>;
  for (let i = 0; i < items.length; i++) {
    const card = cards.nth(i);
    const item = items[i]!;
    for (const id of [
      "news-status",
      "news-relevance",
      "news-time",
      "news-headline",
      "news-summary",
      "news-source",
    ]) {
      await expect(card.getByTestId(id).first(), id).toBeVisible();
    }
    // the status in words, not only a colour
    await expect(card.getByTestId("news-status")).toContainText(labels[item.status]?.label ?? "?");
    if (item.claims[0]?.sources.some((s) => s.url)) {
      const link = card.getByTestId("news-link").first();
      await expect(link).toHaveAttribute("target", "_blank");
      await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
    expect(
      (await card.getByTestId("news-summary").first().innerText()).trim().length,
    ).toBeGreaterThan(10);
    if (item.claims.length > 1)
      await expect(card.getByTestId("news-claim")).toHaveCount(item.claims.length);
  }
  if (items.some((i) => i.status === "RUMOR")) {
    await expect(block.getByTestId("news-group-rumor")).toBeVisible();
    await expect(block.getByTestId("news-rumor-note")).toBeVisible();
  }
  expect(await block.innerText(), "no certainty, no «valor»").not.toMatch(VETOED[lang()]);
  // in English: a summary PrediGol translated (A11) is shown in English; one it did not, in Spanish and labelled
  if (lang() === "en" && items.some((i) => i.claims.some((c) => c.text && !c.text_en)))
    await expect(block.getByTestId("news-in-spanish").first()).toBeVisible();
  const translated = items.flatMap((i) => i.claims).find((c) => c.text_en);
  if (translated)
    await expect(
      block
        .getByTestId("news-summary")
        .filter({ hasText: lang() === "en" ? translated.text_en! : translated.text! })
        .first(),
    ).toBeVisible();
  const headed = items.find((i) => (lang() === "es" ? i.headline_es : i.headline_en));
  if (headed)
    await expect(
      block
        .getByTestId("news-headline")
        .filter({ hasText: (lang() === "es" ? headed.headline_es : headed.headline_en)! })
        .first(),
    ).toBeVisible();
  await expect.poll(() => sent, { timeout: 20_000 }).toContain("news_opened");
  // Alineaciones: the press's absences with their status and source - never a rumour -, and the way to Noticias
  const said = items.filter(
    (i) =>
      ["injury", "suspension", "doubtful"].includes(i.kind) &&
      ["CONFIRMED", "PROBABLE", "CONTRADICTORY"].includes(i.status) &&
      i.claims.some((c) => c.assertion === "out" || c.assertion === "doubtful"),
  );
  await page.getByRole("tab", { name: t.match.tabs.lineups }).click();
  await settle(page);
  if (said.length > 0) {
    const press = page.getByTestId("press-absences");
    await expect(press.getByTestId("press-absence")).toHaveCount(said.length);
    await press.getByTestId("press-absences-more").click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
  } else {
    await expect(page.getByTestId("press-absences")).toHaveCount(0);
  }
  note(
    test.info(),
    `news of ${withNews}: ${items.length} cards, ${said.length} absences in the press`,
  );
  await assertClean(page, w);
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

interface CenterLiveBody {
  data: {
    status_group: string;
    events: { status: string; data: unknown[] };
    live_odds: { status: string; data: Array<{ captured_at: string }>; reason: string | null };
    live_movement: { status: string; data: unknown[] };
  } | null;
}

test("A match in play: its centre is live, with the in-play prices of the current book or a note that there are none", async ({
  page,
}) => {
  const w = watch(page);
  const t = L[lang()];
  const { body } = await getJson<{ data: { matches: Array<{ fixture_id: number }> } }>(
    page.request,
    "/api/v1/live",
  );
  const live = body.data.matches[0];
  if (!live) {
    note(test.info(), "no match in play now");
    return;
  }
  const center = await getJson<CenterLiveBody>(
    page.request,
    `/api/v1/matches/${live.fixture_id}/center`,
  );
  await open(page, w, `/matches/${live.fixture_id}`);
  const root = page.getByTestId("match-center");
  await expect(root).toBeVisible();
  if (center.body.data?.status_group !== "live") {
    note(test.info(), "the match finished between the two reads");
    return;
  }
  await expect(root).toHaveAttribute("data-phase", "live");
  await expect(page.getByText(t.match.liveOdds.title).first()).toBeVisible();
  // the block shows 1X2 / the main over-under from the current book, or says it has none for this match now;
  // before the first capture of the match (or with the provider silent) it says there is nothing yet
  const liveOdds = center.body.data.live_odds;
  if (liveOdds.status === "ok" && liveOdds.data.length > 0) {
    await expect(
      page.getByText(t.match.liveOdds.note).or(page.getByText(t.match.liveOdds.none)).first(),
    ).toBeVisible();
  } else {
    await expect(
      page
        .getByTestId("match-center")
        .getByText(t.match.note.noData)
        .or(page.getByText(t.match.note.notAvailable))
        .or(page.getByText(t.match.liveOdds.none))
        .first(),
    ).toBeVisible();
  }
  await assertClean(page, w);
});

test("A finished match keeps its result and events, and no in-play prices", async ({ page }) => {
  const w = watch(page);
  const before = new Date(Date.now() - 4 * 3600_000).toISOString();
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    `/api/v1/matches?status=finished&order=desc&limit=5&kickoff_before=${encodeURIComponent(before)}`,
  );
  const done = body.data[0];
  if (!done) {
    note(test.info(), "no match finished more than four hours ago");
    return;
  }
  const center = await getJson<CenterLiveBody>(page.request, `/api/v1/matches/${done.id}/center`);
  const c = center.body.data;
  expect(c?.status_group).toBe("finished");
  // the in-play book drops a match minutes after its last tick: nothing of it outlives the match
  expect(c?.live_odds.data).toEqual([]);
  expect(c?.live_odds.status).not.toBe("ok");
  expect(c?.live_movement.data).toEqual([]);
  await open(page, w, `/matches/${done.id}`);
  await expect(page.getByTestId("match-center")).toHaveAttribute("data-phase", "finished");
  await assertClean(page, w);
});

test("Profile shows the account's language and time zone", async ({ page }) => {
  const w = watch(page);
  const t = L[lang()];
  await open(page, w, "/profile");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.profile.title);
  const tz = lang() === "es" ? "America/Bogota" : "Europe/Madrid";
  await expect(page.getByTestId("current-timezone")).toContainText(tz);
  await expect(page.getByTestId(`profile-lang-${lang()}`)).toHaveAttribute("aria-checked", "true");
  // The time zones are a listbox that owns its options: every item is a wrapper, every option a button inside it (the
  // three findings of axe on this page in the line base of A0).
  const zones = page.getByRole("listbox");
  await expect(zones.getByRole("option").first()).toBeVisible();
  await expect(zones.locator("> li:not([role='presentation'])")).toHaveCount(0);
  // Plan UX, A1 (F07): no internal role on screen - not in the profile, not in the account menu.
  await expect(page.getByTestId("profile-role")).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText("USER");
  // The session slides with use (F05): the profile says it closes sooner if it goes unused.
  await expect(page.getByTestId("profile-session")).toContainText(
    lang() === "es" ? "7 días" : "7 days",
  );
  await page.getByTestId("account-menu").click();
  await expect(page.getByRole("menu")).toBeVisible();
  await expect(page.getByTestId("account-role")).toHaveCount(0);
  await expect(page.getByRole("menu")).not.toContainText("USER");
});

test("Profile security: a failure to read the sessions or the activity says so, with the reference and a retry", async ({
  page,
}) => {
  // Plan UX, A1 (F05): a failed read showed as an empty list - "no sessions", "no activity" - which is not true.
  const t = L[lang()];
  const fault = (id: string) => ({
    status: 500,
    headers: { "content-type": "application/json", "x-request-id": id },
    body: JSON.stringify({ error: { code: "internal", message: "fault" }, request_id: id }),
  });
  await page.route("**/api/v1/auth/me/sessions", (route) => route.fulfill(fault("e2e-sessions-1")));
  await page.route("**/api/v1/auth/me/access*", (route) => route.fulfill(fault("e2e-access-1")));
  await page.goto("/profile");
  const sessions = page.getByTestId("sessions-error");
  // The error shows after the two retries of a 5xx (1 s and 2 s apart) - and, on the QA dev server under load, after
  // up to 12 s of hydration (A2's run 3: the first request left 12.6 s after the page loaded).
  await expect(sessions).toBeVisible({ timeout: 30_000 });
  await expect(sessions).toContainText(t.errors.requestId.replace("{id}", "e2e-sessions-1"));
  await expect(page.getByTestId("access-error")).toContainText(
    t.errors.requestId.replace("{id}", "e2e-access-1"),
  );
  await expect(page.getByTestId("sessions-panel")).not.toContainText(
    t.profile.securityPanel.thisDevice,
  );
  // the retry reads them again, and the panels show what is there
  await page.unroute("**/api/v1/auth/me/sessions");
  await page.unroute("**/api/v1/auth/me/access*");
  await sessions.getByRole("button", { name: t.common.retry }).click();
  await expect(page.getByTestId("sessions-panel")).toContainText(
    t.profile.securityPanel.thisDevice,
  );
  await page.getByTestId("access-error").getByRole("button", { name: t.common.retry }).click();
  await expect(page.getByTestId("access-error")).toHaveCount(0);
});

interface TransparencyBody {
  status: string;
  data: null | {
    periods: Array<{ period: string; published: number; settled: number; units: string | null }>;
    parlays: Array<{ kind: string; published: number; settled: number; units: string | null }>;
    days: {
      days: number;
      without: number;
      reasons: Record<string, number>;
      items: unknown[];
    };
    markets: Array<{ market: string }>;
    line_value: { n: number; mean: string | null };
    forecasts: Array<{ market: string; state: string; bins: unknown[] }>;
    evaluation: { markets: number; pairs: number; passed_markets: number; qualified: number };
  };
}

/** What the page never says (plan section 31: no streaks, no star pick, no projection, no promise). */
const NEVER_SAID: Record<Lang, RegExp> = {
  es: /racha|pick estrella|garantiz|seguro que|ganar[áa]s|recupera tus|apuesta segura/i,
  en: /streak|star pick|guarantee|sure bet|you will win|recover your/i,
};

interface PublishedPicksBody {
  status: string;
  data: Array<{ result: string; odds: string; p_model: string; home: string; away: string }>;
  meta: { total?: number; next_cursor?: string | null };
}

test("«Cómo le va a PrediGol» (A12): the seven blocks, every figure as the API counted it with its sample, reached from the account menu and from a day without picks - only once readers can open it", async ({
  page,
}) => {
  // Plan UX, A12 (section 31): what PrediGol published and how it went, the days without picks and why, the evaluation in
  // counts - and, while the owner has not opened it (FBI_TRANSPARENCY off, as production starts), no way to it at all.
  const w = watch(page);
  const t = L[lang()];
  const { body } = await getJson<TransparencyBody>(page.request, "/api/v1/transparency");
  const me = (await getJson<{ transparency?: boolean }>(page.request, "/api/v1/auth/me")).body;
  if (body.status !== "ok" || body.data === null) {
    expect(me.transparency ?? false).toBe(false);
    await open(page, w, "/home");
    await page.getByTestId("account-menu").click();
    await expect(page.getByTestId("go-glossary")).toBeVisible();
    await expect(page.getByTestId("go-transparency")).toHaveCount(0);
    await page.keyboard.press("Escape");
    await open(page, w, "/transparency");
    await expect(page.getByText(t.transparency.page.notAvailable)).toBeVisible();
    await expect(page.getByTestId("transparency-body")).toHaveCount(0);
    note(test.info(), "the page is not open to readers on this database (FBI_TRANSPARENCY off)");
    return;
  }
  expect(me.transparency).toBe(true);
  const data = body.data;
  await open(page, w, "/home");
  await page.getByTestId("account-menu").click();
  await page.getByTestId("go-transparency").click();
  await expect(page).toHaveURL(/\/transparency$/);
  await settle(page);
  await assertClean(page, w);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.transparency.page.title);
  await expect(page.getByTestId("transparency-preview")).toHaveCount(0);
  for (const block of [
    "published",
    "parlays",
    "picks",
    "days",
    "markets",
    "line-value",
    "forecast",
    "evaluation",
    "how",
    "what-is-a-pick",
    "how-to-read",
    "definitions",
    "changes",
  ])
    await expect(page.getByTestId(`transparency-${block}`)).toBeVisible();
  // plan de cierre UX, 1.5: with nothing published the page says so, as it is - and only then
  await expect(page.getByTestId("transparency-zero")).toHaveCount(
    data.periods.find((p) => p.period === "all")?.published === 0 ? 1 : 0,
  );
  // PrediGol's parlays, by kind, as the API counted them
  for (const p of data.parlays)
    await expect(page.getByTestId(`transparency-parlay-tally-${p.kind}`)).toHaveAttribute(
      "data-settled",
      String(p.settled),
    );
  // the published picks one by one: a page of them, as many as the counts say, and «ver más» only while there are more
  const listed = (
    await getJson<PublishedPicksBody>(page.request, "/api/v1/transparency/picks?limit=20")
  ).body;
  expect(listed.status === "ok" || listed.status === "empty").toBe(true);
  const total = listed.meta.total ?? 0;
  expect(total).toBe(data.periods.find((p) => p.period === "all")?.published);
  if (total === 0) {
    await expect(page.getByTestId("transparency-picks-none")).toBeVisible();
  } else {
    const rows = page.getByTestId("published-pick");
    await expect(rows).toHaveCount(Math.min(20, total));
    await expect(page.getByTestId("transparency-picks-shown")).toContainText(String(total));
    const more = page.getByTestId("transparency-picks-more");
    await expect(more).toHaveCount(total > 20 ? 1 : 0);
    if (total > 20) {
      expect((await more.boundingBox())!.height).toBeGreaterThanOrEqual(43.5);
      await more.click();
      await expect(rows).toHaveCount(Math.min(40, total));
    }
  }
  // the periods: what the API counted, and units only from the sample
  for (const p of data.periods) {
    await expect(page.getByTestId(`transparency-tally-${p.period}`)).toHaveAttribute(
      "data-settled",
      String(p.settled),
    );
    await expect(page.getByTestId(`transparency-tally-${p.period}-units`)).toHaveCount(
      p.units === null ? 0 : 1,
    );
  }
  if (data.periods.every((p) => p.published === 0))
    await expect(page.getByText(t.transparency.published.none).first()).toBeVisible();
  // the days without picks, why, and the list of days under a finger
  if (data.days.without > 0) {
    await expect(page.getByTestId("transparency-days-summary")).toContainText(
      String(data.days.without),
    );
    for (const [reason, n] of Object.entries(data.days.reasons))
      if (n > 0) await expect(page.getByTestId(`transparency-reason-${reason}`)).toBeVisible();
    const list = page.getByTestId("transparency-day-list");
    await list.locator("summary").click();
    await expect(list.getByTestId("transparency-day")).toHaveCount(data.days.items.length);
  }
  if (data.markets.length === 0)
    await expect(page.getByTestId("transparency-markets-none")).toBeVisible();
  await expect(page.getByTestId("transparency-line-value-version")).toBeVisible();
  if (data.line_value.n === 0)
    await expect(page.getByTestId("transparency-line-value-none")).toBeVisible();
  for (const f of data.forecasts) {
    await expect(page.getByTestId(`transparency-forecast-state-${f.market}`)).toHaveText(
      f.state === "CALIBRATED"
        ? t.transparency.forecast.calibrated
        : t.transparency.forecast.uncalibrated,
    );
    await expect(page.getByTestId(`transparency-bins-${f.market}`)).toHaveCount(
      f.state === "CALIBRATED" && f.bins.length > 0 ? 1 : 0,
    );
  }
  if (data.evaluation.pairs > 0)
    await expect(page.getByTestId("transparency-evaluation-summary")).toContainText(
      String(data.evaluation.pairs),
    );
  await expect(page.getByTestId("transparency-evaluation-qualified")).toContainText(
    String(data.evaluation.qualified),
  );
  expect(await page.getByTestId("transparency-page").innerText()).not.toMatch(NEVER_SAID[lang()]);
  // a day without picks leads there (Picks, today) - once the day is decided, not while it is still being read
  await open(page, w, "/picks");
  const empty = page.getByTestId("no-pick");
  if ((await empty.count()) > 0 && (await empty.getAttribute("data-state")) === "none") {
    await empty.getByTestId("transparency-link").click();
    await expect(page).toHaveURL(/\/transparency$/);
    await settle(page);
    await assertClean(page, w);
  } else {
    note(test.info(), "today's set is not an empty decided day: its link is not on screen");
  }
});
