/**
 * Personalisation (plan UX, B2; section 38 and gate G9), in the browser against the API, on two accounts the test makes and
 * deletes - with different favourites:
 *
 * * Partidos opens on each reader's own leagues and teams, counted beside every match of the day; each of their
 *   competitions and each match of a team they follow says why; «Todos» shows every match, the same count for both;
 * * Picks: the day's set and the selections are the same for both - only what each list opens on differs; never «no picks»
 *   while there are some: the others are counted and a tap away;
 * * the reason fits on one line on a 320 px phone, nothing sideways;
 * * a match's «Mercados»: the markets a reader consults most come first, with the rule said; the usual order is a tap
 *   away, and back; a tap on a market records it consulted (market_viewed);
 * * Inicio suggests a league or a team the reader keeps opening, with its reason: «No, gracias» never brings it back,
 *   «Agregar» follows it (the QA database moves the opened matches back to other days: E2E_DATABASE_URL).
 */
import { execFileSync } from "node:child_process";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, skipWelcome, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const DB = (process.env["E2E_DATABASE_URL"] ?? "").replace(
  "postgresql+psycopg://",
  "postgresql://",
);
const PASSWORD = "Sunday-league-at-noon-26"; // gitleaks:allow - a QA account's password, made and deleted here
const PHONE = { width: 320, height: 720 };
const t = L.es;
const USUAL = ["1X2", "OU", "BTTS", "AH", "DC"];

interface Side {
  id: number;
  name: string;
}
interface DayMatch {
  id: number;
  kickoff_at: string;
  status_group: string;
  competition: Side & { is_tracked: boolean };
  home: Side;
  away: Side;
}
interface Favorites {
  leagues: Side[];
  teams: Side[];
  suggested: boolean;
}
interface Personal {
  counted: boolean;
  markets: { first: string[]; views: Array<{ market: string; views: number }>; common: boolean };
  suggestion: { kind: "league" | "team"; id: number; name: string; matches: number } | null;
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(
  admin: APIRequestContext,
  kind: string,
): Promise<{ id: number; email: string }> {
  const email = `e2e.pers.${kind}.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number } }>(admin, "POST", "/api/v1/admin/users", {
    email,
    password: PASSWORD,
    role: "USER",
    language: "es",
    timezone: "America/Bogota",
    must_change_password: false,
  });
  expect(created.status, "the owner creates the test's account").toBe(201);
  return { id: created.body.data.id, email };
}

async function remove(admin: APIRequestContext, id: number, email: string): Promise<void> {
  const r = await sendJson(admin, "POST", `/api/v1/admin/users/${id}/anonymise`, {
    confirm: email,
  });
  expect([200, 409], `the test's account ${id} is deleted`).toContain(r.status);
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
  await skipWelcome(page.request);
  await page.goto("/home");
  const gate = page.getByTestId("consent-gate");
  await expect(gate.or(page.getByTestId("home-today"))).toBeVisible({ timeout: 30_000 });
  if (await gate.isVisible()) {
    for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
      await gate.getByTestId(`consent-${kind}`).check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
  }
}

async function follow(page: Page, leagues: number[], teams: number[]): Promise<Favorites> {
  const res = await page.request.fetch("/api/v1/me/favorites", {
    method: "PUT",
    headers: { "x-requested-with": "predigol", "content-type": "application/json" },
    data: { leagues, teams },
  });
  expect(res.status(), "the favourites saved").toBe(200);
  return (await res.json()) as Favorites;
}

/** Today's matches as Partidos reads them: the reader's day in Bogotá (no daylight saving: -05:00 all year). */
async function todaysMatches(api: APIRequestContext): Promise<DayMatch[]> {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Bogota" }).format(new Date());
  const from = new Date(`${day}T00:00:00-05:00`);
  const to = new Date(from.getTime() + 24 * 3_600_000);
  const out: DayMatch[] = [];
  for (let offset = 0; offset < 2000; offset += 200) {
    const page = await getJson<{ data: DayMatch[]; meta: { total?: number } }>(
      api,
      `/api/v1/matches?kickoff_after=${encodeURIComponent(from.toISOString())}&kickoff_before=${encodeURIComponent(
        to.toISOString(),
      )}&order=asc&limit=200&offset=${offset}`,
    );
    expect(page.status).toBe(200);
    out.push(...page.body.data);
    if (page.body.data.length < 200) break;
  }
  return out;
}

function byCompetition(matches: DayMatch[]): Map<number, DayMatch[]> {
  const out = new Map<number, DayMatch[]>();
  for (const m of matches) {
    if (!m.competition.is_tracked) continue;
    out.set(m.competition.id, [...(out.get(m.competition.id) ?? []), m]);
  }
  return out;
}

async function fits(page: Page, where: string): Promise<void> {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, `${where}: nothing sideways`).toBeLessThanOrEqual(1);
}

