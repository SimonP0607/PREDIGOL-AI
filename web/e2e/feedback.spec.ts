/**
 * What readers think of PrediGol (plan UX, B6; section 40), in the browser against the API: the monthly survey, «¿Te sirvió?»,
 * Novedades and the owner's view of them, on reader accounts the test makes (past their first week by SQL: the survey never comes
 * in an account's first week) and deletes.
 *
 * «Criterio de terminado: la encuesta aparece como máximo una vez al mes y nunca tras un error (prueba de frecuencia), los votos
 * se guardan con su contexto y Novedades está publicada.» And B6's QA: the scale with the keyboard, the card at 320 px.
 *
 * * After a useful moment - a match's analysis read, a result seen - the survey comes up, without taking the focus; answered with
 *   the keyboard, its optional question follows the score, the comment keeps no address, the context is where it was asked; then it
 *   is not owed for 30 days and does not come back.
 * * On a 320 px phone: a card over the page's foot, above the tab bar, inside the screen, 44 px targets, axe clean; «Ahora no»
 *   closes it in one tap and keeps it away for 30 days too.
 * * Never after an error: a visit where something failed does not bring it, even owed.
 * * «¿Te sirvió?» at the end of the reading and of a pick's explanation: saved with its context, one answer per thing read, the last
 *   one counts; after a «No», the way to suggest what was missing.
 * * Novedades: a dot on «Más» while an entry is unread; opening /updates marks the newest seen and the dot goes.
 * * /admin/product: the survey with its n and the comment, never who wrote it.
 *
 * Every figure is checked against SQL written here. Run with E2E_FEEDBACK=1 against the QA stack with QA_PICK_STATES=1 (its
 * published example picks have an explanation to vote on) and FBI_FEEDBACK on; with E2E_FEEDBACK_OFF=1, against FBI_FEEDBACK=0:
 * no survey and no question, the answers kept.
 */
import { execFileSync } from "node:child_process";
import AxeBuilder from "@axe-core/playwright";
import {
  devices,
  expect,
  request,
  test,
  type APIRequestContext,
  type Browser,
  type Page,
} from "@playwright/test";
import { statePath } from "./accounts";
import { L, getJson, sendJson, skipWelcome, smallTargets } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const DB = (process.env["E2E_DATABASE_URL"] ?? "").replace(
  "postgresql+psycopg://",
  "postgresql://",
);
const OFF = process.env["E2E_FEEDBACK_OFF"] === "1";
const PASSWORD = "Tell-us-once-a-month-26"; // gitleaks:allow - a QA account's password, made and deleted here
const PHONE = { width: 320, height: 720 };
const DESK = { width: 1440, height: 900 };
/** The survey comes up 12 s after a useful moment (OFFER_AFTER_MS): time enough to see it, or to be sure it did not come. */
const COMES_UP = 30_000;
const WAIT_NONE = 16_000;
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const t = L.es;

function sql(query: string): string {
  return execFileSync("psql", [DB, "-v", "ON_ERROR_STOP=1", "-qAt", "-F", "|", "-c", query], {
    stdio: "pipe",
  })
    .toString()
    .trim();
}

interface Reader {
  id: number;
  email: string;
}

const made: Reader[] = [];

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

/** A reader account; ``weeks`` past its first week by SQL (the survey can be owed to it) unless ``fresh``. */
async function account(tag: string, fresh = false): Promise<Reader> {
  const admin = await owner();
  const email = `e2e.feedback.${tag}.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number } }>(admin, "POST", "/api/v1/admin/users", {
    email,
    password: PASSWORD,
    role: "USER",
    language: "es",
    timezone: "America/Bogota",
    must_change_password: false,
  });
  await admin.dispose();
  expect(created.status, "the owner creates the test's account").toBe(201);
  const reader = { id: created.body.data.id, email };
  made.push(reader);
  if (!fresh)
    sql(`UPDATE auth.users SET created_at = now() - interval '8 days' WHERE id = ${reader.id}`);
  return reader;
}

test.afterAll(async () => {
  const admin = await owner();
  for (const r of made) {
    const res = await sendJson(admin, "POST", `/api/v1/admin/users/${r.id}/anonymise`, {
      confirm: r.email,
    });
    expect([200, 409], `the test's account ${r.id} is deleted`).toContain(res.status);
  }
  await admin.dispose();
});

