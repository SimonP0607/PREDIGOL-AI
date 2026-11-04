/**
 * Help and support (plan UX, A14; gate G10), in the browser against the API, on accounts the test makes and deletes:
 *
 * * Ayuda two taps from any screen (the account menu): the questions and their accent-blind search;
 * * «Reportar un problema» from Ayuda: a category, the words, what goes with them; the ticket arrives in the owner's
 *   Soporte with its context, is answered there (the reader is told by e-mail: the queue holds the message), and the
 *   reader reads the answer, closes it and says how easy it was;
 * * from an error: the sheet carries that error's reference; from a match: «¿Ves un dato incorrecto?» carries the match;
 * * the sheet on a 320 px phone: big options with labels, nothing sideways, every control in a finger's reach, axe 0;
 * * another reader's ticket is «not found», and the inbox is the owner's alone;
 * * whoever cannot sign in finds the contact under the sign-in, once the owner has given it;
 * * with the QA messenger (E2E_MAIL_SINK), the receipt and the answer reach the reader's mailbox with the number, never
 *   the words; with QA_SUPPORT=0 (FBI_SUPPORT=0), the tickets go and Ayuda, its contact and the reading stay.
 */
import AxeBuilder from "@axe-core/playwright";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import {
  expect,
  request,
  test,
  type APIRequestContext,
  type Browser,
  type Page,
} from "@playwright/test";
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
const PASSWORD = "Tarde-de-copa-en-casa-26"; // gitleaks:allow - a QA account's password, made and deleted here
const SAME_SITE = { "x-requested-with": "predigol" };
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const t = L.es;
const s = t.support;

