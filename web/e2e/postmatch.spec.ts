/**
 * Postpartido (plan UX, B4; section 31), in the browser against the API, on QA's finished match (seed_b4.py on fbi_qa_b4p: «QA Bambú 2-1 QA
 * Cedro», twenty hours ago) with PrediGol's three published picks settled - one won and one lost with their post-mortem's facts, one lost
 * with no analysis yet - the forecast written before kick-off and a news item first published after it; and a reader account the test makes,
 * with two saved picks written into the QA database (E2E_DATABASE_URL), then deletes:
 *
 * * the finished match opens on its Postpartido;
 * * «Lo que guardaste»: each saved pick with its result, the price (the reader's own when they gave one) and its units;
 * * under each published pick, why it ended as it did - the facts of the match in words, each «A favor» or «En contra», or that the
 *   analysis is written the night after - and never what the post-mortem judges;
 * * the forecast against the result in three markets, and the news after the whistle;
 * * the reading's way to the Postpartido, and a settled pick in Mis picks opening its match there;
 * * on a 320 px phone nothing goes sideways; axe (WCAG 2.2 A and AA) on the tab.
 *
 * Run with E2E_POSTMATCH=1 against the QA stack with QA_POSTMATCH=1.
 */
import { execFileSync } from "node:child_process";
import AxeBuilder from "@axe-core/playwright";
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
const PASSWORD = "Final-whistle-at-nine-28"; // gitleaks:allow - a QA account's password, made and deleted here
const PHONE = { width: 320, height: 720 };
const DESK = { width: 1440, height: 900 };
const FIXTURE = 97240001; // seed_b4.py's provider id
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const t = L.es;

