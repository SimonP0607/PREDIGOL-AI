/**
 * The welcome, the favourites, the hints and the tour (plan UX, A13; gate G8), in the browser against the API, on accounts
 * the test makes and deletes at the end:
 *
 * * a new account - invited, its e-mail's link opened, when the QA API runs with self-service on (QA_SELF_SERVICE=1,
 *   QA_MESSENGER=1, E2E_MAIL_SINK), else made by the owner with its password - goes from its first entry through the
 *   consents, «Tu fútbol» and «Qué es PrediGol» to Inicio with «Hoy en tus ligas» in under 90 seconds, timed; and never
 *   sees the welcome again;
 * * an account from before A13 (E2E_DATABASE_URL moves its creation back a month) sees one screen of favourites; skipping
 *   keeps the suggested ones, labelled, with the way to choose;
 * * the picker on a 320 px phone: nothing sideways, every control in a finger's reach - and by keyboard alone;
 * * a first-visit hint on Picks, a match, the parlays and Mis picks: dismissed with a tap, never again, after a reload too;
 * * the optional tour from the help: four steps, each on its page;
 * * the star in a match's header follows the team; Inicio then says why its match is there.
 */
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import {
  L,
  assertClean,
  getJson,
  sendJson,
  settle,
  skipWelcome,
  smallTargets,
  watch,
} from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const SINK = process.env["E2E_MAIL_SINK"] ?? "";
const DB = (process.env["E2E_DATABASE_URL"] ?? "").replace(
  "postgresql+psycopg://",
  "postgresql://",
);
const PASSWORD = "Mi-primer-partido-2026"; // gitleaks:allow - a QA account's password, made and deleted here
const CHOSEN = "La-tarde-del-clasico-26"; // gitleaks:allow - the password an invited QA reader chooses
const SAME_SITE = { "x-requested-with": "predigol" };
const PHONE = { width: 320, height: 720 };
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const t = L.es;
const o = t.onboarding;
/** Plan UX, section 19 and gate G8: from the activation to the first value, timed. */
const LIMIT_MS = 90_000;

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function selfService(): Promise<boolean> {
  const api = await request.newContext({ baseURL: BASE, extraHTTPHeaders: SAME_SITE });
  const r = await getJson<{ self_service: boolean }>(api, "/api/v1/auth/options");
  await api.dispose();
  return r.body.self_service;
}

async function account(
  admin: APIRequestContext,
  kind: string,
): Promise<{ id: number; email: string }> {
  const email = `e2e.welcome.${kind}.${Date.now()}@predigol.local`;
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
  if (!id) return;
  const r = await sendJson(admin, "POST", `/api/v1/admin/users/${id}/anonymise`, {
    confirm: email,
  });
  expect([200, 409], `the test's account ${id} is deleted`).toContain(r.status);
}

async function signIn(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
}

async function consents(page: Page): Promise<void> {
  const gate = page.getByTestId("consent-gate");
  await expect(gate).toBeVisible();
  for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
    await gate.getByTestId(`consent-${kind}`).check();
  await gate.getByTestId("consent-submit").click();
  await expect(gate).toHaveCount(0);
}

interface Mail {
  to: string;
  template: string;
  text: string;
  at: string;
}

async function invitationLink(to: string, since: number): Promise<string> {
  let found: Mail | undefined;
  await expect(async () => {
    found = readdirSync(SINK)
      .filter((f) => f.endsWith(".json"))
      .map((f) => JSON.parse(readFileSync(join(SINK, f), "utf8")) as Mail)
      .filter((m) => m.to === to && m.template === "invitation" && Date.parse(m.at) >= since)
      .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))[0];
    expect(found, `an invitation to ${to} in ${SINK}`).toBeTruthy();
  }).toPass({ timeout: 60_000, intervals: [1_000] });
  const m = /https?:\/\/\S+?\/activate#t=([A-Za-z0-9_-]{43})\b/.exec(found?.text ?? "");
  expect(m, "the e-mail carries its /activate link").toBeTruthy();
  return `/activate#t=${m?.[1] ?? ""}`;
}

