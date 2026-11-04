/**
 * The real test's journey, in QA first (plan UX, A16; section 45): the sixteen steps of a reader the owner invites, on ONE
 * account from its invitation to its recovery, on a 390 px phone with touch and in Spanish - what the owner's run in
 * production (P10, backend/docs/owner/PRUEBA_REAL_A16.md) goes through, proven here before. Each step is a test.step named
 * as on the owner's sheet, so a failure says which step broke; nothing scrolls sideways on any of them.
 *
 * Needs the QA stack with self-service and the QA messenger (api-up.sh QA_SELF_SERVICE=1 QA_MESSENGER=1; E2E_MAIL_SINK = its
 * folder, where each e-mail is a file instead of leaving) and QA's consent gate on its drafts (the default); skipped otherwise.
 * The QA seeds give every step something real to show: seed_football.py the upcoming matches with prices (the parlay, the saved
 * pick), seed_a9.py today's match of a suggested league and a result, seed_a10.py its news. PrediGol has no pick in QA, so step 7
 * checks the day without picks and its reason - never a made-up pick.
 *
 * Steps 15 (a real phone) and 16 (the installed app) are the owner's: here the journey runs at 390 px with touch (and in WebKit,
 * the engine of every iPhone browser, in the journey-webkit project) and pwa.spec.ts proves the worker on the production build.
 * The account is deleted at the end - anonymised, the console's own way - whatever happened.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Browser,
  type Locator,
  type Page,
} from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, watch, type Watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const SINK = process.env["E2E_MAIL_SINK"] ?? "";
const SAME_SITE = { "x-requested-with": "predigol" };
const CHOSEN = "Tarde-de-futbol-con-amigos-26"; // gitleaks:allow - the password the invited QA reader chooses; deleted here
const RENEWED = "Noche-de-clasico-en-el-estadio-26"; // gitleaks:allow - its new password after the recovery; deleted here
const WRONG = "Esta-no-es-la-clave-de-nadie-26"; // gitleaks:allow - a wrong password, on purpose
const ANSWER = "Gracias por avisar: ya lo revisamos y vuelve a verse bien.";
const t = L.es;
/** Plan UX, section 19 and gate G8: from the invitation's link to the first value. */
const ONBOARDING_LIMIT_MS = 90_000;
const SIX_TABS = ["summary", "analysis", "stats", "markets", "lineups", "news"] as const;

interface Mail {
  to: string;
  template: string;
  text: string;
  at: string;
}

interface Today {
  data: {
    matches: {
      data: Array<{
        fixture_id: number;
        status_group: string;
        competition: { name: string };
        home: { id: number; name: string };
      }>;
    };
    no_pick: { data: { state: string; reason: string | null } };
  };
}

interface PricedFixture {
  fixture_id: number;
  kickoff_at: string;
  home: { id: number };
  away: { id: number };
}

interface AdminTicket {
  id: number;
  user_id: number;
  category: string;
  context: { route?: string; device?: string; pwa?: boolean } | null;
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function anonymous(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, extraHTTPHeaders: SAME_SITE });
}

async function selfService(): Promise<boolean> {
  const api = await anonymous();
  const r = await getJson<{ self_service: boolean }>(api, "/api/v1/auth/options");
  await api.dispose();
  return r.status === 200 && r.body.self_service;
}

/** The owner's console, at a desk, in its account's language. */
async function desk(browser: Browser): Promise<Page> {
  const ctx = await browser.newContext({
    storageState: statePath("admin"),
    viewport: { width: 1440, height: 900 },
    locale: "en-GB",
  });
  return ctx.newPage();
}

/** The e-mail the QA messenger wrote for this address and template since `since`, waiting for it a while. */
async function mailFor(to: string, template: string, since: number): Promise<Mail> {
  let found: Mail | undefined;
  await expect(async () => {
    found = readdirSync(SINK)
      .filter((f) => f.endsWith(".json"))
      .map((f) => JSON.parse(readFileSync(join(SINK, f), "utf8")) as Mail)
      .filter((m) => m.to === to && m.template === template && Date.parse(m.at) >= since)
      .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))[0];
    expect(found, `an e-mail "${template}" to ${to} in ${SINK}`).toBeTruthy();
  }).toPass({ timeout: 90_000, intervals: [1_000] });
  return found as Mail;
}