function sql(query: string): string {
  return execFileSync("psql", [DB, "-v", "ON_ERROR_STOP=1", "-qAt", "-c", query], {
    stdio: "pipe",
  })
    .toString()
    .trim();
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(admin: APIRequestContext): Promise<{ id: number; email: string }> {
  const email = `e2e.postmatch.${Date.now()}@predigol.local`;
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
  await expect(gate.or(page.getByTestId("home-page"))).toBeVisible({ timeout: 30_000 });
  if (await gate.isVisible()) {
    for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
      await gate.getByTestId(`consent-${kind}`).check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
  }
}

/** The seeded match and its published picks, from the QA database. */
function world(): { fixture: number; picks: Record<string, number> } {
  const fixture = Number(
    sql(`SELECT id FROM core.fixtures WHERE provider_fixture_id = ${FIXTURE}`),
  );
  expect(
    fixture,
    "QA's finished match is there (the stack with QA_POSTMATCH=1: seed_b4.py)",
  ).toBeGreaterThan(0);
  const rows = sql(
    `SELECT market_key || ':' || selection || '=' || id FROM picks.picks WHERE fixture_id = ${fixture} ORDER BY id`,
  ).split("\n");
  const picks = Object.fromEntries(rows.map((r) => r.split("=")).map(([k, v]) => [k, Number(v)]));
  return { fixture, picks: picks as Record<string, number> };
}

/** What the reader saved on the match: the published pick that won, and Over 2.5 from the market at their own price. */
function save(user: number, fixture: number, pick: number): void {
  sql(`INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, pick_id, odds, user_odds, snapshot,
         saved_at, status, profit_units, settled_at)
       VALUES (${user}, ${fixture}, '1X2', 'Home', 0, 'predigol_pick', ${pick}, 2.100, NULL, '{}', now() - interval '28 hours',
               'WIN', 1.1000, now() - interval '18 hours'),
              (${user}, ${fixture}, 'OU', 'Over', 2.5, 'market', NULL, 1.950, 2.000, '{}', now() - interval '27 hours',
               'WIN', 1.0000, now() - interval '18 hours')`);
}

function card(page: Page, words: string): Locator {
  return page.getByTestId("prematch-picks").locator("article").filter({ hasText: words });
}

test("a finished match explains what the reader saved and why each published pick ended as it did", async ({
  page,
}) => {
  test.setTimeout(180_000);
  test.skip(!DB, "no E2E_DATABASE_URL: the reader's saved picks cannot be written");
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    const { fixture, picks } = world();
    save(id, fixture, picks["1X2:Home"] ?? 0);
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await page.goto(`/matches/${fixture}`);
    await settle(page);
    await expect(
      page.locator("#match-tab-postmatch"),
      "a finished match opens on its Postpartido",
    ).toHaveAttribute("aria-selected", "true");
    const tab = page.getByTestId("postmatch");

    // What the reader saved, each with its settlement.
    const saved = tab.getByTestId("postmatch-saved-pick");
    await expect(saved).toHaveCount(2);
    await expect(saved.first()).toHaveAttribute("data-status", "WIN");
    await expect(saved.first()).toContainText("Gana QA Bambú");
    await expect(saved.first()).toContainText("a 2,10");
    await expect(saved.first()).toContainText("+1,10");
    await expect(saved.last()).toContainText("a tu cuota de 2,00");

    // Under each published pick, why it ended as it did.
    const won = card(page, "Gana QA Bambú").getByTestId("postmatch-why-pick");
    await expect(won).toHaveAttribute("data-analysed", "true");
    await expect(won).toContainText("Ganó.");
    await expect(won).toContainText("Expulsión en QA Cedro, en el minuto 58.");
    await expect(won).toContainText(
      "Las ocasiones respaldaban esta selección: goles esperados QA Bambú 1,92 – 0,84 QA Cedro.",
    );
    await expect(won.getByTestId("postmatch-why-effect").first()).toHaveAttribute(
      "data-effect",
      "for",
    );
    const lost = card(page, "Menos de 2,5").getByTestId("postmatch-why-pick");
    await expect(lost).toContainText("Perdió.");
    await expect(lost).toContainText("Penalti convertido por QA Cedro, en el minuto 77.");
    await expect(lost.getByTestId("postmatch-why-effect").first()).toHaveAttribute(
      "data-effect",
      "against",
    );
    const waiting = card(page, "Ambos marcan").getByTestId("postmatch-why-pick");
    await expect(waiting).toHaveAttribute("data-analysed", "false");
    await expect(waiting).toContainText(t.match.postmatch.why.notYet);
    const text = await tab.innerText();
    for (const judged of ["MERECIDO", "VARIANZA", "NORMAL_VARIANCE", "unreviewed", "CLV"]) {
      expect(text, `what a post-mortem judges never reaches the page: ${judged}`).not.toContain(
        judged,
      );
    }

    // The forecast against the result: the result and both teams to score matched, the goals at 2.5 did not.
    const reads = tab.getByTestId("forecast-vs-result");
    await expect(reads).toHaveCount(3);
    expect(
      await reads.evaluateAll((els) =>
        els.map((e) => `${e.getAttribute("data-market")}=${e.getAttribute("data-hit")}`),
      ),
    ).toEqual(["1X2=true", "OU=false", "BTTS=true"]);

    // The news first published after the kick-off.
    await expect(tab.getByTestId("postmatch-news")).toContainText(
      "QA Jugador Siete salió lesionado",
    );
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="postmatch"]')
      .withTags(AXE_TAGS)
      .analyze();
    expect(
      axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
      "the Postpartido: axe, WCAG 2.2 A and AA",
    ).toEqual([]);
    await assertClean(page, w);

    // The reading's way to the Postpartido, when the match has a reading.
    const reading = await getJson<{ status: string }>(
      page.request,
      `/api/v1/matches/${fixture}/reading`,
    );
    if (reading.body.status === "ok") {
      await page.locator("#match-tab-analysis").click();
      const to = page.getByTestId("reading-to-postmatch").first();
      await expect(to).toHaveText(t.match.postmatch.fromReading);
      await to.click();
      await expect(page.locator("#match-tab-postmatch")).toHaveAttribute("aria-selected", "true");
    }

    // A settled pick in Mis picks opens its match on the Postpartido.
    await page.goto("/my-picks");
    await settle(page);
    const link = page.getByTestId("my-pick-match").filter({ hasText: "QA Bambú" }).first();
    await expect(link).toHaveAttribute("href", new RegExp(`/matches/${fixture}#postmatch$`));
    await link.click();
    await expect(page.locator("#match-tab-postmatch")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("postmatch-saved")).toBeVisible();
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("on a 320 px phone the Postpartido reads top to bottom and nothing goes sideways", async ({
  page,
}) => {
  test.setTimeout(150_000);
  test.skip(!DB, "no E2E_DATABASE_URL: the reader's saved picks cannot be written");
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    const { fixture, picks } = world();
    save(id, fixture, picks["1X2:Home"] ?? 0);
    await page.setViewportSize(PHONE);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await page.goto(`/matches/${fixture}`);
    await settle(page);
    const tab = page.getByTestId("postmatch");
    await expect(tab.getByTestId("postmatch-saved")).toBeVisible();
    for (const el of await tab.getByTestId("postmatch-why-pick").all()) {
      await el.scrollIntoViewIfNeeded();
      const box = await el.boundingBox();
      expect(box, "the why of a pick on the page").not.toBeNull();
      expect(box!.x + box!.width, "inside the screen").toBeLessThanOrEqual(PHONE.width);
    }
    const order = await tab.evaluate((root) =>
      ["postmatch-saved", "forecast-vs-result", "prematch-picks"].map((id) => {
        const el = root.querySelector(`[data-testid="${id}"]`);
        return el ? el.getBoundingClientRect().top + window.scrollY : -1;
      }),
    );
    expect(order.every((y) => y >= 0)).toBe(true);
    expect(
      [...order].sort((a, b) => a - b),
      "what you saved first, then the forecast, then the picks",
    ).toEqual(order);
    const over = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(over, "nothing sideways").toBeLessThanOrEqual(1);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});