interface TodayBody {
  data: {
    matches: {
      data: Array<{
        fixture_id: number;
        status_group: string;
        competition: { name: string };
        home: { id: number; name: string };
      }>;
    };
  };
}

/**
 * A team that plays later today: the home side of the QA seed's match of «QA Primera A» (seed_a9.py: «QA Bahía - QA Llano»,
 * later today in Bogotá, in a suggested league) - its name to search, its match to open.
 */
async function todaysTeam(
  api: APIRequestContext,
): Promise<{ fixture: number; id: number; name: string }> {
  const today = await getJson<TodayBody>(api, "/api/v1/today");
  expect(today.status).toBe(200);
  const scheduled = today.body.data.matches.data.filter((m) => m.status_group === "scheduled");
  const match = scheduled.find((m) => m.competition.name === "QA Primera A") ?? scheduled[0];
  expect(match, "the QA seed puts a match later today on the board (seed_a9.py)").toBeTruthy();
  return { fixture: match?.fixture_id ?? 0, id: match?.home.id ?? 0, name: match?.home.name ?? "" };
}

test("a new account: from its first entry to «Hoy en tus ligas» with its favourites in under 90 seconds, and never again", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const admin = await owner();
  const invited = (await selfService()) && SINK !== "";
  let id = 0;
  let email = `e2e.welcome.new.${Date.now()}@predigol.local`;
  try {
    let started: number;
    // 403 consent_required while the boxes are owed; 401 from the anonymous /auth/me
    const w = watch(page, { expect401: true, expectStatus: [403] });
    if (invited) {
      const since = Date.now();
      const r = await sendJson<{ data: { id: number } }>(
        admin,
        "POST",
        "/api/v1/admin/users/invite",
        {
          email,
          display_name: "Bienvenida E2E",
          language: "es",
          timezone: "America/Bogota",
        },
      );
      expect(r.status, "the owner invites").toBe(201);
      id = r.body.data.id;
      const link = await invitationLink(email, since);
      started = Date.now();
      await page.goto(link);
      await expect(page.getByTestId("activate-form")).toBeVisible();
      await page.getByTestId("new-password").fill(CHOSEN);
      await page.getByTestId("new-password-repeat").fill(CHOSEN);
      await page.getByTestId("activate-submit").click();
    } else {
      ({ id, email } = await account(admin, "new"));
      started = Date.now();
      await signIn(page, email);
    }
    await consents(page);

    // «Tu fútbol»: the suggested ones already ticked, a team found by name and added
    await expect(page).toHaveURL(/\/welcome$/);
    const welcome = page.getByTestId("welcome");
    await expect(welcome).toHaveAttribute("data-step", "football");
    await expect(page.getByTestId("welcome-progress")).toHaveText(
      o.welcome.step.replace("{n}", "1").replace("{total}", "2"),
    );
    const chosen = page.getByTestId("fav-chosen");
    await expect(chosen.getByTestId("fav-chip").first()).toBeVisible();
    const suggested = await chosen.getByTestId("fav-chip").count();
    const team = await todaysTeam(page.request);
    await page.getByTestId("fav-search").fill(team.name.slice(0, 5));
    const result = page.getByTestId("fav-team").filter({ hasText: team.name }).first();
    await expect(result).toBeVisible();
    if ((await result.getAttribute("aria-pressed")) === "false") await result.click();
    await expect(result).toHaveAttribute("aria-pressed", "true");
    await expect(chosen.getByTestId("fav-chip")).toHaveCount(suggested + 1);
    await page.getByTestId("welcome-save").click();

    // «Qué es PrediGol»: three sentences, then Inicio
    await expect(welcome).toHaveAttribute("data-step", "about");
    await expect(page.getByTestId("welcome-about").locator("li")).toHaveCount(3);
    await page.getByTestId("welcome-enter").click();
    await expect(page).toHaveURL(/\/home$/);
    const block = page.getByTestId("home-today");
    await expect(block).toHaveAttribute("data-view", "mine");
    await expect(block.getByRole("heading", { name: t.home.today.titleMine })).toBeVisible();
    await expect(block.getByTestId("mine-chips")).toContainText(team.name);
    const elapsed = Date.now() - started;
    test
      .info()
      .annotations.push({ type: "timing", description: `first entry to Inicio: ${elapsed} ms` });
    expect(elapsed, "plan UX G8: under 90 seconds").toBeLessThan(LIMIT_MS);
    // useful content in the first minute, with or without picks: today's matches of the reader's own, why each is there
    await expect(block.getByTestId("today-row").first()).toBeVisible();
    await expect(block.getByTestId("today-why").first()).toBeVisible();
    await settle(page);
    await assertClean(page, w);

    // never again: the welcome is done, its address leads to Inicio
    await page.goto("/welcome");
    await expect(page).toHaveURL(/\/home$/);
    const state = await getJson<{ welcome_due: boolean; onboarded_at: string | null }>(
      page.request,
      "/api/v1/me/onboarding",
    );
    expect(state.body.welcome_due).toBe(false);
    expect(state.body.onboarded_at).not.toBeNull();
    const favorites = await getJson<{ suggested: boolean; teams: Array<{ id: number }> }>(
      page.request,
      "/api/v1/me/favorites",
    );
    expect(favorites.body.suggested).toBe(false);
    expect(favorites.body.teams.map((x) => x.id)).toContain(team.id);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("an account from before: one screen of favourites; skipping keeps the suggested ones, labelled, with the way to choose", async ({
  page,
}) => {
  test.skip(!DB, "E2E_DATABASE_URL: the QA base, to move the account's creation back a month");
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "older");
  try {
    execFileSync(
      "psql",
      [
        DB,
        "-v",
        "ON_ERROR_STOP=1",
        "-qtAc",
        `UPDATE auth.users SET created_at = now() - interval '30 days' WHERE id = ${Number(id)}`,
      ],
      { stdio: "pipe" },
    );
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await consents(page);
    await expect(page).toHaveURL(/\/welcome$/);
    await expect(page.getByTestId("welcome")).toHaveAttribute("data-step", "football");
    await expect(page.getByTestId("welcome-progress"), "one screen: no steps to count").toHaveCount(
      0,
    );
    await expect(page.getByTestId("welcome")).toContainText(o.welcome.football.introOlder);
    await page.getByTestId("welcome-skip").click();
    await expect(page).toHaveURL(/\/home$/);
    const block = page.getByTestId("home-today");
    await expect(block).toHaveAttribute("data-view", "suggested");
    await expect(block.getByRole("heading", { name: t.home.today.title })).toBeVisible();
    await expect(block.getByTestId("today-choose")).toHaveText(t.home.today.choose);
    await block.getByTestId("today-choose").click();
    await expect(page).toHaveURL(/\/profile#football$/);
    await expect(page.getByTestId("football-current")).toHaveAttribute("data-suggested", "true");
    await settle(page);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("the picker on a 320 px phone: nothing sideways, every control in a finger's reach; and by keyboard alone", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "phone");
  try {
    await page.setViewportSize(PHONE);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await consents(page);
    await expect(page).toHaveURL(/\/welcome$/);
    await expect(page.getByTestId("fav-league").first()).toBeVisible();
    await settle(page);
    const sideways = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(sideways, "nothing scrolls sideways at 320 px").toBeLessThanOrEqual(0);
    // the picker and the welcome's own buttons (the header's language switch and the notice's links are the shared
    // ones responsive.spec.ts measures on a touch phone)
    const small = await smallTargets(page, '[data-testid="welcome"] main');
    expect(small, "every toggle, chip and button 44 px").toEqual([]);
    await expect(page.getByTestId("fav-search")).toHaveCSS("font-size", "16px");
    const axe = await new AxeBuilder({ page })
      .withTags(WCAG)
      .include('[data-testid="welcome"]')
      .analyze();
    expect(
      axe.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
      "the welcome passes axe (WCAG 2.2 AA)",
    ).toEqual([]);

    // the keyboard alone: the search, a league's toggle (Space), the save (Enter)
    await page.getByTestId("fav-search").focus();
    await expect(page.getByTestId("fav-search")).toBeFocused();
    // a folded country opens with Enter; a league's toggle changes with Space
    const closed = page.locator('[data-testid="fav-country"]:not([open])').first();
    await closed.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(closed).toHaveAttribute("open", "");
    const league = closed.getByTestId("fav-league").first();
    const before = await league.getAttribute("aria-pressed");
    await league.focus();
    await page.keyboard.press("Space");
    await expect(league).toHaveAttribute("aria-pressed", before === "true" ? "false" : "true");
    await page.getByTestId("welcome-save").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("welcome")).toHaveAttribute("data-step", "about");
    await page.getByTestId("welcome-enter").focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/home$/);
    await settle(page);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("a first-visit hint on Picks, a match, the parlays and Mis picks: dismissed with a tap, never again", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "hints");
  try {
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await skipWelcome(page.request);
    await consents(page);
    const team = await todaysTeam(page.request);
    const pages: Array<[string, "picks" | "match" | "parlay" | "my_picks"]> = [
      ["/picks", "picks"],
      [`/matches/${team.fixture}`, "match"],
      ["/parlays", "parlay"],
      ["/my-picks", "my_picks"],
    ];
    for (const [path, hint] of pages) {
      await page.goto(path);
      const card = page.getByTestId("first-visit-hint");
      await expect(card).toHaveAttribute("data-hint", hint);
      await expect(card).toContainText(o.hint[hint]);
      await card.getByTestId("hint-dismiss").click();
      await expect(card).toHaveCount(0);
      await page.reload();
      await settle(page);
      await expect(page.getByTestId("first-visit-hint"), `${path}: never again`).toHaveCount(0);
    }
    const state = await getJson<{ hints_seen: string[] }>(page.request, "/api/v1/me/onboarding");
    expect([...state.body.hints_seen].sort()).toEqual(["match", "my_picks", "parlay", "picks"]);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("the optional tour from the help: four steps, each on its page, closed at the end", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "tour");
  try {
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await skipWelcome(page.request);
    await consents(page);
    await page.goto("/help/glossary");
    await page.getByTestId("tour-start").click();
    const card = page.getByTestId("tour-card");
    const steps: Array<[string, RegExp]> = [
      ["home", /\/home$/],
      ["match", /\/matches(\/\d+)?$/],
      ["pick", /\/picks$/],
      ["myPicks", /\/my-picks$/],
    ];
    for (const [i, [step, url]] of steps.entries()) {
      await expect(page).toHaveURL(url);
      await expect(card).toHaveAttribute("data-step", step);
      await expect(card).toContainText(
        o.tour.step.replace("{n}", String(i + 1)).replace("{total}", "4"),
      );
      await card.getByTestId("tour-next").click();
    }
    await expect(card).toHaveCount(0);
    await settle(page);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("the star in a match's header follows the team, and Inicio says why its match is there", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "star");
  try {
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await skipWelcome(page.request);
    await consents(page);
    const team = await todaysTeam(page.request);
    await page.goto(`/matches/${team.fixture}`);
    const star = page.locator(`[data-testid="follow-star"][data-team="${team.id}"]`);
    await expect(star).toHaveAttribute("aria-pressed", "false");
    await expect(star).toHaveAttribute("aria-label", o.follow.add.replace("{team}", team.name));
    await star.click();
    await expect(star).toHaveAttribute("aria-pressed", "true");
    await page.goto("/home");
    const block = page.getByTestId("home-today");
    await expect(block).toHaveAttribute("data-view", "mine");
    const row = block.locator(`[data-testid="today-row"][data-fixture="${team.fixture}"]`);
    await expect(row.getByTestId("today-why")).toHaveText(
      t.home.today.whyTeam.replace("{team}", team.name),
    );
    // and back: unfollowed from the same star
    await page.goto(`/matches/${team.fixture}`);
    await star.click();
    await expect(star).toHaveAttribute("aria-pressed", "false");
    await settle(page);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});
