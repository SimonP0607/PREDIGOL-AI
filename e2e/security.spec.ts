/**
 * Two-step verification and the staged sign-in, through the browser, on an account the owner creates for the test
 * (and switches off at the end): set up the authenticator from the QR's key, keep the recovery codes, choose a
 * password, sign in again with a code, then the owner's side - the badges, a 2FA reset, a temporary password.
 */
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, watch } from "./support";
import { base32Decode, codeAt, stepNow } from "./totp";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const t = L.es;

async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByTestId("login-submit").click();
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

test("a new account: authenticator from the QR's key, recovery codes, its own password, then a code", async ({
  page,
  browser,
}) => {
  const admin = await owner();
  const email = `e2e.mfa.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number; must_change_password: boolean } }>(
    admin,
    "POST",
    "/api/v1/admin/users",
    {
      email,
      password: "E2e-initial-pass-26",
      role: "USER",
      language: "es",
      timezone: "America/Bogota",
      must_change_password: true,
      mfa_required: true,
    },
  );
  expect(created.status).toBe(201);
  const id = created.body.data.id;
  try {
    // the reused temporary password below is refused on purpose (422)
    const w = watch(page, { expect401: true, expectStatus: [422] });
    await signIn(page, email, "E2e-initial-pass-26");

    // 1. the authenticator, set up from the key under the QR (what a phone that cannot scan would type)
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.auth.steps.enrollTitle);
    await page.getByTestId("enroll-start").click();
    await expect(page.getByTestId("enroll-qr")).toBeVisible();
    const key = base32Decode(await page.getByTestId("enroll-secret").innerText());
    let step = stepNow();
    await page.getByTestId("step-code").fill(codeAt(key, step));
    await page.getByTestId("enroll-confirm").click();

    // 2. the recovery codes, shown once; continuing needs the reader to say they kept them
    await expect(page.getByTestId("recovery-codes")).toBeVisible();
    const codes = await page.locator('[data-testid="recovery-codes"] li').allInnerTexts();
    expect(codes).toHaveLength(10);
    await expect(page.getByTestId("recovery-continue")).toBeDisabled();
    await page.getByTestId("recovery-saved").check();
    await page.getByTestId("recovery-continue").click();

    // 3. its own password (the owner's temporary one is not accepted again)
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.auth.steps.passwordTitle);
    await page.getByTestId("step-new-password").fill("E2e-initial-pass-26");
    await page.getByTestId("step-repeat-password").fill("E2e-initial-pass-26");
    await page.getByTestId("step-submit").click();
    await expect(page.getByTestId("step-error")).toContainText(t.errors.problem.password_reused);
    await page.getByTestId("step-new-password").fill("E2e-own-pass-2026");
    await page.getByTestId("step-repeat-password").fill("E2e-own-pass-2026");
    await page.getByTestId("step-submit").click();
    await expect(page).toHaveURL(/\/home$/);
    await settle(page);
    await assertClean(page, w);

    // 4. the profile shows it
    await page.goto("/profile");
    await expect(page.getByTestId("two-factor-panel")).toContainText(t.profile.securityPanel.mfaOn);
    await expect(page.getByTestId("sessions-panel")).toContainText(
      t.profile.securityPanel.thisDevice,
    );
    await expect(page.getByTestId("access-panel")).toContainText(
      t.profile.securityPanel.action["login.succeeded"],
    );

    // 5. the next sign-in asks for a code; a wrong one says how many attempts are left
    await page.context().clearCookies();
    await signIn(page, email, "E2e-own-pass-2026");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(t.auth.steps.mfaTitle);
    await page.getByTestId("step-code").fill("000000");
    await page.getByTestId("step-submit").click();
    await expect(page.getByTestId("step-error")).toHaveText(
      t.auth.steps.invalidCodeLeft.replace("{left}", "4"),
    );
    step = Math.max(stepNow(), step + 1);
    await page.getByTestId("step-code").fill(codeAt(key, step));
    await page.getByTestId("step-submit").click();
    await expect(page).toHaveURL(/\/home$/);

    // 6. a recovery code works in place of a code
    await page.context().clearCookies();
    await signIn(page, email, "E2e-own-pass-2026");
    await page.getByTestId("step-toggle-recovery").click();
    await page.getByTestId("step-code").fill(codes[0] ?? "");
    await page.getByTestId("step-submit").click();
    await expect(page).toHaveURL(/\/home$/);

    // 7. the owner: the account shows 2FA; a reset sends it back to the set-up
    const ownerPage = await (
      await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
    ).newPage();
    await ownerPage.goto("/admin/users");
    const row = ownerPage.getByTestId(`user-row-${id}`);
    await expect(row.getByTestId(`security-${id}`)).toContainText("2FA");
    await row.getByTestId(`mfa-${id}`).click();
    await row.getByTestId(`confirm-mfa-${id}`).click();
    await expect(row.getByTestId(`security-${id}`)).toContainText(L.en.admin.users.mfaPending);
    // a temporary password, shown once, and the account must replace it
    await row.getByTestId(`password-${id}`).click();
    await row.getByTestId(`confirm-password-${id}`).click();
    await expect(row.getByTestId(`temporary-password-${id}`)).toBeVisible();
    await expect(row.getByTestId(`security-${id}`)).toContainText(L.en.admin.users.mustChange);
    await ownerPage.context().close();
    // the reader's session ended with the reset
    await page.goto("/profile");
    await expect(page).toHaveURL(/\/login/);
  } finally {
    await sendJson(admin, "PATCH", `/api/v1/admin/users/${id}`, { status: "disabled" });
    const audit = await getJson<{ data: Array<{ action: string }> }>(
      admin,
      `/api/v1/admin/audit?user_id=${id}&limit=200`,
    );
    expect(audit.body.data.map((e) => e.action)).toEqual(
      expect.arrayContaining([
        "mfa.enrolled",
        "mfa.verified",
        "mfa.failed",
        "mfa.reset",
        "password.reset",
      ]),
    );
    await admin.dispose();
  }
});