/** A 320 px touch phone (pointer: coarse, as the plan's phones; the 44 px targets count the "tap" widening), in the project's language. */
async function phone(browser: Browser): Promise<{ page: Page; close: () => Promise<void> }> {
  const context = await browser.newContext({
    ...devices["Pixel 7"],
    viewport: PHONE,
    baseURL: BASE,
    locale: "es-ES",
    timezoneId: "America/Bogota",
  });
  const page = await context.newPage();
  return { page, close: () => context.close() };
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

interface Survey {
  enabled: boolean;
  due: boolean;
  last_at: string | null;
  next_at: string | null;
}

async function survey(page: Page): Promise<Survey> {
  const r = await getJson<Survey>(page.request, "/api/v1/me/feedback/survey");
  expect(r.status).toBe(200);
  return r.body;
}

/** A match to come with its reading (the analysis the reader opens). */
async function matchToRead(page: Page): Promise<number> {
  const today = await getJson<{
    data: {
      matches: { data: Array<{ fixture_id: number; has_reading: boolean; status_group: string }> };
    };
  }>(page.request, "/api/v1/today");
  for (const m of today.body.data.matches.data) {
    if (!m.has_reading || m.status_group !== "scheduled") continue;
    const reading = await getJson<{ status: string }>(
      page.request,
      `/api/v1/matches/${m.fixture_id}/reading`,
    );
    if (reading.body.status === "ok") return m.fixture_id;
  }
  throw new Error("QA has no match to come with a reading today (seed_a9.py)");
}

/** The newest finished match (its Postpartido is a result seen). */
async function finishedMatch(page: Page): Promise<number> {
  const r = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    "/api/v1/matches?status=finished&order=desc&limit=1",
  );
  const id = r.body.data[0]?.id;
  expect(id, "QA has a finished match").toBeTruthy();
  return id!;
}

async function openTab(
  page: Page,
  fixtureId: number,
  tab: "analysis" | "postmatch",
): Promise<void> {
  await page.goto(`/matches/${fixtureId}`);
  await page.getByRole("tab", { name: t.match.tabs[tab] }).click();
}

function feedbackRows(user: number): string[] {
  return sql(
    `SELECT kind, coalesce(score::text, ''), coalesce(comment, ''), coalesce(subject, ''), coalesce(subject_id::text, ''),
            coalesce(helpful::text, ''), context::text
       FROM customer.feedback WHERE user_id = ${user} ORDER BY id`,
  )
    .split("\n")
    .filter(Boolean);
}