function count(label: string | null): number {
  return Number(/(\d+)\s*$/.exec(label ?? "")?.[1] ?? Number.NaN);
}

test("two readers with different favourites: Partidos opens on each one's own, why said, «Todos» and the picks the same for both", async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await owner();
  const a = await account(admin, "a");
  const b = await account(admin, "b");
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const pageA = await ctxA.newPage();
  const pageB = await ctxB.newPage();
  try {
    const wA = watch(pageA, { expect401: true, expectStatus: [403] });
    const wB = watch(pageB, { expect401: true, expectStatus: [403] });
    await signIn(pageA, a.email);
    await signIn(pageB, b.email);
    const today = await todaysMatches(pageA.request);
    const leagues = [...byCompetition(today).entries()].sort((x, y) => y[1].length - x[1].length);
    expect(
      leagues.length,
      "the QA seed puts matches of two followed leagues on today (seed_a9.py)",
    ).toBeGreaterThan(1);
    const [p, q] = [leagues[0]!, leagues[1]!];
    // A team of a third competition playing today, for the reason of a single match (when the day has one).
    const elsewhere = today.find(
      (m) => m.competition.is_tracked && m.competition.id !== p[0] && m.competition.id !== q[0],
    );
    const favA = await follow(pageA, [p[0]], elsewhere ? [elsewhere.home.id] : []);
    const favB = await follow(pageB, [q[0]], []);
    expect(favA.suggested || favB.suggested).toBe(false);

    const mineA = today.filter(
      (m) =>
        m.competition.id === p[0] ||
        (elsewhere ? [m.home.id, m.away.id].includes(elsewhere.home.id) : false),
    ).length;
    const mineB = q[1].length;
    for (const [page, mine, league] of [
      [pageA, mineA, p[1][0]!.competition.name],
      [pageB, mineB, q[1][0]!.competition.name],
    ] as const) {
      await page.goto("/matches");
      await settle(page);
      const scope = page.getByTestId("matches-scope");
      await expect(scope, "chosen favourites: the reader's own first").toHaveAttribute(
        "data-scope",
        "mine",
      );
      expect(count(await page.getByTestId("matches-scope-mine").textContent())).toBe(mine);
      expect(count(await page.getByTestId("matches-scope-all").textContent())).toBe(today.length);
      const groups = page.getByTestId("competition-group");
      await expect(groups.first()).toBeVisible();
      await expect(page.getByTestId("match-row")).toHaveCount(mine);
      const head = groups.filter({ hasText: league }).first();
      await expect(head.getByTestId("competition-why")).toHaveText(t.home.today.whyLeague);
    }
    if (elsewhere) {
      const row = pageA.getByTestId("match-row").filter({ hasText: elsewhere.home.name }).first();
      await expect(row.getByTestId("match-why")).toHaveText(
        t.home.today.whyTeam.replace("{team}", elsewhere.home.name),
      );
    }
    // «Todos»: every match of the day, for either reader
    for (const page of [pageA, pageB]) {
      await page.getByTestId("matches-scope-all").click();
      await expect(page.getByTestId("matches-scope")).toHaveAttribute("data-scope", "all");
      await expect(page.getByTestId("match-row")).toHaveCount(today.length, { timeout: 20_000 });
    }

    // The picks: the same day's set and the same selections for both - personalisation never touches them
    const sameA = await getJson<unknown>(pageA.request, "/api/v1/daily");
    const sameB = await getJson<unknown>(pageB.request, "/api/v1/daily");
    expect(JSON.stringify(sameA.body).replace(/"generated_at":"[^"]*"/g, "")).toBe(
      JSON.stringify(sameB.body).replace(/"generated_at":"[^"]*"/g, ""),
    );
    const boardA = await getJson<{
      data: { picks: Array<{ pick_id: number; competition: Side; home: Side; away: Side }> };
    }>(pageA.request, "/api/v1/picks?hours=168");
    const boardB = await getJson<{ data: { picks: Array<{ pick_id: number }> } }>(
      pageB.request,
      "/api/v1/picks?hours=168",
    );
    expect(boardA.body.data.picks.map((x) => x.pick_id)).toEqual(
      boardB.body.data.picks.map((x) => x.pick_id),
    );
    await pageB.goto("/picks");
    await settle(pageB);
    await expect(pageB.getByTestId("daily-item")).toHaveCount(
      ((sameB.body as { data: { set: { items: unknown[] } | null } }).data.set?.items ?? []).length,
    );
    // the list as the page opens it: the next 24 hours (REVIEW point 13)
    const shown = await getJson<{
      data: { picks: Array<{ competition: Side; home: Side; away: Side }> };
    }>(pageB.request, "/api/v1/picks?hours=24");
    const all = shown.body.data.picks;
    if (all.length > 0) {
      await expect(pageB.getByTestId("picks-scope")).toHaveAttribute("data-scope", "mine");
      const theirs = all.filter((x) => x.competition.id === q[0]).length;
      expect(count(await pageB.getByTestId("picks-scope-mine").textContent())).toBe(theirs);
      expect(count(await pageB.getByTestId("picks-scope-all").textContent())).toBe(all.length);
      if (theirs === 0) {
        const empty = pageB.getByTestId("picks-mine-empty");
        await expect(empty, "never «no picks» while there are some").toContainText(
          String(all.length),
        );
        await empty.getByTestId("picks-mine-see-all").click();
      } else {
        await expect(pageB.getByTestId("pick-why").first()).toHaveText(t.home.today.whyLeague);
        await pageB.getByTestId("picks-scope-all").click();
      }
      await expect(pageB.getByTestId("picks-scope")).toHaveAttribute("data-scope", "all");
      await expect(pageB.getByTestId("pick-card").first()).toBeVisible();
    } else {
      test.info().annotations.push({
        type: "data",
        description: "no selection in the window: Picks' lists not compared",
      });
    }
    await assertClean(pageA, wA);
    await assertClean(pageB, wB);
  } finally {
    await ctxA.close();
    await ctxB.close();
    await remove(admin, a.id, a.email);
    await remove(admin, b.id, b.email);
    await admin.dispose();
  }
});