/** The page and the token of an e-mail's link: the token travels in the fragment, never in a URL a server sees. */
function linkOf(mail: Mail, path: "/activate" | "/reset-password"): string {
  const m = new RegExp(`https?://\\S+?${path}#t=([A-Za-z0-9_-]{43})\\b`).exec(mail.text);
  expect(m, `the e-mail carries a ${path} link`).toBeTruthy();
  return `${path}#t=${m?.[1] ?? ""}`;
}

/** Nothing scrolls sideways: a phone never pans (step 15 of the real test, here at the project's width). */
async function fits(page: Page, where: string): Promise<void> {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(
    over,
    `${where}: nothing sideways at ${page.viewportSize()?.width ?? "?"} px`,
  ).toBeLessThanOrEqual(1);
}

/** «Más» on the phone's bar, then one of its rows: two taps (plan UX, A15). */
async function more(page: Page, row: string): Promise<void> {
  await page.getByTestId("tab-more").click();
  const sheet = page.getByTestId("more-sheet");
  await expect(sheet).toBeVisible();
  await sheet.getByTestId(row).click();
  await expect(sheet).toHaveCount(0);
}

/**
 * A navigation that waits for the document, not for the "load" event: in WebKit on the QA dev server that event now and then
 * never fires (a page that is already drawn and working), so every step waits for its own element instead.
 */
async function go(page: Page, url: string): Promise<void> {
  await page.goto(url, { waitUntil: "domcontentloaded" });
}

