/**
 * Getting in without the owner (plan UX, A7; R11, R25 of the security plan), in the browser against the API, on
 * accounts the test makes and deletes at the end. Two configurations of the QA stack:
 *
 * * self-service off - production's default until the owner turns it on (FBI_SELF_SERVICE): the sign-in page offers
 *   no recovery, the pages say how to get back in (the owner gives a temporary password), the API's routes do not
 *   exist and the console creates accounts with a temporary password, as before.
 * * self-service on, with the QA messenger (api-up.sh with QA_SELF_SERVICE=1 QA_MESSENGER=1; E2E_MAIL_SINK = its
 *   folder, where each e-mail is a file instead of leaving): the owner invites from the console and the e-mail's
 *   one-use link activates the account - the password with its meter, the language, the time zone and the consents -
 *   and signs in, and never works again; a forgotten password gets the same answer for any address and its link ends
 *   every session; a locked account asks for its unlock link from the sign-in page; ending another session asks who
 *   asks; an invitation is withdrawn by anonymising it. The reader's pages run at 320 px, with fields of 16 px.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const SINK = process.env["E2E_MAIL_SINK"] ?? "";
const SAME_SITE = { "x-requested-with": "predigol" };
const t = L.es;
const FIRST = "Primera-clave-del-lector-26"; // gitleaks:allow - a QA account's password, made and deleted here
const SECOND = "Segunda-clave-del-lector-26"; // gitleaks:allow - a QA account's password, made and deleted here
const CHOSEN = "La-final-se-juega-en-mayo"; // gitleaks:allow - the password an invited QA reader chooses
const PHONE = { width: 320, height: 720 };

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
  expect(r.status).toBe(200);
  return r.body.self_service;
}

/** An account of the test's own, made by the owner with a known password. */
async function account(
  admin: APIRequestContext,
  kind: string,
): Promise<{ id: number; email: string }> {
  const email = `e2e.${kind}.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number } }>(admin, "POST", "/api/v1/admin/users", {
    email,
    password: FIRST,
    role: "USER",
    language: "es",
    timezone: "America/Bogota",
    must_change_password: false,
  });
  expect(created.status, "the owner creates the test's account").toBe(201);
  return { id: created.body.data.id, email };
}

/** At the end: the account is deleted as anonymisation (the console's own way), whatever happened. */
async function remove(admin: APIRequestContext, id: number, email: string): Promise<void> {
  const r = await sendJson(admin, "POST", `/api/v1/admin/users/${id}/anonymise`, {
    confirm: email,
  });
  expect([200, 409], `the test's account ${id} is deleted`).toContain(r.status);
}

interface Mail {
  to: string;
  subject: string;
  text: string;
  template: string;
  at: string;
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
  }).toPass({ timeout: 60_000, intervals: [1_000] });
  return found as Mail;
}

/** The page and the token of an e-mail's link: the token travels in the fragment, never in a URL a server sees. */
function linkOf(mail: Mail, path: "/activate" | "/reset-password" | "/unlock"): string {
  const m = new RegExp(`https?://\\S+?${path}#t=([A-Za-z0-9_-]{43})\\b`).exec(mail.text);
  expect(m, `the e-mail carries a ${path} link`).toBeTruthy();
  return `${path}#t=${m?.[1] ?? ""}`;
}

async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByTestId("login-submit").click();
}

/** Every field of the reader's form at 16 px: a phone does not zoom into it. */
async function sixteen(page: Page, testIds: string[]): Promise<void> {
  for (const id of testIds) await expect(page.getByTestId(id)).toHaveCSS("font-size", "16px");
}