async function accessible(page: Page, what: string, within: string): Promise<void> {
  const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).include(within).analyze();
  expect(
    result.violations.map(
      (v) => `${v.id} (${v.impact ?? "?"}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    ),
    `${what}: axe, WCAG 2.2 A and AA`,
  ).toEqual([]);
}

test.describe.configure({ mode: "serial" });
test.setTimeout(240_000);

test.describe("FBI_FEEDBACK on", () => {
  test.skip(OFF, "the run with FBI_FEEDBACK=0 checks the other side");

  test("after a useful moment the survey comes up, answered by keyboard: the question follows the score, the comment keeps no address, then not for 30 days", async ({
    page,
  }) => {
    await page.setViewportSize(DESK);
    const reader = await account("keys");
    await signIn(page, reader.email);
    expect((await survey(page)).due, "owed to a reader past their first week").toBe(true);
    // signing in and Inicio are not useful moments: nothing comes up there
    await page.waitForTimeout(WAIT_NONE);
    await expect(page.getByTestId("csat-prompt")).toHaveCount(0);

    const fixture = await matchToRead(page);
    await openTab(page, fixture, "analysis");
    await expect(page.getByTestId("match-reading")).toBeVisible();
    const prompt = page.getByTestId("csat-prompt");
    await expect(prompt).toBeVisible({ timeout: COMES_UP });
    await expect(prompt).toHaveAttribute("role", "dialog");
    await expect(prompt).toHaveAttribute("aria-modal", "false");
    expect(
      await page.evaluate(() => !!document.activeElement?.closest('[data-testid="csat-prompt"]')),
      "it does not take the focus from what the reader was reading",
    ).toBe(false);
    await expect(prompt).toContainText(t.support.feedback.survey.question);
    await expect(prompt.getByTestId("csat-send")).toBeDisabled();

    // the scale with the keyboard: Space chooses, the arrows move along it
    const radios = prompt.locator('input[type="radio"]');
    await expect(radios).toHaveCount(5);
    await radios.first().focus();
    await page.keyboard.press("Space");
    await expect(radios.nth(0)).toBeChecked();
    await page.keyboard.press("ArrowRight");
    await expect(radios.nth(1)).toBeChecked();
    await expect(prompt.getByTestId("csat-comment-block")).toContainText(
      t.support.feedback.survey.comment.missing,
    );
    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
    await expect(radios.nth(4)).toBeChecked();
    await expect(prompt.getByTestId("csat-comment-block")).toContainText(
      t.support.feedback.survey.comment.best,
    );
    await page.keyboard.press("Tab");
    await expect(prompt.getByTestId("csat-comment")).toBeFocused();
    await page.keyboard.type("Las lecturas; escríbanme a lector.b6@example.org");
    await page.keyboard.press("Tab");
    await expect(prompt.getByTestId("csat-skip")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(prompt.getByTestId("csat-send")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(prompt).toHaveAttribute("data-phase", "thanks");
    await expect(prompt.getByTestId("csat-updates")).toHaveAttribute("href", "/updates");

    expect(feedbackRows(reader.id)).toEqual([
      `csat|5|Las lecturas; escríbanme a [dato quitado]||||{"route": "/matches/${fixture}", "trigger": "analysis_opened"}`,
    ]);
    const after = await survey(page);
    expect(after.due).toBe(false);
    expect(Date.parse(after.next_at!) - Date.parse(after.last_at!)).toBe(30 * 24 * 3600 * 1000);
    await prompt.getByTestId("csat-done").click();
    await expect(prompt).toHaveCount(0);

    // another visit, another useful moment: not owed, it does not come back
    await page.reload();
    await openTab(page, fixture, "analysis");
    await expect(page.getByTestId("match-reading")).toBeVisible();
    await page.waitForTimeout(WAIT_NONE);
    await expect(prompt).toHaveCount(0);
    expect(feedbackRows(reader.id)).toHaveLength(1);
  });

  test("on a 320 px phone: a card over the page's foot, above the tab bar, 44 px targets; «Ahora no» closes it in one tap for 30 days", async ({
    browser,
  }) => {
    const { page, close } = await phone(browser);
    const reader = await account("phone");
    await signIn(page, reader.email);
    const fixture = await finishedMatch(page);
    await openTab(page, fixture, "postmatch");
    await expect(page.getByTestId("postmatch")).toBeVisible();
    const prompt = page.getByTestId("csat-prompt");
    await expect(prompt).toBeVisible({ timeout: COMES_UP });
    const card = (await prompt.boundingBox())!;
    const bar = (await page
      .getByRole("navigation", { name: t.nav.mainNavigation })
      .last()
      .boundingBox())!;
    expect(card.x).toBeGreaterThanOrEqual(0);
    expect(card.x + card.width).toBeLessThanOrEqual(PHONE.width);
    expect(card.y + card.height, "above the tab bar").toBeLessThanOrEqual(bar.y);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
      "nothing goes sideways",
    ).toBeLessThanOrEqual(1);
    await prompt.getByTestId("csat-score-3").click();
    expect(await smallTargets(page, '[data-testid="csat-prompt"]'), "44 px targets").toEqual([]);
    await accessible(page, "the survey on a 320 px phone", '[data-testid="csat-prompt"]');
    await prompt.getByTestId("csat-skip").click();
    await expect(prompt).toHaveCount(0);
    expect(feedbackRows(reader.id)).toEqual([
      `csat_skipped||||||{"route": "/matches/${fixture}", "trigger": "result_seen"}`,
    ]);
    expect((await survey(page)).due, "closed: not for 30 days").toBe(false);
    await close();
  });

  test("never after an error: a visit where something failed does not bring it, even owed; and never in an account's first week", async ({
    page,
  }) => {
    await page.setViewportSize(DESK);
    const reader = await account("error");
    await signIn(page, reader.email);
    // Inicio's day fails once: the reader sees the error, with its reference and a retry
    await page.route("**/api/v1/today*", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: '{"error":{"code":"internal","message":"x"},"request_id":"e2eB6err"}',
      }),
    );
    await page.goto("/home");
    await expect(page.getByRole("alert").filter({ hasText: "e2eB6err" }).first()).toBeVisible({
      timeout: 30_000,
    });
    await page.unroute("**/api/v1/today*");
    const fixture = await matchToRead(page);
    await openTab(page, fixture, "analysis");
    await expect(page.getByTestId("match-reading")).toBeVisible();
    await page.waitForTimeout(WAIT_NONE);
    await expect(page.getByTestId("csat-prompt")).toHaveCount(0);
    expect((await survey(page)).due, "owed - the error kept it away, not the server").toBe(true);
    expect(feedbackRows(reader.id)).toEqual([]);

    // an account in its first week: not owed until its eighth day
    const fresh = await account("first-week", true);
    const api = await request.newContext({
      baseURL: BASE,
      extraHTTPHeaders: { "x-requested-with": "predigol" },
    });
    expect(
      (
        await api.post("/api/v1/auth/login", { data: { email: fresh.email, password: PASSWORD } })
      ).status(),
    ).toBe(200);
    // the consents first, as the gate asks of every new reader (plan UX, A4): until then /me answers 403
    const who = (await (await api.get("/api/v1/auth/me")).json()) as { consents_due?: string[] };
    if (who.consents_due?.length) {
      const texts = (await (await api.get("/api/v1/me/consents?lang=es")).json()) as {
        purposes: Array<{ kind: string; version: string }>;
      };
      const accepted = await api.post("/api/v1/me/consents", {
        data: {
          decisions: texts.purposes
            .filter((p) => who.consents_due?.includes(p.kind))
            .map((p) => ({ kind: p.kind, granted: true, version: p.version })),
          locale: "es",
          source: "gate",
        },
      });
      expect(accepted.status(), "the new reader accepts the current texts").toBe(200);
    }
    const asked = await api.get("/api/v1/me/feedback/survey");
    expect(asked.status(), "the survey's state").toBe(200);
    const state = (await asked.json()) as Survey;
    const created = sql(
      `SELECT extract(epoch FROM created_at) FROM auth.users WHERE id = ${fresh.id}`,
    );
    expect(state.due).toBe(false);
    expect(
      Math.abs(Date.parse(state.next_at!) / 1000 - (Number(created) + 7 * 24 * 3600)),
    ).toBeLessThan(1);
    await api.dispose();
  });

  test("«¿Te sirvió?» at the end of the reading and of a pick's explanation: saved with its context, the last answer counts", async ({
    page,
  }) => {
    await page.setViewportSize(DESK);
    const reader = await account("votes");
    // the survey answered first: this test is about the votes
    sql(
      `INSERT INTO customer.feedback (user_id, kind, score, context) VALUES (${reader.id}, 'csat', 4, '{}')`,
    );
    await signIn(page, reader.email);
    const fixture = await matchToRead(page);
    await openTab(page, fixture, "analysis");
    const reading = page.getByTestId("match-reading");
    const vote = reading.getByTestId("helpful-vote");
    await expect(vote).toBeVisible();
    const subject = (await vote.getAttribute("data-subject"))!;
    expect(["reading", "narrative"]).toContain(subject);
    await expect(vote).toContainText(t.support.feedback.helpful.question.analysis);
    await expect(vote).toHaveAttribute("data-vote", "none");
    await vote.getByTestId("helpful-yes").click();
    await expect(vote.getByTestId("helpful-yes")).toHaveAttribute("aria-pressed", "true");
    await expect(vote.getByTestId("helpful-note")).toContainText(t.support.feedback.helpful.thanks);
    const row = (helpful: boolean) =>
      `helpful|||${subject}|${fixture}|${helpful}|{"route": "/matches/${fixture}"}`;
    await expect.poll(() => feedbackRows(reader.id).slice(1)).toEqual([row(true)]);
    await vote.getByTestId("helpful-no").click();
    await expect(vote.getByTestId("helpful-no")).toHaveAttribute("aria-pressed", "true");
    await expect
      .poll(() => feedbackRows(reader.id).slice(1), "one answer, the last one")
      .toEqual([row(false)]);
    // after a «No», the way to tell what was missing: a suggestion
    await vote.getByTestId("helpful-tell-us").click();
    const sheet = page.getByTestId("report-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByTestId("report-category-suggestion").locator("input")).toBeChecked();
    await page.keyboard.press("Escape");
    await expect(sheet).toHaveCount(0);
    await page.reload();
    await page.getByRole("tab", { name: t.match.tabs.analysis }).click();
    await expect(page.getByTestId("helpful-vote").getByTestId("helpful-no")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // a published pick's explanation (QA's example picks: the stack with QA_PICK_STATES=1)
    const board = await getJson<{
      data: { picks: Array<{ pick_id: number; home: { name: string } }> };
    }>(page.request, "/api/v1/picks?hours=24");
    const pick = board.body.data.picks[0];
    expect(pick, "a published pick to explain (seed_b3.py)").toBeTruthy();
    await page.goto("/picks");
    await page
      .getByTestId("picks-list")
      .getByTestId("pick-card")
      .filter({ hasText: pick!.home.name })
      .first()
      .getByTestId("why-pick")
      .click();
    const why = page.getByTestId("why-sheet");
    await expect(why.getByTestId("why-explanation")).toBeVisible();
    const explained = why.getByTestId("helpful-vote");
    await expect(explained).toContainText(t.support.feedback.helpful.question.explanation);
    // after the layers, before the notice that closes every explanation
    expect(
      await why.evaluate((root) => {
        const v = root.querySelector('[data-testid="helpful-vote"]')!;
        const layers = root.querySelector('[data-testid="why-layer-conclusion"]')!;
        return [
          layers.compareDocumentPosition(v) & Node.DOCUMENT_POSITION_FOLLOWING,
          v.nextElementSibling?.textContent?.includes("+18") ?? false,
        ];
      }),
    ).toEqual([4, true]); // Node.DOCUMENT_POSITION_FOLLOWING: after the layers; then the notice
    await explained.getByTestId("helpful-yes").click();
    await expect(explained.getByTestId("helpful-yes")).toHaveAttribute("aria-pressed", "true");
    await expect
      .poll(() => feedbackRows(reader.id).filter((r) => r.includes("|explanation|")))
      .toEqual([`helpful|||explanation|${pick!.pick_id}|true|{"route": "/picks"}`]);
    await accessible(page, "the explanation with its question", '[data-testid="why-sheet"]');
  });

  test("Novedades: a dot on «Más» while an entry is unread; opening it marks the newest seen and the dot goes", async ({
    browser,
  }) => {
    const { page, close } = await phone(browser);
    const reader = await account("updates", true);
    await signIn(page, reader.email);
    const more = page.getByTestId("tab-more");
    await expect(more.getByTestId("tab-more-dot")).toBeVisible();
    await expect(more).toContainText(t.nav.moreUnread);
    await more.click();
    const sheet = page.getByTestId("more-sheet");
    const row = sheet.getByTestId("more-updates");
    await expect(row).toContainText(t.nav.updates);
    await expect(row.getByTestId("unread-dot")).toBeVisible();
    await row.click();
    await expect(page).toHaveURL(/\/updates$/);
    const entries = page.getByTestId("update");
    expect(await entries.count()).toBeGreaterThan(0);
    const newest = (await entries.first().getAttribute("data-update"))!;
    await expect(page.getByRole("heading", { level: 1 })).toContainText(t.support.updates.title);
    await expect(
      page.getByTestId("update-from-readers"),
      "no entry claims the readers' comments yet",
    ).toHaveCount(0);
    await expect
      .poll(() =>
        sql(
          `SELECT array_to_string(hints_seen, ',') FROM customer.preferences WHERE user_id = ${reader.id}`,
        ),
      )
      .toContain(`updates:${newest}`);
    await expect(more.getByTestId("tab-more-dot")).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId("tab-more").getByTestId("tab-more-dot")).toHaveCount(0);
    expect(await smallTargets(page, '[data-testid="updates"]')).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    ).toBeLessThanOrEqual(1);
    await close();
  });

  test("/admin/product: the survey with its n and the comments - never who wrote them", async ({
    browser,
  }) => {
    const context = await browser.newContext({
      storageState: statePath("admin"),
      viewport: DESK,
      baseURL: BASE,
      locale: "es-ES",
      timezoneId: "America/Bogota",
    });
    const page = await context.newPage();
    const answers = Number(
      sql(
        `SELECT count(*) FROM customer.feedback WHERE kind = 'csat' AND created_at > now() - interval '90 days'`,
      ),
    );
    await page.goto("/admin/product");
    const card = page.getByTestId("feedback-card");
    await expect(card).toBeVisible();
    await expect(card.getByTestId("feedback-n")).toContainText(String(answers));
    const comments = card.getByTestId("feedback-comments");
    await expect(comments).toContainText("Las lecturas; escríbanme a [dato quitado]");
    for (const r of made) await expect(card).not.toContainText(r.email);
    await expect(card).not.toContainText("@");
    await context.close();
  });
});

test.describe("FBI_FEEDBACK=0", () => {
  test.skip(!OFF, "only against the API with FBI_FEEDBACK=0");

  test("no survey and no question - the answers stay", async ({ page }) => {
    await page.setViewportSize(DESK);
    const reader = await account("off");
    sql(
      `INSERT INTO customer.feedback (user_id, kind, subject, subject_id, helpful, context)
       VALUES (${reader.id}, 'helpful', 'reading', 1, true, '{}')`,
    );
    await signIn(page, reader.email);
    const state = await survey(page);
    expect([state.enabled, state.due]).toEqual([false, false]);
    const fixture = await matchToRead(page);
    await openTab(page, fixture, "analysis");
    await expect(page.getByTestId("match-reading")).toBeVisible();
    await page.waitForTimeout(WAIT_NONE);
    await expect(page.getByTestId("csat-prompt")).toHaveCount(0);
    await expect(page.getByTestId("helpful-vote")).toHaveCount(0);
    const refused = await sendJson<{ error: { code: string } }>(
      page.request,
      "POST",
      "/api/v1/me/feedback/survey",
      {
        score: 5,
      },
    );
    expect([refused.status, refused.body.error.code]).toEqual([404, "feedback_off"]);
    expect(feedbackRows(reader.id), "the answers stay").toHaveLength(1);
    // Novedades is not feedback: it stays
    await page.goto("/updates");
    await expect(page.getByTestId("update").first()).toBeVisible();
  });
});