async function signIn(page: Page, email: string, password: string): Promise<void> {
  if (!new URL(page.url()).pathname.startsWith("/login")) await go(page, "/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByTestId("login-submit").click();
}

/**
 * A team that plays later today in a suggested league: the home side of the QA seed's match of «QA Primera A»
 * (seed_a9.py) - its name to search in «Tu fútbol», its match to open.
 */
async function todaysTeam(
  api: APIRequestContext,
): Promise<{ fixture: number; id: number; name: string }> {
  const today = await getJson<Today>(api, "/api/v1/today");
  expect(today.status).toBe(200);
  const scheduled = today.body.data.matches.data.filter((m) => m.status_group === "scheduled");
  const match = scheduled.find((m) => m.competition.name === "QA Primera A") ?? scheduled[0];
  expect(match, "the QA seed puts a match later today on the board (seed_a9.py)").toBeTruthy();
  return { fixture: match?.fixture_id ?? 0, id: match?.home.id ?? 0, name: match?.home.name ?? "" };
}

/** Two upcoming matches with a 1X2 price and no team in common, kicking off more than half an hour from now. */
async function pricedFixtures(api: APIRequestContext, count: number): Promise<PricedFixture[]> {
  const { body } = await getJson<{ data: { fixtures: PricedFixture[] } }>(
    api,
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

/** A match's Mercados and its first price (the home win): a tap puts it in the parlay, the bookmark beside it saves it. */
async function firstPrice(page: Page, fixtureId: number): Promise<Locator> {
  await go(page, `/matches/${fixtureId}`);
  await page.getByRole("tab", { name: t.match.tabs.markets }).click();
  await settle(page);
  const price = page.getByTestId("selectable-price").first();
  await expect(price).toBeVisible();
  return price;
}

/** The day's set, or the honest sentence and its reason when it is empty (as Inicio and Picks both say it). */
async function dayWithoutPicksOrPicks(page: Page, scope: Locator): Promise<string> {
  const daily = await getJson<{ data: { set: { items: unknown[] } | null } }>(
    page.request,
    "/api/v1/daily",
  );
  const items = daily.body.data.set?.items ?? [];
  if (items.length > 0) {
    await expect(scope.getByTestId("daily-item")).toHaveCount(items.length);
    return `${items.length} picks`;
  }
  const today = await getJson<Today>(page.request, "/api/v1/today");
  const reason = today.body.data.no_pick.data;
  const empty = scope.getByTestId("no-pick");
  await expect(empty).toBeVisible();
  if (reason.state === "reviewing") {
    await expect(empty.getByTestId("no-pick-title")).toHaveText(t.records.noPick.reviewing);
  } else if (reason.reason === "no_matches") {
    await expect(empty.getByTestId("no-pick-title")).toHaveText(t.records.noPick.noMatches);
  } else {
    await expect(empty.getByTestId("no-pick-title")).toHaveText(t.records.noPick.honest);
    const known = reason.reason
      ? (t.records.noPick.reason as Record<string, string>)[reason.reason]
      : undefined;
    if (known) await expect(empty.getByTestId("no-pick-reason")).toContainText(known);
  }
  expect(await empty.innerText(), "a day without picks never says «valor»").not.toMatch(
    /\bvalor\b/i,
  );
  return `no pick (${reason.state}, ${reason.reason ?? "-"})`;
}

test("the real test's sixteen steps on one invited account, on a 390 px phone: from the invitation to the recovery", async ({
  page,
  browser,
}) => {
  test.setTimeout(480_000);
  test.skip(
    !(await selfService()) || SINK === "",
    "needs self-service and the QA messenger (api-up.sh QA_SELF_SERVICE=1 QA_MESSENGER=1, E2E_MAIL_SINK)",
  );
  const admin = await owner();
  const email = `e2e.journey.${Date.now()}@predigol.local`;
  const note = (description: string): void => {
    test.info().annotations.push({ type: "journey", description });
    console.log(`journey (${test.info().project.name}): ${description}`);
  };
  let id = 0;
  // 401 from the anonymous /auth/me and the wrong password; 403 while the consents are owed
  const w = watch(page, { expect401: true, expectStatus: [403] });
  // The reader's tab: a new one after signing out (step 12), see there.
  let tab: Page = page;
  let tw: Watch = w;
  try {
    let link = "";
    let opened = 0;
    let team = { fixture: 0, id: 0, name: "" };
    let fixtures: PricedFixture[] = [];
    let parlayName = "";

    await test.step("1 · Invitación: el dueño invita desde la consola y llega un correo con un enlace de un uso", async () => {
      const consolePage = await desk(browser);
      try {
        await consolePage.goto("/admin/users");
        const since = Date.now();
        await consolePage.getByTestId("invite-user").click();
        const form = consolePage.getByTestId("invite-form");
        await form.getByTestId("invite-email").fill(email);
        await form.getByTestId("invite-alias").fill("Invitada QA");
        await form.getByTestId("invite-language").selectOption("es");
        await form.getByTestId("invite-timezone").selectOption("America/Bogota");
        await form.getByTestId("invite-submit").click();
        await expect(consolePage.getByTestId("users-notice")).toContainText(email);
        const row = consolePage.locator("tr", { hasText: email });
        await expect(row).toContainText(L.en.admin.users.invited);
        id = Number((await row.getAttribute("data-testid"))?.replace("user-row-", ""));
        expect(id).toBeGreaterThan(0);
        const mail = await mailFor(email, "invitation", since);
        link = linkOf(mail, "/activate");
      } finally {
        await consolePage.context().close();
      }
    });

    await test.step("2 · Activación: el enlace abre «Activa tu cuenta» con el idioma y la zona ya puestos y se crea la contraseña", async () => {
      opened = Date.now();
      await go(page, link);
      await expect(page.getByTestId("activate-form")).toBeVisible();
      expect(await page.evaluate(() => window.location.hash), "the token left the address").toBe(
        "",
      );
      await expect(page.getByTestId("account-email")).toHaveValue(email);
      await expect(page.getByTestId("activate-language")).toHaveValue("es");
      await expect(page.getByTestId("activate-timezone")).toHaveValue("America/Bogota");
      await fits(page, "activate");
      await page.getByTestId("new-password").fill(CHOSEN);
      await page.getByTestId("new-password-repeat").fill(CHOSEN);
      await page.getByTestId("activate-submit").click();
    });

    await test.step("3 · Consentimiento: cuatro casillas separadas y sin marcar, sin las que no se avanza; quedan con su versión y su sha256", async () => {
      const gate = page.getByTestId("consent-gate");
      await expect(gate).toBeVisible();
      const kinds = ["terms", "privacy", "age_18", "risk_notice"];
      for (const kind of kinds) await expect(gate.getByTestId(`consent-${kind}`)).not.toBeChecked();
      await expect(gate.getByTestId("consent-submit")).toBeDisabled();
      for (const kind of kinds.slice(0, 3)) await gate.getByTestId(`consent-${kind}`).check();
      await expect(
        gate.getByTestId("consent-submit"),
        "three of four: still no way on",
      ).toBeDisabled();
      await gate.getByTestId("consent-risk_notice").check();
      await fits(page, "the consent gate");
      await gate.getByTestId("consent-submit").click();
      await expect(gate).toHaveCount(0);
      const consents = await getJson<{
        history: Array<{
          kind: string;
          granted: boolean;
          version: string;
          sha256: string;
          source: string;
        }>;
      }>(page.request, "/api/v1/me/consents?lang=es");
      expect(consents.body.history.map((h) => h.kind).sort()).toEqual([...kinds].sort());
      for (const h of consents.body.history) {
        expect(h.granted, h.kind).toBe(true);
        expect(h.version, h.kind).not.toBe("");
        expect(h.sha256, h.kind).toMatch(/^[0-9a-f]{64}$/);
        expect(h.source, `${h.kind}: given at the activation`).toBe("activation");
      }
    });

    await test.step("4 · Bienvenida: «Tu fútbol» y «Qué es PrediGol» en menos de 90 segundos desde el enlace", async () => {
      await expect(page).toHaveURL(/\/welcome$/);
      const welcome = page.getByTestId("welcome");
      await expect(welcome).toHaveAttribute("data-step", "football");
      await expect(page.getByTestId("fav-chosen").getByTestId("fav-chip").first()).toBeVisible();
      team = await todaysTeam(page.request);
      await page.getByTestId("fav-search").fill(team.name.slice(0, 5));
      const result = page.getByTestId("fav-team").filter({ hasText: team.name }).first();
      await expect(result).toBeVisible();
      if ((await result.getAttribute("aria-pressed")) === "false") await result.click();
      await expect(result).toHaveAttribute("aria-pressed", "true");
      await fits(page, "«Tu fútbol»");
      await page.getByTestId("welcome-save").click();
      await expect(welcome).toHaveAttribute("data-step", "about");
      await expect(page.getByTestId("welcome-about").locator("li")).toHaveCount(3);
      await page.getByTestId("welcome-enter").click();
      await expect(page).toHaveURL(/\/home$/);
      await expect(page.getByTestId("home-today")).toHaveAttribute("data-view", "mine");
      const elapsed = Date.now() - opened;
      note(`from the invitation's link to Inicio with its favourites: ${elapsed} ms`);
      expect(elapsed, "gate G8: under 90 seconds").toBeLessThan(ONBOARDING_LIMIT_MS);
      const state = await getJson<{ welcome_due: boolean; onboarded_at: string | null }>(
        page.request,
        "/api/v1/me/onboarding",
      );
      expect(state.body.welcome_due).toBe(false);
      expect(state.body.onboarded_at).not.toBeNull();
    });

    await test.step("2 · (después) El mismo enlace por segunda vez ya no sirve", async () => {
      const again = await (
        await browser.newContext({ viewport: { width: 390, height: 844 } })
      ).newPage();
      const w2 = watch(again, { expect401: true, expectStatus: [410] });
      await go(again, link);
      await expect(again.getByTestId("link-invalid")).toHaveText(t.auth.account.inviteInvalid);
      await assertClean(again, w2);
      await again.context().close();
    });

    await test.step("5 · Inicio: «Hoy en tus ligas» con partidos reales y, si no hay picks, su motivo", async () => {
      const block = page.getByTestId("home-today");
      await expect(block.getByRole("heading", { name: t.home.today.titleMine })).toBeVisible();
      await expect(block.getByTestId("mine-chips")).toContainText(team.name);
      await expect(block.getByTestId("today-row").first()).toBeVisible();
      await expect(block.getByTestId("today-why").first()).toBeVisible();
      note(`Inicio: ${await dayWithoutPicksOrPicks(page, page.getByTestId("daily-set"))}`);
      await settle(page);
      await fits(page, "Inicio");
      await assertClean(page, w);
    });

    await test.step("6 · Partido: sus secciones con su estado y, en Noticias, tarjetas o la frase exacta; un resultado abre su Postpartido", async () => {
      await page
        .getByTestId("home-today")
        .locator(`[data-testid="today-row"][data-fixture="${team.fixture}"]`)
        .first()
        .click();
      await expect(page).toHaveURL(new RegExp(`/matches/${team.fixture}`));
      // before kick-off: six sections (Postpartido once it is over)
      await expect(page.getByRole("tab")).toHaveText(SIX_TABS.map((key) => t.match.tabs[key]));
      for (const key of SIX_TABS) {
        const tab = page.getByRole("tab", { name: t.match.tabs[key] });
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
        await expect(page.locator(`#match-panel-${key}`)).toBeVisible();
        await settle(page);
        await fits(page, `the match's ${key}`);
      }
      const news = page.getByTestId("match-news");
      const cards = news.getByTestId("news-card");
      if ((await cards.count()) > 0) {
        await expect(cards.first().getByTestId("news-status")).toBeVisible();
        note(`Noticias: ${await cards.count()} cards`);
      } else {
        await expect(page.getByTestId("news-empty")).toHaveText(t.match.news.empty);
        note("Noticias: the exact sentence without coverage");
      }
      await assertClean(page, w);
      await page.getByTestId("tab-home").click();
      await expect(page).toHaveURL(/\/home$/);
      const results = page.getByTestId("results-list").getByTestId("today-row");
      await expect(results.first().or(page.getByTestId("results-empty"))).toBeVisible();
      if ((await results.count()) > 0) {
        await results.first().click();
        await expect(page.getByRole("tab", { name: t.match.tabs.postmatch })).toHaveAttribute(
          "aria-selected",
          "true",
        );
        await expect(page.getByTestId("postmatch")).toBeVisible();
        await settle(page);
        await fits(page, "Postpartido");
        await assertClean(page, w);
      } else {
        note("no result on Inicio today: Postpartido is not opened");
      }
    });

    await test.step("7 · Pick: un pick publicado con su estado real, o el día sin picks bien explicado", async () => {
      await page.getByTestId("tab-picks").click();
      await expect(page).toHaveURL(/\/picks$/);
      await settle(page);
      note(`Picks: ${await dayWithoutPicksOrPicks(page, page.locator("main"))}`);
      const text = (await page.locator("main").innerText()).toLowerCase();
      for (const word of ["shadow", "candidate", "rejected", "payload"])
        expect(text, `"${word}" on the reader's Picks`).not.toContain(word);
      await fits(page, "Picks");
      await assertClean(page, w);
    });

    await test.step("8 · Parlay: añadir y quitar patas, deshacer, ver la dependencia y guardar", async () => {
      fixtures = await pricedFixtures(page.request, 2);
      expect(fixtures, "seed_football.py puts upcoming matches with prices in QA").toHaveLength(2);
      for (const f of fixtures) {
        const price = await firstPrice(page, f.fixture_id);
        await price.getByTestId("odds-add-to-parlay").click();
        await expect(price.getByTestId("odds-add-to-parlay")).toHaveAttribute(
          "aria-pressed",
          "true",
        );
      }
      await page.getByTestId("slip-open").click();
      const sheet = page.getByTestId("slip-sheet");
      await expect(sheet.getByTestId("slip-leg")).toHaveCount(2);
      await sheet.getByTestId("slip-remove").first().click();
      await expect(sheet.getByTestId("slip-leg")).toHaveCount(1);
      await sheet.getByTestId("slip-undo-button").click();
      await expect(sheet.getByTestId("slip-leg")).toHaveCount(2);
      const dependency = sheet.getByTestId("slip-dependency");
      await expect(dependency).toBeVisible();
      await expect(dependency).toHaveAttribute("data-level", /^(low|medium|high)$/);
      note(`the slip's dependency: ${await dependency.getAttribute("data-level")}`);
      await expect(sheet.getByTestId("slip-save")).toBeEnabled();
      parlayName = `Recorrido ${Date.now()}`;
      await sheet.getByTestId("slip-name").fill(parlayName);
      await fits(page, "the slip");
      await sheet.getByTestId("slip-save").click();
      await expect(sheet).toHaveCount(0);
      await assertClean(page, w);
    });

    await test.step("9 · Mis picks: lo guardado, el resumen con su muestra y la confirmación al borrar", async () => {
      const [first] = fixtures;
      if (!first) throw new Error("no priced match");
      const price = await firstPrice(page, first.fixture_id);
      await price.getByTestId("save-pick").click();
      await expect(price.getByTestId("save-pick")).toHaveAttribute("aria-pressed", "true");
      await page.getByTestId("tab-my-picks").click();
      await expect(page).toHaveURL(/\/my-picks$/);
      await settle(page);
      const mine = page.locator(
        `[data-testid="saved-pick"][data-fixture-id="${first.fixture_id}"]`,
      );
      const row = mine.first();
      await expect(row).toBeVisible();
      await expect(row.getByTestId("origin-mine")).toHaveText(t.records.labels.mine);
      await expect(row.getByTestId("result-badge")).toHaveAttribute("data-status", "PENDING");
      await expect(page.getByTestId("my-parlay").filter({ hasText: parlayName })).toBeVisible();
      // the summary, as the API counts it (the page opens on 7 days)
      const history = await getJson<{ data: { groups: Record<string, { total: number }> } }>(
        page.request,
        "/api/v1/me/history?period=7d",
      );
      const fmt = new Intl.NumberFormat("es-ES");
      for (const group of ["predigol_picks", "my_picks", "predigol_parlays", "my_parlays"])
        await expect(page.getByTestId(`history-${group}-total`)).toHaveText(
          fmt.format(history.body.data.groups[group]?.total ?? 0),
        );
      // taking it out asks first: cancel keeps it, confirm removes it
      await row.getByTestId("saved-pick-remove").click();
      await expect(page.getByTestId("confirm-remove-pick")).toBeVisible();
      await page.getByTestId("confirm-remove-pick-cancel").click();
      await expect(row).toBeVisible();
      await row.getByTestId("saved-pick-remove").click();
      await page.getByTestId("confirm-remove-pick-ok").click();
      await expect(mine).toHaveCount(0);
      await fits(page, "Mis picks");
      await assertClean(page, w);
    });

    await test.step("10 · Perfil: idioma y zona, la copia de los datos (solo los suyos), seguridad y membresía", async () => {
      await more(page, "more-profile");
      await expect(page).toHaveURL(/\/profile/);
      // the account centre (plan UX, B1): on a phone, eight blocks folded, each with its line
      for (const key of [
        "account",
        "football",
        "region",
        "notifications",
        "privacy",
        "security",
        "membership",
        "help",
      ]) {
        await expect(page.getByTestId(`profile-block-${key}`)).toHaveAttribute(
          "data-open",
          "false",
        );
        await expect(page.getByTestId(`profile-summary-${key}`)).not.toHaveText("");
      }
      await expect(page.getByTestId("profile-summary-membership")).toContainText(
        "En prueba hasta el",
      );
      for (const key of ["region", "security", "membership", "privacy"])
        await page.getByTestId(`profile-toggle-${key}`).click();
      await expect(page.getByTestId("profile-lang-es")).toHaveAttribute("aria-checked", "true");
      await expect(page.getByTestId("current-timezone")).toContainText("America/Bogota");
      await expect(page.getByTestId("sessions-panel")).toBeVisible();
      const membership = page.getByTestId("membership-card");
      await expect(membership).toHaveAttribute("data-state", "trial");
      await expect(membership.getByTestId("membership-line")).toContainText("En prueba hasta el");
      const block = page.getByTestId("privacy-export");
      await block.getByTestId("privacy-export-start").click();
      await block.getByTestId("privacy-password").fill(CHOSEN);
      const downloading = page.waitForEvent("download");
      await block.getByTestId("privacy-export-confirm").click();
      const file = await downloading;
      expect(file.suggestedFilename()).toMatch(/^predigol-datos-\d{4}-\d{2}-\d{2}\.json$/);
      const raw = readFileSync(await file.path(), "utf8");
      const data = JSON.parse(raw) as { account: { email: string } };
      expect(data.account.email).toBe(email);
      const addresses = new Set(
        raw.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g) ?? [],
      );
      expect([...addresses], "the copy holds no one else's address").toEqual([email]);
      await expect(block).toContainText(t.legal.privacy.exported);
      await fits(page, "Perfil");
      await assertClean(page, w);
    });

    await test.step("11 · Soporte: «Reportar un problema» crea un mensaje con su contexto y la respuesta llega por correo", async () => {
      await more(page, "more-help");
      await expect(page).toHaveURL(/\/help$/);
      await page.getByTestId("help-report").first().click();
      const sheet = page.getByTestId("report-sheet");
      await expect(sheet).toBeVisible();
      await expect(sheet.getByTestId("report-context")).toContainText("/help");
      await sheet.getByTestId("report-category-technical").click();
      const words = `Recorrido de prueba: no se ve el partido de hoy (e2e ${Date.now()})`;
      const since = Date.now() - 5_000;
      await sheet.getByTestId("report-text").fill(words);
      await fits(page, "the report sheet");
      await sheet.getByTestId("report-send").click();
      const done = sheet.getByTestId("report-done");
      await expect(done).toBeVisible();
      const ticketId = Number(/n\.º (\d+)/.exec(await done.innerText())?.[1] ?? 0);
      expect(ticketId, "the receipt says the ticket's number").toBeGreaterThan(0);

      // the owner: the ticket with its context, answered in Soporte
      const inbox = await getJson<{ tickets: AdminTicket[] }>(
        admin,
        "/api/v1/admin/support?status=all",
      );
      const kept = inbox.body.tickets.find((x) => x.id === ticketId);
      expect(kept?.user_id).toBe(id);
      expect(kept?.category).toBe("technical");
      expect(kept?.context).toMatchObject({ route: "/help", device: "phone", pwa: false });
      const consolePage = await desk(browser);
      try {
        await consolePage.goto("/admin/support");
        const row = consolePage.getByTestId(`support-ticket-${ticketId}`);
        await expect(row).toBeVisible();
        await row.getByRole("button").first().click();
        await expect(consolePage.getByTestId(`support-context-${ticketId}`)).toContainText("/help");
        const answer = consolePage.getByTestId(`support-answer-${ticketId}`);
        await answer.locator("textarea").fill(ANSWER);
        await answer.getByTestId(`support-answer-send-${ticketId}`).click();
        await expect(answer.getByRole("status")).toBeVisible();
      } finally {
        await consolePage.context().close();
      }
      // the reader's mailbox: the receipt and the answer with the number and the link - never the words
      for (const template of ["support_ticket_received", "support_ticket_answered"]) {
        const mail = await mailFor(email, template, since);
        expect(mail.text).toContain(String(ticketId));
        expect(mail.text).toContain(`/help/messages/${ticketId}`);
        expect(mail.text).not.toContain(words);
        expect(mail.text).not.toContain(ANSWER);
      }
      await sheet.getByTestId("report-see").click();
      await expect(page).toHaveURL(new RegExp(`/help/messages/${ticketId}$`));
      await expect(page.getByTestId("ticket-status")).toHaveText(t.support.ticket.status.answered);
      await expect(page.getByTestId("ticket-thread")).toContainText(ANSWER);
      await fits(page, "the message's page");
      await assertClean(page, w);
    });

    await test.step("12 · Salir: la sesión se cierra en el servidor y volver atrás no muestra datos", async () => {
      const cookies = await page.context().cookies();
      await more(page, "more-sign-out");
      await expect(page).toHaveURL(/\/login/);
      await page.goBack({ waitUntil: "commit" });
      await expect(page).toHaveURL(/\/login/);
      await expect(page.getByTestId("ticket-thread")).toHaveCount(0);
      const old = await request.newContext({
        baseURL: BASE,
        extraHTTPHeaders: SAME_SITE,
        storageState: { cookies, origins: [] },
      });
      expect((await old.get("/api/v1/auth/me")).status(), "the session ended on the server").toBe(
        401,
      );
      await old.dispose();
      // The reader comes back later in a new tab. (WebKit's test build cannot navigate on from a page that Back restored -
      // it hangs or crashes; Chromium does not - so steps 13 and 14 run in a tab of their own in both engines.)
      tab = await page.context().newPage();
      tw = watch(tab, { expect401: true, expectStatus: [403] });
    });

    await test.step("13 · Entrar: un error dice que el correo o la contraseña no son correctos; con la suya entra", async () => {
      await signIn(tab, email, WRONG);
      await expect(tab.getByTestId("login-error")).toHaveText(t.errors.code.invalid_credentials);
      await expect(tab).toHaveURL(/\/login/);
      await tab.locator('input[name="password"]').fill(CHOSEN);
      await tab.getByTestId("login-submit").click();
      // back where the reader was going (the tab Back led to: «next»), or Inicio
      await expect(tab).not.toHaveURL(/\/login/);
      await tab.getByTestId("tab-home").click();
      await expect(tab).toHaveURL(/\/home$/);
      await expect(tab.getByTestId("consent-gate"), "the consents are asked once").toHaveCount(0);
      await settle(tab);
      await fits(tab, "Inicio, back");
      await assertClean(tab, tw);
    });

    await test.step("14 · Recuperación: «¿Olvidaste tu contraseña?» manda el enlace y la nueva contraseña cierra las demás sesiones", async () => {
      const elsewhere = await anonymous();
      expect(
        (
          await elsewhere.post("/api/v1/auth/login", { data: { email, password: CHOSEN } })
        ).status(),
        "a session on another device",
      ).toBe(200);
      await more(tab, "more-sign-out");
      await expect(tab).toHaveURL(/\/login/);
      await tab.getByTestId("forgot-link").click();
      await expect(tab).toHaveURL(/\/forgot-password$/);
      const since = Date.now();
      await tab.getByTestId("forgot-email").fill(email);
      await tab.getByTestId("forgot-submit").click();
      await expect(tab.getByTestId("forgot-sent")).toHaveText(t.auth.account.forgotSent);
      await fits(tab, "¿Olvidaste tu contraseña?");
      const reset = linkOf(await mailFor(email, "password_reset", since), "/reset-password");
      await go(tab, reset);
      await expect(tab.getByTestId("reset-form")).toBeVisible();
      await expect(tab.getByTestId("account-email")).toHaveValue(email);
      await tab.getByTestId("new-password").fill(RENEWED);
      await tab.getByTestId("new-password-repeat").fill(RENEWED);
      await tab.getByTestId("reset-submit").click();
      await expect(tab.getByTestId("reset-done")).toHaveText(t.auth.account.resetDone);
      expect(
        (await elsewhere.get("/api/v1/auth/me")).status(),
        "the other device's session ended",
      ).toBe(401);
      await elsewhere.dispose();
      await signIn(tab, email, CHOSEN);
      await expect(tab.getByTestId("login-error"), "the old password no longer works").toHaveText(
        t.errors.code.invalid_credentials,
      );
      await tab.locator('input[name="password"]').fill(RENEWED);
      await tab.getByTestId("login-submit").click();
      await expect(tab).toHaveURL(/\/home$/);
      await settle(tab);
      await assertClean(tab, tw);
    });

    note(
      "15 · Móvil and 16 · PWA are the owner's, on a real phone (P10): here the journey ran at " +
        `${page.viewportSize()?.width ?? "?"} px with touch, and pwa.spec.ts proves the worker on the production build`,
    );
  } finally {
    if (id) {
      const r = await sendJson(admin, "POST", `/api/v1/admin/users/${id}/anonymise`, {
        confirm: email,
      });
      expect([200, 409], `the journey's account ${id} is deleted`).toContain(r.status);
    }
    await admin.dispose();
  }
});