test.describe("self-service off (production's default)", () => {
  test.beforeEach(async () => {
    test.skip(await selfService(), "the QA API runs with self-service on");
  });

  test("nothing is offered: no recovery on the sign-in page, the pages say how to get back in, the routes do not exist", async ({
    page,
    browser,
  }) => {
    const w = watch(page, { expect401: true });
    await page.goto("/login");
    await expect(page.getByTestId("login-submit")).toBeVisible();
    await expect(page.getByTestId("forgot-link")).toHaveCount(0);
    await page.goto("/forgot-password");
    await expect(page.getByTestId("self-service-off")).toHaveText(t.auth.account.forgotOff);
    await expect(page.getByTestId("forgot-form")).toHaveCount(0);
    await assertClean(page, w);
    const api = await anonymous();
    for (const path of ["/api/v1/auth/password/forgot", "/api/v1/auth/unlock/request"]) {
      const r = await api.post(path, { data: { email: "someone@predigol.local" } });
      expect(r.status(), path).toBe(404);
    }
    await api.dispose();

    // the console: no «Invite», the account is created with a temporary password as before
    const ownerPage = await (
      await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
    ).newPage();
    await ownerPage.goto("/admin/users");
    await expect(ownerPage.getByTestId("self-service-off")).toHaveText(
      L.en.admin.users.selfServiceOff,
    );
    await expect(ownerPage.getByTestId("invite-user")).toHaveCount(0);
    await expect(ownerPage.getByTestId("new-user")).toHaveText(L.en.admin.users.newUser);
    await ownerPage.context().close();
  });
});

