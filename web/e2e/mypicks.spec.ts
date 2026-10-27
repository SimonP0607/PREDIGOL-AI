/**
 * Mis picks completo (plan UX, B5; section 30), in the browser against the API, on QA's world of B5 (seed_b5.py on fbi_qa_relm: «QA Liga
 * Ñandú» and «QA Copa Andina», 330 finished matches with their results and the close of every third, 8 still to be played) and two reader
 * accounts the test makes, with their saved picks written into the QA database (E2E_DATABASE_URL), then deletes:
 *
 * * reader A, 668 saved picks: «local» and «Más de 2,5» on every finished match, settled by its result, at five prices for the local
 *   (1,40 · 1,85 · 2,40 · 3,20 · 5,50; every eleventh at the reader's own price, 0,15 higher) and three for the goals (1,70 · 1,95 ·
 *   2,10), and «Ambos marcan» on the 8 to come;
 * * reader B, 40 picks of «visitante» on the same matches - never seen by A.
 *
 * «Criterio de terminado: "Todo" completo y paginado en una cuenta de QA con más de 600 picks, filtros y desglose iguales a consultas
 * independientes, el aviso de muestra visible y el CSV solo con datos propios.» Every figure here is checked against SQL written in this
 * file, not the API's. And: no streak anywhere; on a 320 px phone the filters come up from the bottom and nothing goes sideways.
 *
 * Run with E2E_MYPICKS=1 against the QA stack with QA_MYPICKS=1.
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, skipWelcome, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const DB = (process.env["E2E_DATABASE_URL"] ?? "").replace(
  "postgresql+psycopg://",
  "postgresql://",
);
const PASSWORD = "Every-pick-on-the-record-31"; // gitleaks:allow - a QA account's password, made and deleted here
const PHONE = { width: 320, height: 720 };
const DESK = { width: 1440, height: 900 };
const FIRST = 97250000; // seed_b5.py's provider ids: 330 finished matches, then 8 to come
const LAST = 97250337;
const COPA = 97251; // «QA Copa Andina»
const t = L.es;

function sql(query: string): string {
  return execFileSync("psql", [DB, "-v", "ON_ERROR_STOP=1", "-qAt", "-F", "|", "-c", query], {
    stdio: "pipe",
  })
    .toString()
    .trim();
}

function num(query: string): number {
  return Number(sql(query));
}

/** «12 345» / «12.345»: a count as the page writes it, whatever the separator of thousands. */
function digits(text: string): string {
  return text.replace(/[\s.\u00a0\u202f]/g, "");
}

