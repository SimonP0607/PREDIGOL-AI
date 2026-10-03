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
  await page.locator('input[name="email"]').fill("nobody.e2e@predigol.local");
  await page.locator('input[name="password"]').fill("definitely-not-it-123");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("login-error")).toHaveText(L.es.errors.code.invalid_credentials);
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