test("on a 320 px phone the reason fits on one line and nothing goes sideways", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "phone");
  try {
    await page.setViewportSize(PHONE);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    const today = await todaysMatches(page.request);
    const leagues = [...byCompetition(today).entries()].sort((x, y) => y[1].length - x[1].length);
    expect(leagues.length).toBeGreaterThan(0);
    const league = leagues[0]!;
    const other = today.find((m) => m.competition.is_tracked && m.competition.id !== league[0]);
    // the longest team name of the day, for the hardest line
    const team = other
      ? [other.home, other.away].sort((x, y) => y.name.length - x.name.length)[0]!
      : null;
    await follow(page, [league[0]], team ? [team.id] : []);
    await page.goto("/matches");
    await settle(page);
    const chips = page.locator('[data-testid="competition-why"], [data-testid="match-why"]');
    await expect(chips.first()).toBeVisible();
    for (const chip of await chips.all()) {
      const box = await chip.boundingBox();
      expect(box, "a chip on the page").not.toBeNull();
      expect(box!.height, "one line").toBeLessThanOrEqual(24);
      expect(box!.x + box!.width, "inside the screen").toBeLessThanOrEqual(PHONE.width);
    }
    await fits(page, "Partidos");
    await page.goto("/picks");
    await settle(page);
    await fits(page, "Picks");
    for (const chip of await page.getByTestId("pick-why").all()) {
      expect((await chip.boundingBox())?.height ?? 0, "one line").toBeLessThanOrEqual(24);
    }
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("a match's Mercados put the reader's most consulted first, say the rule, and go back to the usual order", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "markets");
  try {
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    const best = await getJson<{
      data: { fixtures: Array<{ fixture_id: number; kickoff_at: string }> };
    }>(page.request, "/api/v1/odds/best?hours=72&market=1X2");
    const fixture = best.body.data.fixtures.find(
      (f) => Date.parse(f.kickoff_at) > Date.now() + 30 * 60_000,
    );
    expect(fixture, "seed_football.py puts upcoming matches with prices in QA").toBeTruthy();
    const match = fixture!.fixture_id;
    const sent = await sendJson<{ recorded: number }>(page.request, "POST", "/api/v1/events", {
      events: [
        ...Array.from({ length: 3 }, () => ({
          name: "market_viewed",
          props: { market: "OU", match_id: match },
        })),
        ...Array.from({ length: 2 }, () => ({
          name: "market_viewed",
          props: { market: "BTTS", match_id: match },
        })),
        { name: "market_viewed", props: { market: "DC", match_id: match } },
      ],
    });
    expect(sent.body.recorded, "the QA API measures (FBI_PRODUCT_EVENTS=on)").toBe(6);
    const personal = await getJson<Personal>(page.request, "/api/v1/me/personal");
    expect(personal.body.markets.first).toEqual(["OU", "BTTS"]);

    const events: Array<{ name: string; props: Record<string, unknown> }> = [];
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().endsWith("/api/v1/events"))
        events.push(...((req.postDataJSON() as { events?: typeof events } | null)?.events ?? []));
    });
    await page.goto(`/matches/${match}`);
    await page.getByRole("tab", { name: t.match.tabs.markets }).click();
    await settle(page);
    const grid = page.getByTestId("markets-grid").first();
    await expect(grid).toBeVisible();
    const present = await grid
      .locator("[data-market]")
      .evaluateAll((els) => els.map((e) => e.getAttribute("data-market")));
    const mine = ["OU", "BTTS"].filter((m) => present.includes(m));
    const note = page.getByTestId("markets-order");
    await expect(note).toHaveAttribute("data-order", "mine");
    await expect(note).toContainText("Primero, los mercados que más consultas");
    await expect(note).toContainText("(3)");
    if (mine.length > 0) {
      await expect(grid.locator("[data-market]").first()).toHaveAttribute("data-market", mine[0]!);
    }
    await page.getByTestId("markets-order-usual").click();
    await expect(note).toHaveAttribute("data-order", "usual");
    await expect(note).toContainText(t.match.markets.order.usual);
    const usual = USUAL.filter((m) => present.includes(m));
    await expect(grid.locator("[data-market]").first()).toHaveAttribute("data-market", usual[0]!);
    await page.getByTestId("markets-order-mine").click();
    await expect(note).toHaveAttribute("data-order", "mine");

    // a tap on a market is that market consulted: once per visit, the catalog's properties only
    const cell = grid.locator("[data-market]").first();
    const market = (await cell.getAttribute("data-market")) ?? "";
    const price = cell.getByTestId("odds-add-to-parlay").first();
    await price.click();
    await expect(price).toHaveAttribute("aria-pressed", "true");
    await price.click();
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect
      .poll(() => events.filter((e) => e.name === "market_viewed").map((e) => e.props), {
        timeout: 10_000,
      })
      .toEqual([{ market, match_id: match }]);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

