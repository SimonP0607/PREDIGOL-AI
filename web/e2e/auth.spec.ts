/** Signing in and out, and where a signed-out reader is sent. */
import { expect, test } from "@playwright/test";
import { credentials } from "./accounts";
import { L, assertClean, settle, watch } from "./support";

test("the sign-in screen is in Spanish by default and switches to English", async ({ page }) => {
  const w = watch(page, { expect401: true });
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(L.es.auth.title);
  await expect(page.getByAltText("PrediGol").first()).toBeVisible();
  await page.getByTestId("lang-en").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(L.en.auth.title);
  await page.getByTestId("lang-es").click();
  await assertClean(page, w);
});

test("wrong credentials say so, in the reader's language, without signing in", async ({ page }) => {
  watch(page, { expect401: true });
  await page.goto("/login");
  // An address of its own on every run: five failures of one address lock it (plan UX, A1, R12).
  await page.locator('input[name="email"]').fill(`nobody.e2e+${Date.now()}@predigol.local`);
  await page.locator('input[name="password"]').fill("definitely-not-it-123");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("login-error")).toHaveText(L.es.errors.code.invalid_credentials);
  await expect(page).toHaveURL(/\/login/);
});

test("the failure that locks says the real wait, in minutes - an address without an account locks alike", async ({
  page,
}) => {
  // Plan UX, A1 (F01, R12): the page always said "60 s" and the failure that locked answered 401. Now the fifth
  // failure answers 429 with the real wait - 15 minutes - for any address; the same rule for an address with an
  // account is proven by the API's tests (test_auth_lockout.py), without locking a QA account here.
  watch(page, { expect401: true, expectStatus: [429] });
  await page.goto("/login");
  const email = `lock.e2e+${Date.now()}@predigol.local`;
  for (let attempt = 1; attempt <= 5; attempt++) {
    await page.locator('input[name="email"]').fill(email);
    await page.locator('input[name="password"]').fill(`not-the-password-${attempt}`);
    const answered = page.waitForResponse((r) => r.url().includes("/api/v1/auth/login"));
    await page.getByTestId("login-submit").click();
    const res = await answered;
    expect(res.status(), `attempt ${attempt}`).toBe(attempt < 5 ? 401 : 429);
  }
  const error = page.getByTestId("login-error");
  await expect(error).toHaveText(
    L.es.errors.code.too_many_attempts.replace("{wait}", "15 minutos"),
  );
  await expect(error).not.toContainText("60 s");
  await expect(page).toHaveURL(/\/login/);
});

test("a signed-out reader is sent to sign in and comes back where they were going", async ({
  page,
}) => {
  const w = watch(page, { expect401: true });
  await page.goto("/picks");
  await expect(page).toHaveURL(/\/login\?next=%2Fpicks/);
  const { email, password } = credentials("user");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/picks$/);
  await settle(page);
  await assertClean(page, w);
  // and signing out ends it
  await page.getByTestId("account-menu").click();
  await page.getByTestId("sign-out").click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/home");
  await expect(page).toHaveURL(/\/login\?next=%2Fhome/);
});

test.describe("served in the reader's language", () => {
  test.use({ locale: "en-GB" });

  test("an English browser gets lang, title and description in English; the switch names each language in itself", async ({
    page,
  }) => {
    // Plan UX, A1 (F08): the server wrote lang="es" with an English title for everyone, and the switch said ES/EN.
    watch(page, { expect401: true });
    const html = await (
      await page.request.get("/login", { headers: { "accept-language": "en-GB,en;q=0.9" } })
    ).text();
    expect(html).toMatch(/<html lang="en"/);
    expect(html).toContain("<title>Sign in · PrediGol</title>");
    expect(html).toContain(L.en.common.meta.description);
    const spanish = await (
      await page.request.get("/login", { headers: { "accept-language": "es-CO,es;q=0.9" } })
    ).text();
    expect(spanish).toMatch(/<html lang="es"/);
    expect(spanish).toContain("<title>Inicia sesión · PrediGol</title>");

    await page.goto("/login");
    await expect(page).toHaveTitle("Sign in · PrediGol");
    expect(await page.evaluate(() => document.documentElement.lang)).toBe("en");
    // the code on the screen, then the language's own name: what is seen is in what is said (WCAG 2.5.3)
    await expect(page.getByTestId("lang-es")).toHaveAccessibleName("es Español");
    await expect(page.getByTestId("lang-en")).toHaveAccessibleName("en English");
    // the reader's choice takes over the whole page: its text, lang and title
    await page.getByTestId("lang-es").click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(L.es.auth.title);
    await expect(page).toHaveTitle("Inicia sesión · PrediGol");
    await expect.poll(() => page.evaluate(() => document.documentElement.lang)).toBe("es");
  });
});