interface Reader {
  id: number;
  email: string;
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(admin: APIRequestContext, tag: string): Promise<Reader> {
  const email = `e2e.mypicks.${tag}.${Date.now()}@predigol.local`;
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

async function remove(admin: APIRequestContext, r: Reader): Promise<void> {
  const res = await sendJson(admin, "POST", `/api/v1/admin/users/${r.id}/anonymise`, {
    confirm: r.email,
  });
  expect([200, 409], `the test's account ${r.id} is deleted`).toContain(res.status);
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

/**
 * A reader signed in over the API (no browser): with the consent gate on (the QA API runs it over the drafts) the reader accepts the
 * current texts once, as global.setup.ts does for the QA accounts - so the test reads the reader's records, not the gate.
 */
async function apiReader(r: Reader): Promise<APIRequestContext> {
  const ctx = await request.newContext({
    baseURL: BASE,
    extraHTTPHeaders: { "x-requested-with": "predigol" },
  });
  const login = await ctx.post("/api/v1/auth/login", {
    data: { email: r.email, password: PASSWORD },
  });
  expect(login.status(), "the reader signs in").toBe(200);
  const who = (await (await ctx.get("/api/v1/auth/me")).json()) as { consents_due?: string[] };
  if (who.consents_due?.length) {
    const state = (await (await ctx.get("/api/v1/me/consents?lang=es")).json()) as {
      purposes: Array<{ kind: string; version: string }>;
    };
    const accepted = await ctx.post("/api/v1/me/consents", {
      data: {
        decisions: state.purposes
          .filter((p) => who.consents_due?.includes(p.kind))
          .map((p) => ({ kind: p.kind, granted: true, version: p.version })),
        locale: "es",
        source: "gate",
      },
    });
    expect(accepted.status(), "the reader accepts the current texts").toBe(200);
  }
  return ctx;
}

/** The world's matches with their order n (0 the most recent finished one) and result. */
const WORLD = `
  SELECT f.id, f.kickoff_at, f.status_group, f.provider_fixture_id - ${FIRST} AS n,
         r.goals_home AS gh, r.goals_away AS ga
    FROM core.fixtures f LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
   WHERE f.provider_fixture_id BETWEEN ${FIRST} AND ${LAST}`;

/** Reader A's 668 picks and reader B's 40, settled by each match's result at the price each counts. */
function save(a: number, b: number): void {
  sql(`
    INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, user_odds, snapshot, saved_at,
                                  status, profit_units, settled_at)
    SELECT who, id, market, selection, line, 'market', odds, own, '{}', kickoff_at - interval '3 hours',
           CASE WHEN won IS NULL THEN 'PENDING' WHEN won THEN 'WIN' ELSE 'LOSS' END,
           CASE WHEN won IS NULL THEN NULL WHEN won THEN COALESCE(own, odds) - 1 ELSE -1 END,
           CASE WHEN won IS NULL THEN NULL ELSE kickoff_at + interval '2 hours' END
      FROM (
        SELECT ${a} AS who, id, kickoff_at, '1X2' AS market, 'Home' AS selection, 0::numeric AS line,
               (ARRAY[1.40, 1.85, 2.40, 3.20, 5.50])[n % 5 + 1]::numeric AS odds,
               CASE WHEN n % 11 = 0 THEN (ARRAY[1.40, 1.85, 2.40, 3.20, 5.50])[n % 5 + 1] + 0.15 END::numeric AS own,
               gh > ga AS won
          FROM (${WORLD}) w WHERE status_group = 'finished'
        UNION ALL
        SELECT ${a}, id, kickoff_at, 'OU', 'Over', 2.5, (ARRAY[1.70, 1.95, 2.10])[n % 3 + 1]::numeric, NULL, gh + ga >= 3
          FROM (${WORLD}) w WHERE status_group = 'finished'
        UNION ALL
        SELECT ${a}, id, kickoff_at, 'BTTS', 'Yes', 0, 2.00, NULL, NULL
          FROM (${WORLD}) w WHERE status_group = 'scheduled'
        UNION ALL
        SELECT ${b}, id, kickoff_at, '1X2', 'Away', 0, 3.10, NULL, ga > gh
          FROM (${WORLD}) w WHERE status_group = 'finished' AND n < 40
      ) p`);
}

/** A's picks, joined as a reader's list reads them - for the conditions of each check. */
function picksOf(user: number): string {
  return `picks.user_picks u
    JOIN core.fixtures f ON f.id = u.fixture_id
    JOIN core.teams th ON th.id = f.home_team_id
    JOIN core.teams ta ON ta.id = f.away_team_id
    JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    JOIN core.competitions c ON c.id = cs.competition_id
   WHERE u.user_id = ${user}`;
}

interface Tally {
  total: number;
  pending: number;
  won: number;
  lost: number;
  settled: number;
  units: number;
}

/** The tally of A's picks under a condition, by SQL: settled = with a stake and not voided (every pick here has one). */
function tally(user: number, where = "true"): Tally {
  const [total, pending, won, lost, settled, units] = sql(
    `SELECT count(*), count(*) FILTER (WHERE u.status = 'PENDING'),
            count(*) FILTER (WHERE u.status IN ('WIN', 'HALF_WIN')), count(*) FILTER (WHERE u.status IN ('LOSS', 'HALF_LOSS')),
            count(*) FILTER (WHERE u.status NOT IN ('PENDING', 'VOID') AND u.profit_units IS NOT NULL),
            coalesce(sum(u.profit_units), 0)
       FROM ${picksOf(user)} AND (${where})`,
  )
    .split("|")
    .map(Number);
  return {
    total: total!,
    pending: pending!,
    won: won!,
    lost: lost!,
    settled: settled!,
    units: units!,
  };
}

interface ApiTally {
  total: number;
  pending: number;
  won: number;
  lost: number;
  half_won: number;
  half_lost: number;
  settled: number;
  units: string | null;
  roi: string | null;
  margin: string | null;
  sample: "counts_only" | "inconclusive" | "conclusive";
}

interface Summary {
  min_sample: number;
  conclusive: number;
  filter: { active: number };
  tally: ApiTally;
  markets: Array<ApiTally & { market: string }>;
  competitions: Array<ApiTally & { competition: { id: number; name: string } }>;
  bands: Array<ApiTally & { band: string }>;
  line_value: { n: number; mean: string | null; positive: string | null; version: string };
  options: { markets: string[]; competitions: Array<{ id: number; name: string }> };
}

function expectTally(api: ApiTally, want: Tally, what: string): void {
  expect(
    {
      total: api.total,
      pending: api.pending,
      won: api.won + api.half_won,
      lost: api.lost + api.half_lost,
      settled: api.settled,
    },
    what,
  ).toEqual({
    total: want.total,
    pending: want.pending,
    won: want.won,
    lost: want.lost,
    settled: want.settled,
  });
  if (want.settled >= 25) {
    expect(Number(api.units), `${what}: units`).toBeCloseTo(want.units, 2);
    expect(Number(api.roi), `${what}: ROI`).toBeCloseTo(want.units / want.settled, 3);
    expect(Number(api.margin), `${what}: margin`).toBeCloseTo(1 / Math.sqrt(want.settled), 3);
    expect(api.sample, `${what}: sample`).toBe(want.settled >= 100 ? "conclusive" : "inconclusive");
  } else {
    expect([api.units, api.roi, api.margin], `${what}: only the counts below 25`).toEqual([
      null,
      null,
      null,
    ]);
    expect(api.sample).toBe("counts_only");
  }
}

/** A minimal CSV reader (RFC 4180: quoted fields, doubled quotes), without the BOM. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  const body = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < body.length; i++) {
    const ch = body[i]!;
    if (quoted) {
      if (ch === '"' && body[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else cell += ch;
  }
  if (cell || row.length) rows.push([...row, cell]);
  return rows;
}

function summaryOf(page: Page): Locator {
  return page.getByTestId("mypicks-summary").locator("xpath=..");
}

test.describe.configure({ mode: "serial" });

test.describe("Mis picks completo (plan UX, B5)", () => {
  let admin: APIRequestContext;
  let a: Reader;
  let b: Reader;
  let copa: number;

  test.beforeAll(async () => {
    expect(
      DB,
      "E2E_DATABASE_URL: the QA database the test writes its readers' picks into",
    ).not.toBe("");
    expect(
      num(
        `SELECT count(*) FROM core.fixtures WHERE provider_fixture_id BETWEEN ${FIRST} AND ${LAST}`,
      ),
      "QA's world of B5 is there (the stack with QA_MYPICKS=1: seed_b5.py)",
    ).toBe(338);
    copa = num(`SELECT id FROM core.competitions WHERE provider_league_id = ${COPA}`);
    admin = await owner();
    a = await account(admin, "a");
    b = await account(admin, "b");
    save(a.id, b.id);
    expect(num(`SELECT count(*) FROM picks.user_picks WHERE user_id = ${a.id}`)).toBe(668);
    expect(num(`SELECT count(*) FROM picks.user_picks WHERE user_id = ${b.id}`)).toBe(40);
  });

  test.afterAll(async () => {
    if (a) await remove(admin, a);
    if (b) await remove(admin, b);
    await admin?.dispose();
  });

  test("«Todo» is every one of the 668 picks: the API's pages hold each once, and the list walks them by the day of the match", async ({
    page,
  }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true });
    await signIn(page, a.email);
    // the API, page by page: each of A's records once, none of B's
    const seen: number[] = [];
    let cursor: string | null = null;
    for (let i = 0; i < 20; i++) {
      const res: {
        status: number;
        body: { data: Array<{ id: number }>; meta: { total: number; next_cursor: string | null } };
      } = await getJson(
        page.request,
        `/api/v1/me/picks?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      expect(res.status).toBe(200);
      expect(res.body.meta.total).toBe(668);
      seen.push(...res.body.data.map((p) => p.id));
      cursor = res.body.meta.next_cursor;
      if (!cursor) break;
    }
    const mine = sql(`SELECT id FROM picks.user_picks WHERE user_id = ${a.id} ORDER BY id`)
      .split("\n")
      .map(Number);
    expect(
      [...seen].sort((x, y) => x - y),
      "every record of the reader, each once",
    ).toEqual(mine);

    await page.goto("/my-picks");
    await settle(page);
    const list = page.getByTestId("saved-picks");
    await expect(page.getByTestId("mypicks-summary-counts")).toContainText("668");
    await expect(page.getByTestId("saved-picks-more-count")).toHaveText(/^25 de 668$/);
    const more = page.getByTestId("saved-picks-more");
    for (let i = 0; i < 40 && (await more.count()) > 0; i++) {
      await more.click();
      await expect(more.or(page.getByTestId("saved-picks-all"))).toBeEnabled();
    }
    await expect(page.getByTestId("saved-picks-all")).toHaveText(
      t.records.mine.picks.allShown_other.replace("{n}", "668"),
      { useInnerText: true },
    );
    await expect(list.getByTestId("saved-pick")).toHaveCount(668);
    // the days go newest first, each once, under its own heading
    const days = await list
      .getByTestId("saved-picks-day")
      .evaluateAll((els) => els.map((e) => e.getAttribute("data-day") ?? ""));
    expect(days.length).toBe(new Set(days).size);
    expect([...days].sort().reverse()).toEqual(days);
    expect(days.length).toBe(
      num(
        `SELECT count(DISTINCT (f.kickoff_at AT TIME ZONE 'America/Bogota')::date) FROM ${picksOf(a.id)}`,
      ),
    );
    await assertClean(page, w);
  });

  test("the totals, the filters and the breakdown equal independent queries", async ({ page }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true });
    await signIn(page, a.email);
    // the names made plain in both cases (a database whose lower() leaves «Ñ» as it is still compares them)
    const lima =
      "translate(lower(th.name || ' ' || ta.name || ' ' || c.name), 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunaeiouun')";
    const cases: Array<[string, string, string]> = [
      ["no filter", "", "true"],
      ["won", "result=won", "u.status IN ('WIN', 'HALF_WIN')"],
      [
        "lost OU",
        "result=lost&market=OU",
        "u.status IN ('LOSS', 'HALF_LOSS') AND u.market_key = 'OU'",
      ],
      ["pending", "result=pending", "u.status = 'PENDING'"],
      ["Copa Andina", `competition=${copa}`, `c.id = ${copa}`],
      ["5 or more", "band=5%2B", "COALESCE(u.user_odds, u.odds) >= 5"],
      [
        "1.50 to 2",
        "band=1.5-2",
        "COALESCE(u.user_odds, u.odds) >= 1.5 AND COALESCE(u.user_odds, u.odds) < 2",
      ],
      ["the reader's own", "origin=mine", "u.origin = 'market'"],
      ["PrediGol's", "origin=predigol", "u.origin = 'predigol_pick'"],
      [
        "the last 30 days",
        `since=${sql(`SELECT ((now() AT TIME ZONE 'America/Bogota')::date - 30)::text`)}&until=${sql(`SELECT ((now() AT TIME ZONE 'America/Bogota')::date)::text`)}`,
        "(f.kickoff_at AT TIME ZONE 'America/Bogota')::date BETWEEN (now() AT TIME ZONE 'America/Bogota')::date - 30 AND (now() AT TIME ZONE 'America/Bogota')::date",
      ],
      ["«nandu», without its accents", "q=nandu", `${lima} LIKE '%nandu%'`],
      ["«ÑUÑOA» in capitals", `q=${encodeURIComponent("ÑUÑOA")}`, `${lima} LIKE '%nunoa%'`],
      [
        "won, 2 to 3, in the Copa",
        `result=won&band=2-3&competition=${copa}`,
        `u.status IN ('WIN', 'HALF_WIN') AND COALESCE(u.user_odds, u.odds) >= 2 AND COALESCE(u.user_odds, u.odds) < 3 AND c.id = ${copa}`,
      ],
    ];
    for (const [name, query, where] of cases) {
      const want = tally(a.id, where);
      const s = await getJson<{ data: Summary }>(
        page.request,
        `/api/v1/me/picks/summary${query ? `?${query}` : ""}`,
      );
      expect(s.status, name).toBe(200);
      expectTally(s.body.data.tally, want, name);
      const listed = await getJson<{ meta: { total: number } }>(
        page.request,
        `/api/v1/me/picks?limit=1${query ? `&${query}` : ""}`,
      );
      expect(listed.body.meta.total, `${name}: the list counts the same records`).toBe(want.total);
    }
    // the breakdown: each kind of bet, league and odds range, by SQL
    const all = (await getJson<{ data: Summary }>(page.request, "/api/v1/me/picks/summary")).body
      .data;
    for (const m of all.markets)
      expectTally(m, tally(a.id, `u.market_key = '${m.market}'`), `market ${m.market}`);
    expect(all.markets.map((m) => m.market).sort()).toEqual(["1X2", "BTTS", "OU"]);
    for (const c of all.competitions)
      expectTally(c, tally(a.id, `c.id = ${c.competition.id}`), `league ${c.competition.name}`);
    expect(all.competitions.length).toBe(2);
    const bounds: Record<string, string> = {
      "lt1.5": "p < 1.5",
      "1.5-2": "p >= 1.5 AND p < 2",
      "2-3": "p >= 2 AND p < 3",
      "3-5": "p >= 3 AND p < 5",
      "5+": "p >= 5",
    };
    for (const band of all.bands)
      expectTally(
        band,
        tally(a.id, bounds[band.band]!.replaceAll("p", "COALESCE(u.user_odds, u.odds)")),
        `odds ${band.band}`,
      );
    expect(all.bands.reduce((n, x) => n + x.total, 0)).toBe(668);

    // and the page: the panel's filters narrow the list, its totals and its breakdown together
    await page.goto("/my-picks");
    await settle(page);
    const panel = page.getByTestId("mypicks-filters-panel");
    await expect(panel).toBeVisible();
    await panel
      .getByTestId("mypicks-filter-result")
      .getByRole("button", { name: t.records.mine.filters.result.lost })
      .click();
    await panel.getByTestId("mypicks-filter-market").selectOption("OU");
    const lostOu = tally(a.id, "u.status IN ('LOSS', 'HALF_LOSS') AND u.market_key = 'OU'");
    const summary = summaryOf(page);
    await expect(page.getByTestId("mypicks-summary")).toContainText(
      t.records.mine.summary.filtered,
    );
    await expect
      .poll(async () => digits(await page.getByTestId("mypicks-summary-counts").innerText()))
      .toContain(`${lostOu.total}`);
    await expect(page.getByTestId("saved-picks-more-count")).toHaveText(
      new RegExp(`^25 de ${lostOu.total}$`),
    );
    await expect(page.getByTestId("saved-pick").first()).toHaveAttribute("data-status", "LOSS");
    await summary.getByTestId("mypicks-breakdown").locator("summary").click();
    const rows = summary.getByTestId("mypicks-breakdown-market");
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText(`${lostOu.total} · ${lostOu.settled}`);
    await expect(summary.getByTestId("mypicks-breakdown-competition")).toHaveCount(2);
    // a filter nothing matches says so, and puts the list back with one tap
    await panel
      .getByTestId("mypicks-filter-origin")
      .getByRole("button", { name: t.records.mine.filters.origin.predigol })
      .click();
    await expect(page.getByText(t.records.mine.filters.empty)).toBeVisible();
    await page.getByTestId("mypicks-empty-reset").click();
    await expect(page.getByTestId("saved-picks-more-count")).toHaveText(/^25 de 668$/);
    // the search goes without accents and finds the league and the teams
    await page.getByTestId("mypicks-search").fill("nandu");
    const nandu = tally(a.id, `${lima} LIKE '%nandu%'`);
    await expect(page.getByTestId("saved-picks-more-count")).toHaveText(
      new RegExp(`^25 de ${nandu.total}$`),
    );
    await assertClean(page, w);
  });

  test("the sample: the margin from 25, the notice below 100, and only the counts below 25", async ({
    page,
  }) => {
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true });
    await signIn(page, a.email);
    await page.goto("/my-picks");
    await settle(page);
    const sample = page.getByTestId("mypicks-summary-sample");
    const everything = tally(a.id);
    await expect(sample).toHaveAttribute("data-sample", "conclusive");
    await expect(sample).toHaveText(
      t.records.sample.conclusive_other
        .replace("{pts}", `${Math.round(100 / Math.sqrt(everything.settled))}`)
        .replace("{n}", `${everything.settled}`),
    );
    await expect(page.getByTestId("mypicks-summary-units")).toBeVisible();
    // 5 or more: the 66 locals at 5,50 - a margin, and the sample does not allow a conclusion yet
    const panel = page.getByTestId("mypicks-filters-panel");
    await panel
      .getByTestId("mypicks-filter-band")
      .getByRole("button", { name: t.records.mine.filters.band["5+"] })
      .click();
    const five = tally(a.id, "COALESCE(u.user_odds, u.odds) >= 5");
    expect(five.settled).toBeGreaterThanOrEqual(25);
    expect(five.settled).toBeLessThan(100);
    await expect(sample).toHaveAttribute("data-sample", "inconclusive");
    await expect(sample).toHaveText(
      t.records.sample.inconclusive_other
        .replace("{pts}", `${Math.round(100 / Math.sqrt(five.settled))}`)
        .replace("{n}", `${five.settled}`),
    );
    await expect(page.getByTestId("mypicks-summary-roi")).toBeVisible();
    // and only the last 60 days of them: fewer than 25 - the counts, never a return
    const since = sql(`SELECT ((now() AT TIME ZONE 'America/Bogota')::date - 60)::text`);
    await panel.getByTestId("mypicks-filter-since").fill(since);
    const few = tally(
      a.id,
      `COALESCE(u.user_odds, u.odds) >= 5 AND (f.kickoff_at AT TIME ZONE 'America/Bogota')::date >= '${since}'`,
    );
    expect(few.settled).toBeGreaterThan(0);
    expect(few.settled).toBeLessThan(25);
    await expect(sample).toHaveAttribute("data-sample", "counts_only");
    await expect(sample).toHaveText(
      (few.settled === 1 ? t.records.sample.countsOnly_one : t.records.sample.countsOnly_other)
        .replace("{n}", `${few.settled}`)
        .replace("{min}", "25"),
    );
    await expect(page.getByTestId("mypicks-summary-units")).toHaveCount(0);
    await expect(page.getByTestId("mypicks-summary-roi")).toHaveCount(0);
    // never a streak, in the totals or in the recap
    await expect(page.locator("body")).not.toContainText(/racha/i);
    await assertClean(page, w);
  });

  test("the line value: each started pick against its close, and their mean with its definition", async ({
    page,
  }) => {
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true });
    await signIn(page, a.email);
    const close = `JOIN LATERAL (
        SELECT m.p_fair FROM market.market_consensus m
         WHERE m.fixture_id = u.fixture_id AND m.market_key = u.market_key AND m.selection = u.selection AND m.line = u.line
           AND m.devig_method = 'shin' AND m.as_of < f.kickoff_at
         ORDER BY m.as_of DESC LIMIT 1) pc ON true`;
    const [n, mean, positive] = sql(
      `SELECT count(*), avg(COALESCE(u.user_odds, u.odds) * pc.p_fair - 1),
              avg(CASE WHEN COALESCE(u.user_odds, u.odds) * pc.p_fair - 1 > 0 THEN 1.0 ELSE 0.0 END)
         FROM picks.user_picks u JOIN core.fixtures f ON f.id = u.fixture_id ${close}
        WHERE u.user_id = ${a.id} AND f.kickoff_at <= now()`,
    )
      .split("|")
      .map(Number);
    expect(n, "the world gives closes to some started picks").toBeGreaterThanOrEqual(25);
    const s = (await getJson<{ data: Summary }>(page.request, "/api/v1/me/picks/summary")).body
      .data;
    expect(s.line_value.n).toBe(n);
    expect(Number(s.line_value.mean)).toBeCloseTo(mean!, 3);
    expect(Number(s.line_value.positive)).toBeCloseTo(positive!, 3);
    expect(s.line_value.version).toBe("clv-v1");
    // one pick's own: the first started pick with a close in the list's order (the newest kick-off, then the newest record)
    const [fixture, value] = sql(
      `SELECT u.fixture_id, COALESCE(u.user_odds, u.odds) * pc.p_fair - 1
         FROM picks.user_picks u JOIN core.fixtures f ON f.id = u.fixture_id ${close}
        WHERE u.user_id = ${a.id} AND f.kickoff_at <= now()
        ORDER BY f.kickoff_at DESC, u.id DESC LIMIT 1`,
    )
      .split("|")
      .map(Number);
    await page.goto("/my-picks");
    await settle(page);
    const block = page.getByTestId("mypicks-summary-line-value");
    await expect(block).toContainText(t.records.mine.summary.lineValue.title);
    await expect.poll(async () => digits(await block.innerText())).toContain(String(n));
    await expect(block).toContainText("clv-v1");
    const row = page
      .locator(`[data-testid="saved-pick"][data-fixture-id="${fixture}"]`)
      .filter({ has: page.getByTestId("saved-pick-line-value") })
      .first();
    // «Valor de línea −45,8 %»: the sign and one decimal, as the reader's language writes them
    const shown = (await row.getByTestId("saved-pick-line-value").innerText()).replace(
      /[\u00a0\u202f]/g,
      " ",
    );
    const m = /([+−]?)(\d+),(\d) %/.exec(shown);
    expect(m, `a share with its sign in «${shown}»`).not.toBeNull();
    const read = (m![1] === "−" ? -1 : 1) * Number(`${m![2]}.${m![3]}`);
    expect(Math.abs(read - value! * 100)).toBeLessThanOrEqual(0.051);
    // a match still to be played has no close yet: no line value on its pick
    const upcoming = num(
      `SELECT f.id FROM core.fixtures f WHERE f.provider_fixture_id = ${LAST - 7}`,
    );
    await expect(
      page
        .locator(`[data-testid="saved-pick"][data-fixture-id="${upcoming}"]`)
        .getByTestId("saved-pick-line-value"),
    ).toHaveCount(0);
    await assertClean(page, w);
  });

  test("the CSV is the reader's own, under the same filter, in their language - and another reader's records stay out of reach", async ({
    page,
  }) => {
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true });
    await signIn(page, a.email);
    await page.goto("/my-picks");
    await settle(page);
    await page
      .getByTestId("mypicks-filters-panel")
      .getByTestId("mypicks-filter-result")
      .getByRole("button", { name: t.records.mine.filters.result.won })
      .click();
    const won = tally(a.id, "u.status IN ('WIN', 'HALF_WIN')");
    await expect(page.getByTestId("saved-picks-more-count")).toHaveText(
      new RegExp(`^25 de ${won.total}$`),
    );
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("mypicks-export").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^predigol-mis-picks-\d{4}-\d{2}-\d{2}\.csv$/);
    const path = await download.path();
    const rows = parseCsv(readFileSync(path, "utf8"));
    expect(rows[0]).toEqual([
      "guardado",
      "inicio",
      "liga",
      "pais",
      "local",
      "visitante",
      "mercado",
      "seleccion",
      "linea",
      "origen",
      "cuota_mostrada",
      "casa",
      "tu_cuota",
      "resultado",
      "unidades",
      "liquidado",
      "prob_cierre",
      "valor_de_linea",
    ]);
    const lines = rows.slice(1).filter((r) => r.length > 1);
    expect(lines.length, "one line per won pick of the reader").toBe(won.total);
    expect(new Set(lines.map((r) => r[13]))).toEqual(new Set(["Ganado"]));
    // only A's selections: B's «visitante» on the same matches is not there
    expect(lines.filter((r) => r[7] === "Away")).toEqual([]);
    expect(new Set(lines.map((r) => `${r[6]}:${r[7]}`))).toEqual(new Set(["1X2:Home", "OU:Over"]));
    const units = lines.reduce((sum, r) => sum + Number(r[14]), 0);
    expect(units).toBeCloseTo(won.units, 2);

    // reader B: their own CSV, and no hand on A's records
    const other = await apiReader(b);
    const export_ = await other.get("/api/v1/me/picks/export");
    expect(export_.status(), "reader B's own CSV").toBe(200);
    expect(export_.headers()["content-type"]).toContain("text/csv");
    const theirs = parseCsv(await export_.text())
      .slice(1)
      .filter((r) => r.length > 1);
    expect(theirs.length).toBe(40);
    expect(new Set(theirs.map((r) => r[7]))).toEqual(new Set(["Away"]));
    // one of A's picks A could still change (its match is to come): B is refused as for any record not theirs to change
    const aPick = num(
      `SELECT min(id) FROM picks.user_picks WHERE user_id = ${a.id} AND status = 'PENDING'`,
    );
    expect(
      (await sendJson(other, "PATCH", `/api/v1/me/picks/${aPick}`, { user_odds: 9.9 })).status,
    ).toBe(422);
    expect((await sendJson(other, "DELETE", `/api/v1/me/picks/${aPick}`)).status).toBe(422);
    expect(
      num(`SELECT count(*) FROM picks.user_picks WHERE id = ${aPick} AND user_odds IS NULL`),
      "A's pick is still there, unchanged",
    ).toBe(1);
    // the parlays' CSV: the reader has none - its headings, nothing else
    const parlays = parseCsv(await (await page.request.get("/api/v1/me/parlays/export")).text());
    expect(parlays[0]?.[0]).toBe("parlay");
    expect(parlays.slice(1).filter((r) => r.length > 1)).toEqual([]);
    await other.dispose();
    await assertClean(page, w);
  });

  test("on a 320 px phone the filters come up from the bottom, «Ver N picks» shows them, and nothing goes sideways", async ({
    page,
  }) => {
    await page.setViewportSize(PHONE);
    const w = watch(page, { expect401: true });
    await signIn(page, a.email);
    await page.goto("/my-picks");
    await settle(page);
    await expect(page.getByTestId("mypicks-filters-panel")).toBeHidden();
    await page.getByTestId("mypicks-filters-sheet-open").click();
    const sheet = page.getByTestId("mypicks-filters-sheet-sheet");
    await expect(sheet).toBeVisible();
    await sheet
      .getByTestId("mypicks-filter-result")
      .getByRole("button", { name: t.records.mine.filters.result.lost })
      .click();
    const lost = tally(a.id, "u.status IN ('LOSS', 'HALF_LOSS')");
    const show = page.getByTestId("mypicks-filters-sheet-show");
    await expect(show).toHaveText(
      t.records.mine.filters.show_other.replace("{n}", `${lost.total}`),
      {
        useInnerText: true,
      },
    );
    const box = await show.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    await show.click();
    await expect(sheet).toBeHidden();
    await expect(page.getByTestId("mypicks-filters-sheet-count")).toHaveText("1");
    await expect(page.getByTestId("saved-picks-more-count")).toHaveText(
      new RegExp(`^25 de ${lost.total}$`),
    );
    await expect(page.getByTestId("saved-picks-day").first()).toBeVisible();
    await expect(page.getByTestId("mypicks-summary-sample")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/racha/i);
    await assertClean(page, w);
  });
});