test.describe("self-service on, with the QA messenger", () => {
  test.beforeEach(async () => {
    test.skip(!(await selfService()), "the QA API runs with self-service off");
    expect(SINK, "E2E_MAIL_SINK: the QA messenger's folder (api-up.sh QA_MESSENGER=1)").not.toBe(
      "",
    );
  });

  test("the owner invites; the e-mail's link activates the account with its password, language, zone and consents, signs in and never works again", async ({
    page,
    browser,
  }) => {
    test.setTimeout(180_000);
    const admin = await owner();
    const email = `e2e.invite.${Date.now()}@predigol.local`;
    let id = 0;
    try {
      // 1. the console: «Invite» first, the temporary password as the backup
      const ownerPage = await (
        await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
      ).newPage();
      await ownerPage.goto("/admin/users");
      await expect(ownerPage.getByTestId("new-user")).toHaveText(L.en.admin.users.temporaryBackup);
      const since = Date.now();
      await ownerPage.getByTestId("invite-user").click();
      const form = ownerPage.getByTestId("invite-form");
      await form.getByTestId("invite-email").fill(email);
      await form.getByTestId("invite-alias").fill("Invitada E2E");
      await form.getByTestId("invite-language").selectOption("es");
      await form.getByTestId("invite-timezone").selectOption("America/Bogota");
      await form.getByTestId("invite-submit").click();
      await expect(ownerPage.getByTestId("users-notice")).toContainText(email);
      const row = ownerPage.locator("tr", { hasText: email });
      await expect(row).toContainText(L.en.admin.users.invited);
      id = Number((await row.getAttribute("data-testid"))?.replace("user-row-", ""));
      expect(id).toBeGreaterThan(0);

      // 2. the e-mail: its link, in the reader's language; the token only there
      const mail = await mailFor(email, "invitation", since);
      const link = linkOf(mail, "/activate");

      // 3. the reader, on a phone: the page reads the link and takes it out of the address at once
      await page.setViewportSize(PHONE);
      // 403 consent_required while the boxes are owed; 401 from the anonymous /auth/me
      const w = watch(page, { expect401: true, expectStatus: [403] });
      await page.goto(link);
      await expect(page.getByTestId("activate-form")).toBeVisible();
      expect(await page.evaluate(() => window.location.hash), "the token left the address").toBe(
        "",
      );
      await expect(page.getByTestId("account-email")).toHaveValue(email);
      await expect(page.getByTestId("activate-language")).toHaveValue("es");
      await expect(page.getByTestId("activate-timezone")).toHaveValue("America/Bogota");
      await sixteen(page, [
        "account-email",
        "new-password",
        "new-password-repeat",
        "activate-language",
        "activate-timezone",
      ]);
      // the meter says what the server will say; nothing is sent until the rule is met
      await page.getByTestId("new-password").fill("corta");
      await expect(page.getByTestId("password-problems")).toBeVisible();
      await expect(page.getByTestId("activate-submit")).toBeDisabled();
      await page.getByTestId("new-password").fill("invitada-e2e-en-la-final");
      await expect(page.getByTestId("password-problems")).toContainText(
        t.errors.problem.password_has_context,
      );
      await page.getByTestId("new-password").fill(CHOSEN);
      await page.getByTestId("new-password-repeat").fill(CHOSEN);
      await expect(page.getByTestId("password-meter")).not.toHaveAttribute("data-level", "1");
      await assertClean(page, w);
      await page.getByTestId("activate-submit").click();

      // 4. the consents right after (the gate's own boxes), then the product
      const gate = page.getByTestId("consent-gate");
      await expect(gate).toBeVisible();
      for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
        await gate.getByTestId(`consent-${kind}`).check();
      await gate.getByTestId("consent-submit").click();
      await expect(page).toHaveURL(/\/home$/);
      await settle(page);
      await assertClean(page, w);
      // recorded as given at the activation, the moment they were asked
      const consents = await getJson<{ history: Array<{ kind: string; source: string }> }>(
        page.request,
        "/api/v1/me/consents?lang=es",
      );
      expect(consents.body.history.map((h) => h.source)).toEqual(
        consents.body.history.map(() => "activation"),
      );
      expect(consents.body.history).toHaveLength(4);

      // 5. its own password signs in again; the link never works again, whatever the session
      await page.context().clearCookies();
      await signIn(page, email, CHOSEN);
      await expect(page).toHaveURL(/\/home$/);
      const again = await (await browser.newContext({ viewport: PHONE })).newPage();
      const w2 = watch(again, { expect401: true, expectStatus: [410] });
      await again.goto(link);
      await expect(again.getByTestId("link-invalid")).toHaveText(t.auth.account.inviteInvalid);
      await expect(again.getByTestId("renew-invitation")).toBeVisible();
      await assertClean(again, w2);
      await again.context().close();

      // 6. the console: the account is active
      await ownerPage.reload();
      await expect(ownerPage.locator("tr", { hasText: email })).toContainText(
        L.en.admin.users.active,
      );
      await ownerPage.context().close();
    } finally {
      if (id) await remove(admin, id, email);
      await admin.dispose();
    }
  });

  test("a forgotten password: the same answer for any address; the link changes it once and ends every session", async ({
    page,
    browser,
  }) => {
    test.setTimeout(150_000);
    const admin = await owner();
    const { id, email } = await account(admin, "reset");
    try {
      // a session elsewhere, which the new password ends
      const elsewhere = await anonymous();
      expect(
        (await elsewhere.post("/api/v1/auth/login", { data: { email, password: FIRST } })).status(),
      ).toBe(200);

      await page.setViewportSize(PHONE);
      // 410: the reused link at the end; 401 from the anonymous /auth/me
      const w = watch(page, { expect401: true, expectStatus: [410] });
      await page.goto("/login");
      await page.getByTestId("forgot-link").click();
      await expect(page).toHaveURL(/\/forgot-password$/);
      await sixteen(page, ["forgot-email"]);
      const since = Date.now();
      await page.getByTestId("forgot-email").fill(email);
      await page.getByTestId("forgot-submit").click();
      await expect(page.getByTestId("forgot-sent")).toHaveText(t.auth.account.forgotSent);
      await assertClean(page, w);
      // an address without an account: word for word the same answer
      await page.goto("/forgot-password");
      await page.getByTestId("forgot-email").fill(`nobody.${Date.now()}@predigol.local`);
      await page.getByTestId("forgot-submit").click();
      await expect(page.getByTestId("forgot-sent")).toHaveText(t.auth.account.forgotSent);

      const link = linkOf(await mailFor(email, "password_reset", since), "/reset-password");
      await page.goto(link);
      await expect(page.getByTestId("reset-form")).toBeVisible();
      expect(await page.evaluate(() => window.location.hash)).toBe("");
      await expect(page.getByTestId("account-email")).toHaveValue(email);
      await expect(page.getByTestId("reset-second-factor")).toHaveCount(0);
      await sixteen(page, ["new-password", "new-password-repeat"]);
      await page.getByTestId("new-password").fill(SECOND);
      await page.getByTestId("new-password-repeat").fill(SECOND);
      await page.getByTestId("reset-submit").click();
      await expect(page.getByTestId("reset-done")).toHaveText(t.auth.account.resetDone);
      await assertClean(page, w);

      // every session ended; the old password no longer works, the new one does
      expect((await elsewhere.get("/api/v1/auth/me")).status()).toBe(401);
      await elsewhere.dispose();
      const api = await anonymous();
      expect(
        (await api.post("/api/v1/auth/login", { data: { email, password: FIRST } })).status(),
      ).toBe(401);
      expect(
        (await api.post("/api/v1/auth/login", { data: { email, password: SECOND } })).status(),
      ).toBe(200);
      await api.dispose();

      // the link, a second time: refused, with the way to ask for a new one
      const again = await (await browser.newContext({ viewport: PHONE })).newPage();
      await again.goto(link);
      await expect(again.getByTestId("link-invalid")).toHaveText(t.auth.account.resetInvalid);
      await expect(again.getByTestId("reset-ask-again")).toHaveAttribute(
        "href",
        "/forgot-password",
      );
      await again.context().close();
    } finally {
      await remove(admin, id, email);
      await admin.dispose();
    }
  });

  test("a locked account asks for its unlock link from the sign-in page, and the link lifts the wait", async ({
    page,
    browser,
  }) => {
    test.setTimeout(150_000);
    const admin = await owner();
    const { id, email } = await account(admin, "unlock");
    try {
      // five wrong passwords lock the account for 15 minutes (plan UX, A1, R12)
      const api = await anonymous();
      for (let attempt = 1; attempt <= 5; attempt++) {
        await api.post("/api/v1/auth/login", {
          data: { email, password: `wrong-${attempt}-pass` },
        });
      }
      const locked = await api.post("/api/v1/auth/login", { data: { email, password: FIRST } });
      expect(locked.status(), "even the right password waits").toBe(429);

      // the sign-in page: the wait, and the e-mail that lifts it (the 429s are the point here)
      await page.setViewportSize(PHONE);
      await page.goto("/login");
      await page.locator('input[name="email"]').fill(email);
      await page.locator('input[name="password"]').fill(FIRST);
      await page.getByTestId("login-submit").click();
      await expect(page.getByTestId("login-error")).toBeVisible();
      const since = Date.now();
      await page.getByTestId("ask-unlock").click();
      await expect(page.getByTestId("unlock-sent")).toHaveText(t.auth.account.unlockSent);

      const link = linkOf(await mailFor(email, "account_unlock", since), "/unlock");
      const w = watch(page, { expect401: true, expectStatus: [410] });
      await page.goto(link);
      // nothing happens on opening: only the reader's tap unlocks (a mail scanner that follows links does nothing)
      await expect(page.getByTestId("unlock-submit")).toBeVisible();
      expect(
        (await api.post("/api/v1/auth/login", { data: { email, password: FIRST } })).status(),
      ).toBe(429);
      await page.getByTestId("unlock-submit").click();
      await expect(page.getByTestId("unlock-done")).toHaveText(t.auth.account.unlockDone);
      await assertClean(page, w);
      expect(
        (await api.post("/api/v1/auth/login", { data: { email, password: FIRST } })).status(),
      ).toBe(200);
      await api.dispose();

      const again = await (await browser.newContext({ viewport: PHONE })).newPage();
      await again.goto(link);
      await expect(again.getByTestId("link-invalid")).toHaveText(t.auth.account.unlockInvalid);
      await again.context().close();
    } finally {
      await remove(admin, id, email);
      await admin.dispose();
    }
  });

  test("ending another session asks for the password first", async ({ page }) => {
    test.setTimeout(120_000);
    const admin = await owner();
    const { id, email } = await account(admin, "sessions");
    try {
      const elsewhere = await anonymous();
      expect(
        (await elsewhere.post("/api/v1/auth/login", { data: { email, password: FIRST } })).status(),
      ).toBe(200);
      // 403: the wrong password, on purpose; and the consent gate's answers until the boxes are ticked
      const w = watch(page, { expect401: true, expectStatus: [403] });
      await signIn(page, email, FIRST);
      const gate = page.getByTestId("consent-gate");
      await expect(gate).toBeVisible();
      for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
        await gate.getByTestId(`consent-${kind}`).check();
      await gate.getByTestId("consent-submit").click();
      await expect(gate).toHaveCount(0);
      await page.goto("/profile");
      const panel = page.getByTestId("sessions-panel");
      await expect(panel.locator("li")).toHaveCount(2);
      await panel.getByTestId("sessions-end-others").click();
      const dialog = page.getByTestId("identity-dialog");
      await expect(dialog).toBeVisible();
      await dialog.getByTestId("identity-password").fill("not-my-password-26");
      await dialog.getByTestId("identity-confirm").click();
      await expect(dialog.getByTestId("identity-error")).toHaveText(t.errors.code.wrong_password);
      expect((await elsewhere.get("/api/v1/auth/me")).status(), "nothing ended").toBe(200);
      await dialog.getByTestId("identity-password").fill(FIRST);
      await dialog.getByTestId("identity-confirm").click();
      await expect(dialog).toHaveCount(0);
      await expect(panel.locator("li")).toHaveCount(1);
      expect((await elsewhere.get("/api/v1/auth/me")).status()).toBe(401);
      await elsewhere.dispose();
      await assertClean(page, w);
    } finally {
      await remove(admin, id, email);
      await admin.dispose();
    }
  });

  test("the owner withdraws an invitation: the account is anonymised and its link no longer works", async ({
    page,
    browser,
  }) => {
    test.setTimeout(150_000);
    const admin = await owner();
    const email = `e2e.withdraw.${Date.now()}@predigol.local`;
    const since = Date.now();
    const invited = await sendJson<{ data: { id: number } }>(
      admin,
      "POST",
      "/api/v1/admin/users/invite",
      {
        email,
        language: "es",
        timezone: "America/Bogota",
      },
    );
    expect(invited.status).toBe(201);
    const id = invited.body.data.id;
    try {
      const link = linkOf(await mailFor(email, "invitation", since), "/activate");
      const ownerPage = await (
        await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
      ).newPage();
      const w = watch(ownerPage);
      await ownerPage.goto("/admin/users");
      const row = ownerPage.getByTestId(`user-row-${id}`);
      await row.getByTestId(`anonymise-${id}`).click();
      const dialog = ownerPage.getByTestId(`anonymise-dialog-${id}`);
      await expect(dialog).toContainText(L.en.admin.users.anonymiseIrreversible);
      const ok = dialog.getByTestId(`anonymise-ok-${id}`);
      await expect(ok).toBeDisabled();
      await dialog.getByTestId(`anonymise-confirm-${id}`).fill(`x${email}`);
      await expect(ok).toBeDisabled();
      await dialog.getByTestId(`anonymise-confirm-${id}`).fill(email.toUpperCase());
      await ok.click();
      await expect(ownerPage.getByTestId("users-notice")).toContainText("0 picks");
      await expect(row).toHaveCount(0); // the deleted hide by default
      await ownerPage.getByTestId("show-deleted").click();
      await expect(row).toContainText(L.en.admin.users.deleted);
      await expect(row).not.toContainText(email);
      await assertClean(ownerPage, w);
      await ownerPage.context().close();

      const w2 = watch(page, { expect401: true, expectStatus: [410] });
      await page.goto(link);
      await expect(page.getByTestId("link-invalid")).toBeVisible();
      await assertClean(page, w2);
    } finally {
      await remove(admin, id, email);
      await admin.dispose();
    }
  });
});