interface AdminTicket {
  id: number;
  user_id: number;
  category: string;
  status: string;
  context: {
    route?: string;
    request_id?: string;
    device?: string;
    pwa?: boolean;
    match_id?: number;
  } | null;
  messages: Array<{ author: string; body: string; channel: string }>;
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(
  admin: APIRequestContext,
  kind: string,
): Promise<{ id: number; email: string }> {
  const email = `e2e.support.${kind}.${Date.now()}@predigol.local`;
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

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
  await skipWelcome(page.request);
  const gate = page.getByTestId("consent-gate");
  await page.goto("/home");
  // the consents first when QA's gate is on (drafts), else straight into the product
  await expect(gate.or(page.getByTestId("account-menu"))).toBeVisible({ timeout: 30_000 });
  if (await gate.isVisible()) {
    for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
      await gate.getByTestId(`consent-${kind}`).check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
  }
}

async function inboxTicket(admin: APIRequestContext, id: number): Promise<AdminTicket> {
  const inbox = await getJson<{ tickets: AdminTicket[] }>(
    admin,
    "/api/v1/admin/support?status=all",
  );
  expect(inbox.status).toBe(200);
  const found = inbox.body.tickets.find((x) => x.id === id);
  expect(found, `ticket ${id} in the owner's inbox`).toBeTruthy();
  return found as AdminTicket;
}

interface Mail {
  to: string;
  template: string;
  text: string;
  html?: string;
  at: string;
}

/** With the QA messenger writing every e-mail to E2E_MAIL_SINK: the one of ``template`` to ``to`` since ``since``. */
async function mailTo(to: string, template: string, since: number): Promise<Mail> {
  let found: Mail | undefined;
  await expect(async () => {
    found = readdirSync(SINK)
      .filter((f) => f.endsWith(".json"))
      .map((f) => JSON.parse(readFileSync(join(SINK, f), "utf8")) as Mail)
      .find((m) => m.to === to && m.template === template && Date.parse(m.at) >= since);
    expect(found, `${template} to ${to} in ${SINK}`).toBeTruthy();
  }).toPass({ timeout: 90_000, intervals: [1_000] });
  return found as Mail;
}

/** Opens the sheet's form and sends ``text`` under ``category`` (when given); the ticket's number. */
async function sendReport(page: Page, text: string, category?: string): Promise<number> {
  const sheet = page.getByTestId("report-sheet");
  await expect(sheet).toBeVisible();
  if (category) await sheet.getByTestId(`report-category-${category}`).click();
  await sheet.getByTestId("report-text").fill(text);
  await sheet.getByTestId("report-send").click();
  const done = sheet.getByTestId("report-done");
  await expect(done).toBeVisible();
  const m = /n\.º (\d+)/.exec((await done.innerText()) ?? "");
  expect(m, "the receipt says the ticket's number").toBeTruthy();
  return Number(m?.[1]);
}

async function adminPage(browser: Browser): Promise<Page> {
  const ctx = await browser.newContext({
    storageState: statePath("admin"),
    viewport: { width: 1440, height: 900 },
  });
  return ctx.newPage();
}

test("Ayuda in two taps, a ticket with its context answered in Soporte, read, closed and rated", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin, "help");
  try {
    const w = watch(page, { expect401: true });
    await signIn(page, email);
    // two taps from any screen: the account menu, then Ayuda
    for (const from of ["/home", "/picks", "/my-picks"]) {
      await page.goto(from);
      await page.getByTestId("account-menu").click();
      await page.getByTestId("go-help").click();
      await expect(page).toHaveURL(/\/help$/);
      await expect(page.getByTestId("help-page")).toBeVisible();
    }
    // the questions, and the search without accents
    await page.getByTestId("help-search").fill("contrasena");
    const found = page.locator('[data-faq="cant_sign_in"]');
    await expect(found).toBeVisible();
    await expect(found).toHaveAttribute("open", "");
    await expect(found).toContainText(s.faq.cant_sign_in.a.slice(0, 40));
    await page.getByTestId("help-search").fill("");
    await expect(page.getByTestId("help-question")).toHaveCount(23);
    await settle(page);
    await assertClean(page, w);

    // a ticket from Ayuda
    await page.getByTestId("help-report").first().click();
    const sheet = page.getByTestId("report-sheet");
    await expect(sheet.getByTestId("report-context")).toContainText("/help");
    const words = `No me cargan los partidos de hoy (e2e ${Date.now()})`;
    const since = Date.now() - 5_000;
    const ticketId = await sendReport(page, words, "technical");
    await sheet.getByTestId("report-see").click();
    await expect(page).toHaveURL(new RegExp(`/help/messages/${ticketId}$`));
    await expect(page.getByTestId("ticket-status")).toHaveText(s.ticket.status.open);
    await expect(page.getByTestId("ticket-respond-by")).toBeVisible();
    await expect(page.getByTestId("ticket-thread")).toContainText(words);

    // the owner: the ticket with its context, answered in Soporte
    const kept = await inboxTicket(admin, ticketId);
    expect(kept.user_id).toBe(id);
    expect(kept.category).toBe("technical");
    expect(kept.context).toMatchObject({ route: "/help", device: "desktop", pwa: false });
    const consolePage = await adminPage(browser);
    try {
      await consolePage.goto("/admin/support");
      const row = consolePage.getByTestId(`support-ticket-${ticketId}`);
      await expect(row).toBeVisible();
      await row.getByRole("button").first().click();
      await expect(consolePage.getByTestId(`support-context-${ticketId}`)).toContainText("/help");
      const form = consolePage.getByTestId(`support-answer-${ticketId}`);
      await form
        .locator("textarea")
        .fill("Ya está: era la caché del navegador. Recarga la página.");
      await form.getByTestId(`support-answer-send-${ticketId}`).click();
      // the console speaks its account's language
      await expect(form.getByRole("status")).toHaveText(
        new RegExp(`^(${s.admin.notice}|${L.en.support.admin.notice})$`.replace(/\./g, "\\.")),
      );
    } finally {
      await consolePage.context().close();
    }
    // the e-mail is queued for the reader (sent once the owner turns sending on)
    const queue = await getJson<{ messages: Array<{ template: string; user_email: string }> }>(
      admin,
      "/api/v1/admin/messages",
    );
    expect(
      queue.body.messages.some(
        (m) => m.template === "support_ticket_answered" && m.user_email === email,
      ),
      "the answer's e-mail is in the queue",
    ).toBe(true);

    // with the QA messenger on: the receipt and the answer reach the reader's mailbox with the number - never the words
    if (SINK) {
      for (const template of ["support_ticket_received", "support_ticket_answered"]) {
        const mail = await mailTo(email, template, since);
        expect(mail.text).toContain(String(ticketId));
        expect(mail.text).not.toContain(words);
        expect(mail.text).not.toContain("era la caché del navegador");
        expect(mail.text).toContain(`/help/messages/${ticketId}`);
      }
    }
    // the reader reads it, closes it, says how easy it was
    await page.reload();
    await expect(page.getByTestId("ticket-status")).toHaveText(s.ticket.status.answered);
    await expect(page.getByTestId("ticket-thread")).toContainText("era la caché del navegador");
    await page.getByTestId("ticket-resolved").click();
    await expect(page.getByTestId("ticket-effort")).toBeVisible();
    await page.getByTestId("ticket-effort-4").click();
    await expect(page.getByTestId("ticket-effort-done")).toContainText(s.ticket.effort.scale["4"]);
    expect((await inboxTicket(admin, ticketId)).status).toBe("closed");
    await settle(page);
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("from an error the sheet carries its reference; from a match, the match", async ({ page }) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "error");
  try {
    await signIn(page, email);
    // Home's board fails once, on purpose, with a request id the server would have logged
    await page.route(/\/api\/v1\/today(\?.*)?$/, (route) =>
      route.fulfill({
        status: 500,
        headers: { "content-type": "application/json", "x-request-id": "e2e500abc123" },
        body: JSON.stringify({
          error: { code: "internal", message: "boom" },
          request_id: "e2e500abc123",
        }),
      }),
    );
    await page.goto("/home");
    const report = page.getByTestId("error-report").first();
    await expect(report).toBeVisible({ timeout: 30_000 });
    await report.click();
    const sheet = page.getByTestId("report-sheet");
    await expect(sheet.getByTestId("report-category-technical").locator("input")).toBeChecked();
    await expect(sheet.getByTestId("report-context")).toContainText("e2e500abc123");
    const fromError = await sendReport(page, "Inicio dice que no pudo cargar");
    await page.unroute(/\/api\/v1\/today(\?.*)?$/);
    expect((await inboxTicket(admin, fromError)).context).toMatchObject({
      route: "/home",
      request_id: "e2e500abc123",
    });
    await page.keyboard.press("Escape");

    // a match: the first one Inicio knows of
    const board = await getJson<{ data: { matches: { data: Array<{ fixture_id: number }> } } }>(
      page.request,
      "/api/v1/today",
    );
    const matchId = board.body?.data?.matches?.data?.[0]?.fixture_id;
    test.skip(
      !matchId,
      "QA has no match on Inicio's board today: the match's report is not exercised",
    );
    await page.goto(`/matches/${matchId}`);
    await page.getByTestId("match-report").click();
    await expect(sheet.getByTestId("report-category-wrong_data").locator("input")).toBeChecked();
    await expect(sheet).toContainText(s.report.matchLinked);
    const fromMatch = await sendReport(page, "El marcador del descanso no es el que vi");
    expect((await inboxTicket(admin, fromMatch)).context).toMatchObject({ match_id: matchId });
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("the sheet on a 320 px phone: big options with labels, nothing sideways, in reach, axe 0", async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const admin = await owner();
  const { id, email } = await account(admin, "phone");
  const ctx = await browser.newContext({
    viewport: { width: 320, height: 720 },
    hasTouch: true,
    isMobile: true,
  });
  const page = await ctx.newPage();
  try {
    const w = watch(page, { expect401: true });
    await signIn(page, email);
    await page.goto("/help");
    await settle(page);
    await assertClean(page, w);
    await page.getByTestId("help-report").first().click();
    const sheet = page.getByTestId("report-sheet");
    await expect(sheet).toBeVisible();
    const box = await sheet.boundingBox();
    expect(box?.width ?? 0, "the sheet fits the screen").toBeLessThanOrEqual(320);
    expect(await smallTargets(page, '[data-testid="report-sheet"]')).toEqual([]);
    for (const c of ["access", "account", "technical", "wrong_data", "suggestion", "complaint"]) {
      const option = sheet.getByTestId(`report-category-${c}`);
      expect(
        (await option.boundingBox())?.height ?? 0,
        `${c}: a big option`,
      ).toBeGreaterThanOrEqual(44);
    }
    await expect(sheet.getByLabel(s.report.textLabel)).toBeVisible();
    const axe = await new AxeBuilder({ page })
      .include('[data-testid="report-sheet"]')
      .withTags(WCAG)
      .analyze();
    expect(axe.violations.map((v) => v.id)).toEqual([]);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  } finally {
    await ctx.close();
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("another reader's ticket is not found and the inbox is the owner's alone", async ({
  page,
  browser,
}) => {
  test.setTimeout(120_000);
  const admin = await owner();
  const one = await account(admin, "one");
  const two = await account(admin, "two");
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const other = await ctx.newPage();
  try {
    await signIn(page, one.email);
    const created = await page.request.post("/api/v1/me/support/tickets", {
      headers: { ...SAME_SITE, "content-type": "application/json" },
      data: { category: "suggestion", text: "Más ligas de Sudamérica" },
    });
    expect(created.status()).toBe(201);
    const ticketId = ((await created.json()) as { id: number }).id;
    await signIn(other, two.email);
    for (const [path, body] of [
      [`/api/v1/me/support/tickets/${ticketId}/messages`, { text: "hola" }],
      [`/api/v1/me/support/tickets/${ticketId}/close`, {}],
    ] as const) {
      const r = await other.request.post(path, {
        headers: { ...SAME_SITE, "content-type": "application/json" },
        data: body,
      });
      expect(r.status(), path).toBe(404);
    }
    const mine = await getJson<{ tickets: unknown[] }>(other.request, "/api/v1/me/support");
    expect(mine.body.tickets).toEqual([]);
    expect(
      (await other.request.get("/api/v1/admin/support", { headers: SAME_SITE })).status(),
    ).toBe(403);
    await other.goto(`/help/messages/${ticketId}`);
    await expect(other.getByTestId("ticket-missing")).toBeVisible();
    const crossSite = await other.request.post("/api/v1/me/support/tickets", {
      headers: { "content-type": "application/json" },
      data: { category: "technical", text: "x" },
    });
    expect(crossSite.status(), "without the same-site header: refused").toBe(403);
  } finally {
    await ctx.close();
    await remove(admin, one.id, one.email);
    await remove(admin, two.id, two.email);
    await admin.dispose();
  }
});

test("whoever cannot sign in finds the contact under the sign-in", async ({ browser }) => {
  const anon = await request.newContext({ baseURL: BASE });
  const contact = await getJson<{ whatsapp: string | null; email: string | null }>(
    anon,
    "/api/v1/support/contact",
  );
  await anon.dispose();
  expect(contact.status).toBe(200);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  try {
    await page.goto("/login");
    await expect(page.getByTestId("login-submit")).toBeVisible();
    if (!contact.body.whatsapp && !contact.body.email) {
      await expect(page.getByTestId("login-contact")).toHaveCount(0);
      test.info().annotations.push({
        type: "data",
        description: "no contact given (P7): nothing is offered",
      });
      return;
    }
    const block = page.getByTestId("login-contact");
    await expect(block).toContainText(s.login.trouble);
    if (contact.body.whatsapp) {
      await expect(block.getByTestId("login-whatsapp")).toHaveAttribute(
        "href",
        new RegExp(`^https://wa\\.me/${contact.body.whatsapp}\\?text=`),
      );
    }
  } finally {
    await ctx.close();
  }
});

test("with FBI_SUPPORT=0 the tickets go and Ayuda, its contact and the reading stay", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const admin = await owner();
  const { id, email } = await account(admin, "off");
  try {
    await signIn(page, email);
    const me = await getJson<{ support?: boolean }>(page.request, "/api/v1/auth/me");
    test.skip(me.body.support !== false, "tickets are on in this run (QA_SUPPORT=0 runs this)");
    await page.goto("/help");
    await expect(page.getByTestId("help-page")).toBeVisible();
    await expect(page.getByTestId("help-report")).toHaveCount(0);
    const contact = page.getByTestId("help-contact");
    await expect(contact).toBeVisible();
    const state = await getJson<{ contact: { whatsapp: string | null } }>(
      page.request,
      "/api/v1/me/support",
    );
    if (state.body.contact.whatsapp)
      await expect(contact.getByTestId("help-whatsapp")).toBeVisible();
    await page.route(/\/api\/v1\/today(\?.*)?$/, (route) =>
      route.fulfill({
        status: 500,
        headers: { "content-type": "application/json", "x-request-id": "e2eoff500abc" },
        body: JSON.stringify({ error: { code: "internal" }, request_id: "e2eoff500abc" }),
      }),
    );
    await page.goto("/home");
    await expect(
      page.getByText(t.errors.requestId.replace("{id}", "e2eoff500abc")).first(),
    ).toBeVisible({
      timeout: 30_000,
    });
    await expect(
      page.getByTestId("error-report"),
      "no «Reportar un problema» while tickets are off",
    ).toHaveCount(0);
    const refused = await page.request.post("/api/v1/me/support/tickets", {
      headers: { ...SAME_SITE, "content-type": "application/json" },
      data: { category: "technical", text: "x" },
    });
    expect(refused.status()).toBe(404);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});
