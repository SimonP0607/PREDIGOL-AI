/**
 * Email opcional (plan UX, B8; section 33): the weekly summary by e-mail, in the browser against the API and the QA
 * messenger, on reader accounts the test makes and deletes.
 *
 * «Criterio de terminado: solo lo recibe quien lo pidió, la baja es inmediata y nunca se superan los límites del plan de
 * Resend.» And B8's QA: «E2E: casilla y baja».
 *
 * * Born off (E2E_DIGEST_OFF=1, the QA stack without QA_DIGEST - production's state until the owner decides): the profile
 *   offers no box, the API records no request for it (422 not_offered) and Privacy lists the four of the gate.
 * * On (E2E_DIGEST=1, the QA stack with QA_DIGEST=1 QA_MESSENGER=1, E2E_MAIL_SINK): «Notificaciones» shows the box off,
 *   with the processing policy's sentence; asking records the decision (from the profile, with the text's version and
 *   hash) and the summary reaches the reader by the commercial sender - another domain than the account's - with the
 *   one-click headers (RFC 8058) and a leaving link, counts only; a reader who did not ask gets none. The link's page,
 *   with no session, changes nothing on opening; its button leaves at once (from an e-mail) and says so, and the profile
 *   says since when; a second visit says the reader had already left. The mail client's own one-click POST - no session,
 *   no PrediGol header - leaves too. Privacy then lists the decision and sends its change to Notificaciones. The box and
 *   the page at 320 px: axe clean and 44 px targets.
 *
 * Every decision is checked against SQL written here (E2E_DATABASE_URL); the QA messenger makes a consenting reader's
 * summary due at its next cycle (--digest-any-day: production waits for the reader's day, from 09:00 in their zone - the
 * backend's tests hold that, the daily cap and the week's dedup).
 */
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
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
const SINK = process.env["E2E_MAIL_SINK"] ?? "";
const OFF = process.env["E2E_DIGEST_OFF"] === "1";
const PASSWORD = "Once-a-week-on-my-day-26"; // gitleaks:allow - a QA account's password, made and deleted here
const PHONE = { width: 320, height: 720 };
/** The commercial sender api-up.sh gives the QA stack with QA_DIGEST=1 (the account's: avisos@correo.predigol.local). */
const COMMERCIAL = "PrediGol <resumen@novedades.predigol.local>";
/** The QA messenger's cycle is 60 s: a summary owed now is queued within a cycle and handed over the next second. */
const ARRIVES = 150_000;
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const t = L.es;

test.describe.configure({ mode: "serial" });

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