/** Moves all but the newest of the reader's latest «match_opened» back one day each (their subject found by a marker). */
function spreadOverDays(marker: number): void {
  const sql = `
    WITH me AS (SELECT subject FROM customer.product_events
                 WHERE name = 'search_submitted' AND (props->>'results')::int = ${marker}
                   AND at > now() - interval '10 minutes' ORDER BY id DESC LIMIT 1),
         opened AS (SELECT e.id, row_number() OVER (ORDER BY e.id DESC) AS n FROM customer.product_events e, me
                     WHERE e.subject = me.subject AND e.name = 'match_opened' AND e.at > now() - interval '10 minutes')
    UPDATE customer.product_events p SET at = p.at - make_interval(days => (opened.n - 1)::int)
      FROM opened WHERE p.id = opened.id`;
  execFileSync("psql", [DB, "-v", "ON_ERROR_STOP=1", "-qAt", "-c", sql], { stdio: "pipe" });
}

test("Inicio suggests what a reader keeps opening: «No, gracias» never brings it back, «Agregar» follows it", async ({
  browser,
}) => {
  test.skip(!DB, "no E2E_DATABASE_URL: the opened matches cannot be spread over days");
  test.setTimeout(200_000);
  const admin = await owner();
  const no = await account(admin, "no");
  const yes = await account(admin, "yes");
  const ctxNo = await browser.newContext();
  const ctxYes = await browser.newContext();
  try {
    for (const [ctx, who] of [
      [ctxNo, no],
      [ctxYes, yes],
    ] as const) {
      const page = await ctx.newPage();
      const w = watch(page, { expect401: true, expectStatus: [403] });
      await signIn(page, who.email);
      const today = await todaysMatches(page.request);
      const leagues = [...byCompetition(today).entries()].sort((x, y) => y[1].length - x[1].length);
      expect(leagues.length).toBeGreaterThan(1);
      const [mineL, opened] = [leagues[1]!, leagues[0]!];
      expect(opened[1].length, "three matches of one league to open").toBeGreaterThanOrEqual(3);
      await follow(page, [mineL[0]], []);
      const marker = 1 + Math.floor(Math.random() * 999);
      const r = await sendJson<{ recorded: number }>(page.request, "POST", "/api/v1/events", {
        events: [
          { name: "search_submitted", props: { results: marker } },
          ...opened[1]
            .slice(0, 3)
            .map((m) => ({ name: "match_opened", props: { origin: "matches", match_id: m.id } })),
        ],
      });
      expect(r.body.recorded).toBe(4);
      spreadOverDays(marker);
      const personal = await getJson<Personal>(page.request, "/api/v1/me/personal");
      const s = personal.body.suggestion;
      expect(s, "three matches on three days outside what the reader follows").not.toBeNull();
      await page.goto("/home");
      await settle(page);
      const card = page.getByTestId("suggestion-card");
      await expect(card).toBeVisible();
      await expect(card).toHaveAttribute("data-id", String(s!.id));
      await expect(card.getByTestId("suggestion-reason")).toContainText(String(s!.matches));
      await expect(card).toContainText(s!.name);
      if (who === no) {
        await card.getByTestId("suggestion-dismiss").click();
        await expect(card).toHaveCount(0);
        await page.reload();
        await settle(page);
        await expect(
          page.getByTestId("suggestion-card"),
          "dismissed: it never comes back",
        ).toHaveCount(0);
        expect(
          (await getJson<Personal>(page.request, "/api/v1/me/personal")).body.suggestion,
        ).toBeNull();
      } else {
        await card.getByTestId("suggestion-add").click();
        await expect(card).toHaveCount(0);
        const favs = await getJson<Favorites>(page.request, "/api/v1/me/favorites");
        const ids =
          s!.kind === "league"
            ? favs.body.leagues.map((x) => x.id)
            : favs.body.teams.map((x) => x.id);
        expect(ids, "followed once confirmed").toContain(s!.id);
        expect(
          favs.body.leagues.map((x) => x.id),
          "nothing they had disappears",
        ).toContain(mineL[0]);
      }
      await assertClean(page, w);
    }
  } finally {
    await ctxNo.close();
    await ctxYes.close();
    await remove(admin, no.id, no.email);
    await remove(admin, yes.id, yes.email);
    await admin.dispose();
  }
});