async function account(tag: string): Promise<Reader> {
  const admin = await owner();
  const email = `e2e.digest.${tag}.${Date.now()}@predigol.local`;
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

/** A 320 px touch phone in Spanish, Bogotá's time. */
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

/** The reader's decisions on the weekly summary, oldest first: granted, source, version, the hash's length. */
function decisions(id: number): string[] {
  const out = sql(
    `SELECT granted, source, version, length(sha256) FROM customer.consents ` +
      `WHERE user_id = ${id} AND kind = 'marketing_email' ORDER BY at, id`,
  );
  return out ? out.split("\n") : [];
}

interface Purpose {
  kind: string;
  version: string;
}

async function privacyVersion(api: APIRequestContext): Promise<string> {
  const state = await getJson<{ purposes: Purpose[] }>(api, "/api/v1/me/consents?lang=es");
  expect(state.status).toBe(200);
  const privacy = state.body.purposes.find((p) => p.kind === "privacy");
  expect(privacy, "the processing policy's purpose").toBeTruthy();
  return privacy?.version ?? "";
}

interface Mail {
  to: string;
  subject: string;
  text: string;
  template: string;
  category: string;
  at: string;
  sender: string | null;
  headers: Record<string, string>;
}

function mails(to: string, template: string, since: number): Mail[] {
  return readdirSync(SINK)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(readFileSync(join(SINK, f), "utf8")) as Mail)
    .filter((m) => m.to === to && m.template === template && Date.parse(m.at) >= since)
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

async function mailFor(to: string, template: string, since: number): Promise<Mail> {
  let found: Mail | undefined;
  await expect(async () => {
    found = mails(to, template, since)[0];
    expect(found, `an e-mail "${template}" to ${to} in ${SINK}`).toBeTruthy();
  }).toPass({ timeout: ARRIVES, intervals: [2_000] });
  return found as Mail;
}

async function axe(page: Page, include: string): Promise<void> {
  const result = await new AxeBuilder({ page }).include(include).withTags(AXE_TAGS).analyze();
  expect(
    result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
  ).toEqual([]);
}

test.describe("born off (production's default)", () => {
  test.skip(!OFF, "E2E_DIGEST_OFF=1 against the QA stack without QA_DIGEST");

  test("the profile offers no box, the API records no request for it, Privacy lists the four of the gate", async ({
    browser,
  }) => {
    const reader = await account("off");
    const { page, close } = await phone(browser);
    await signIn(page, reader.email);
    await page.goto("/profile#notifications");
    await expect(page.getByTestId("notifications")).toBeVisible();
    await expect(page.getByTestId("notify-membership")).toBeVisible();
    await expect(page.getByTestId("digest")).toHaveCount(0);
    const state = await getJson<{ purposes: Purpose[] }>(
      page.request,
      "/api/v1/me/consents?lang=es",
    );
    expect(state.body.purposes.map((p) => p.kind)).toEqual([
      "terms",
      "privacy",
      "age_18",
      "risk_notice",
    ]);
    const version = await privacyVersion(page.request);
    const r = await sendJson<{ error: { code: string } }>(
      page.request,
      "POST",
      "/api/v1/me/consents",
      {
        decisions: [{ kind: "marketing_email", granted: true, version }],
        locale: "es",
        source: "profile",
      },
    );
    expect([r.status, r.body.error.code]).toEqual([422, "not_offered"]);
    expect(decisions(reader.id)).toEqual([]);
    await page.goto("/profile#privacy");
    await expect(page.getByTestId("privacy-consent-privacy")).toBeVisible();
    await expect(page.getByTestId("privacy-consent-marketing_email")).toHaveCount(0);
    await close();
  });
});

test.describe("on, with the QA messenger", () => {
  test.skip(OFF, "E2E_DIGEST=1 against the QA stack with QA_DIGEST=1 QA_MESSENGER=1");
  test.beforeAll(() => {
    expect(SINK, "E2E_MAIL_SINK: the QA messenger's folder (api-up.sh QA_MESSENGER=1)").not.toBe(
      "",
    );
    expect(DB, "E2E_DATABASE_URL: the QA database").not.toBe("");
  });

  test("asked for in the profile, it arrives by its own sender with the way out; the link's page leaves in one tap, once; a reader who did not ask gets nothing", async ({
    browser,
  }) => {
    test.setTimeout(8 * 60_000);
    const reader = await account("on");
    const bystander = await account("bystander");
    const since = Date.now();
    const { page, close } = await phone(browser);
    await signIn(page, reader.email);

    // the box: off, with the policy's sentence, and how it arrives
    await page.goto("/profile#notifications");
    const box = page.getByTestId("digest");
    await expect(box).toBeVisible();
    const toggle = box.getByTestId("digest-switch");
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(box).toContainText(t.profile.notifications.digest.title);
    await expect(box).toContainText("Quiero recibir por correo el resumen semanal de PrediGol");
    await expect(box).toContainText(t.profile.notifications.digest.help);
    await axe(page, '[data-testid="digest"]');
    expect(await smallTargets(page, '[data-testid="digest"]')).toEqual([]);

    // asking for it: one decision from the profile, with the text's version and hash
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    await expect(box.getByTestId("digest-since")).toContainText("Lo pediste el");
    const version = await privacyVersion(page.request);
    expect(decisions(reader.id)).toEqual([`t|profile|${version}|64`]);

    // the summary: by the commercial sender, with the one-click headers and the leaving link, counts only
    const mail = await mailFor(reader.email, "weekly_digest", since);
    expect(mail.category).toBe("marketing");
    expect(mail.sender).toBe(COMMERCIAL);
    expect(mail.subject).toBe("Tu semana en PrediGol");
    expect(mail.headers["List-Unsubscribe-Post"]).toBe("List-Unsubscribe=One-Click");
    const oneClick =
      /^<(https?:\/\/\S+\/api\/v1\/email\/unsubscribe\?t=([0-9]+x[0-9]+x[A-Za-z0-9_-]{22}))>$/.exec(
        mail.headers["List-Unsubscribe"] ?? "",
      );
    expect(oneClick, "List-Unsubscribe: PrediGol's one-click address").toBeTruthy();
    const token = oneClick?.[2] ?? "";
    expect(mail.text).toContain(`/unsubscribe#t=${token}`);
    expect(mail.text).toContain("Recibes este resumen porque lo pediste en tu perfil.");
    expect(mail.text).toContain("Darte de baja en un clic");
    expect(mail.text).not.toMatch(/%|unidad|cuota/i);
    expect(mails(bystander.email, "weekly_digest", since), "nobody who did not ask").toEqual([]);

    // the link's page, with no session: nothing on opening; the button leaves at once
    const visitor = await browser.newContext({
      ...devices["Pixel 7"],
      viewport: PHONE,
      baseURL: BASE,
      locale: "es-ES",
    });
    const link = await visitor.newPage();
    await link.goto(`/unsubscribe#t=${token}`);
    await expect(link.getByTestId("unsubscribe-page")).toBeVisible();
    await expect(link.getByTestId("unsubscribe-page")).toContainText(
      t.auth.account.unsubscribeBody,
    );
    await expect(link).not.toHaveURL(/#t=/);
    expect(decisions(reader.id), "opening the page changes nothing").toEqual([
      `t|profile|${version}|64`,
    ]);
    await axe(link, '[data-testid="unsubscribe-page"]');
    expect(await smallTargets(link, '[data-testid="unsubscribe-page"]')).toEqual([]);
    await link.getByTestId("unsubscribe-submit").click();
    await expect(link.getByTestId("unsubscribe-done")).toHaveText(t.auth.account.unsubscribeDone);
    expect(decisions(reader.id)).toEqual([`t|profile|${version}|64`, `f|email|${version}|64`]);

    // a second visit (a new load: the same address with another fragment would not reload the page): the reader had
    // already left, nothing more is written
    await link.goto("about:blank");
    await link.goto(`/unsubscribe#t=${token}`);
    await link.getByTestId("unsubscribe-submit").click();
    await expect(link.getByTestId("unsubscribe-already")).toHaveText(
      t.auth.account.unsubscribeAlready,
    );
    expect(decisions(reader.id)).toHaveLength(2);
    // a link that is not PrediGol's
    await link.goto("about:blank");
    await link.goto(`/unsubscribe#t=${token.slice(0, -1)}${token.endsWith("A") ? "B" : "A"}`);
    await link.getByTestId("unsubscribe-submit").click();
    await expect(link.getByTestId("link-invalid")).toHaveText(t.auth.account.unsubscribeInvalid);
    await visitor.close();

    // the profile says since when; asked again, the mail client's one-click POST leaves too
    await page.reload();
    await expect(toggle).toHaveAttribute("aria-checked", "false");
    await expect(box.getByTestId("digest-since")).toContainText("Te diste de baja el");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-checked", "true");
    const mailClient = await request.newContext(); // no session, no PrediGol header, no Origin
    const clicked = await mailClient.post(oneClick?.[1] ?? "", {
      headers: { "content-type": "application/x-www-form-urlencoded" },
      data: "List-Unsubscribe=One-Click",
    });
    expect(clicked.status()).toBe(200);
    expect(await clicked.json()).toEqual({ left: true });
    await mailClient.dispose();
    expect(decisions(reader.id).slice(-1)).toEqual([`f|email|${version}|64`]);

    // Privacy lists the decision and sends its change to Notificaciones
    await page.goto("about:blank");
    await page.goto("/profile#privacy");
    const row = page.getByTestId("privacy-consent-marketing_email");
    await expect(row).toBeVisible();
    await expect(row.getByTestId("privacy-optional")).toContainText(t.legal.privacy.optional);
    await expect(row.getByTestId("privacy-withdraw")).toHaveCount(0);
    await close();
  });
});
