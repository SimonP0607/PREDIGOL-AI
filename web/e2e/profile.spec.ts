/**
 * The account centre (plan UX, B1; section 21 and gates G5, G7 and G14), in the browser against the API, on accounts the
 * test makes and deletes at the end:
 *
 * * on a 320 px phone: the eight blocks - Cuenta, Fútbol, Idioma y zona, Notificaciones, Privacidad, Seguridad, Membresía
 *   and Ayuda - folded, each with the line GET /me/account says, two taps from «Más»; each opens with a tap and folds
 *   again, 44 px headers, nothing sideways;
 * * by keyboard: Tab reaches each header, Enter and Space open and fold it;
 * * an address opens its block (an e-mail's /profile#privacy, #membership, the old #language);
 * * at a desk: the eight open, each with its own content; folding one shows its line;
 * * the alias changes in Cuenta and the account says its state in words; with every block open, never an internal word;
 * * a sensitive change asks for the current password: a wrong one changes nothing, the right one does.
 */
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, skipWelcome, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const PASSWORD = "Tardes-de-futbol-en-familia-26"; // gitleaks:allow - a QA account's password, made and deleted here
const RENEWED = "Noches-de-copa-con-amigos-2026"; // gitleaks:allow - its new password in the last test, deleted with it
const PHONE = { width: 320, height: 720 };
const DESK = { width: 1440, height: 900 };
const t = L.es;
const c = t.profile.centre;
const BLOCKS = [
  "account",
  "football",
  "region",
  "notifications",
  "privacy",
  "security",
  "membership",
  "help",
] as const;
/** The content each block mounts once open. */
const CONTENT: Record<(typeof BLOCKS)[number], string> = {
  account: "account-panel",
  football: "football-panel",
  region: "region-panel",
  notifications: "notifications",
  privacy: "privacy-export",
  security: "security-panel",
  membership: "membership-card",
  help: "help-panel",
};
const INTERNAL = /ROLE_|\bUSER\b|SUPER_ADMIN|SHADOW|QUALIFIED|\bshadow\b|\bqualified\b/;

interface Summary {
  account: { display_name: string };
  security: { sessions: number };
  membership: { state: string } | null;
}

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

/** A reader of the test's own, made by the owner (its trial starts with it, as the console does). */
async function account(
  admin: APIRequestContext,
  kind: string,
): Promise<{ id: number; email: string }> {
  // never «profile.…» in an address: the page shows it, and that reads as an untranslated key to the leak check
  const email = `e2e.centre.${kind}.${Date.now()}@predigol.local`;
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

async function signIn(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
  await skipWelcome(page.request);
  await page.goto("/home");
  const gate = page.getByTestId("consent-gate");
  // the consents first when QA's gate is on (drafts), else straight into the product
  await expect(gate.or(page.getByTestId("home-today"))).toBeVisible({ timeout: 30_000 });
  if (await gate.isVisible()) {
    for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
      await gate.getByTestId(`consent-${kind}`).check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
  }
}

async function fits(page: Page, where: string): Promise<void> {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over, `${where}: nothing sideways`).toBeLessThanOrEqual(1);
}

test("on a 320 px phone: the eight blocks folded with their line, two taps from «Más», each opens with a tap and folds again", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin, "phone");
  try {
    await page.setViewportSize(PHONE);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await page.getByTestId("tab-more").click();
    await page.getByTestId("more-sheet").getByTestId("more-profile").click();
    await expect(page).toHaveURL(/\/profile$/);
    await expect(page.getByTestId("account-centre")).toBeVisible();
    const summary = await getJson<Summary>(page.request, "/api/v1/me/account");
    expect(summary.status).toBe(200);
    for (const key of BLOCKS) {
      const block = page.getByTestId(`profile-block-${key}`);
      await expect(block, `${key}: folded on a phone`).toHaveAttribute("data-open", "false");
      await expect(page.getByTestId(`profile-summary-${key}`)).not.toHaveText("");
      await expect(
        page.getByTestId(CONTENT[key]),
        `${key}: nothing mounted while folded`,
      ).toHaveCount(0);
      const head = page.getByTestId(`profile-toggle-${key}`);
      expect(
        (await head.boundingBox())?.height ?? 0,
        `${key}: a finger's reach`,
      ).toBeGreaterThanOrEqual(44);
    }
    await expect(page.getByTestId("profile-summary-account")).toContainText(
      summary.body.account.display_name,
    );
    await expect(page.getByTestId("profile-summary-account")).toContainText("En prueba hasta el");
    await expect(page.getByTestId("profile-summary-security")).toContainText("1 sesión abierta");
    await expect(page.getByTestId("profile-summary-region")).toContainText("Español");
    await fits(page, "the folded centre");
    for (const key of BLOCKS) {
      const head = page.getByTestId(`profile-toggle-${key}`);
      await head.click();
      await expect(head).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByTestId(CONTENT[key]).first(), `${key}: its content`).toBeVisible();
      await settle(page);
      await fits(page, `${key} open`);
      await head.click();
      await expect(head).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByTestId(CONTENT[key])).toHaveCount(0);
    }
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("by keyboard: Tab reaches each header, Enter and Space open and fold it", async ({ page }) => {
  test.setTimeout(120_000);
  const admin = await owner();
  const { id, email } = await account(admin, "keys");
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await page.goto("/profile");
    const first = page.getByTestId("profile-toggle-account");
    await first.focus();
    await page.keyboard.press("Enter");
    await expect(first).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("alias-input")).toBeVisible();
    await page.keyboard.press("Space");
    await expect(first, "the focus stays on the header").toHaveAttribute("aria-expanded", "false");
    await expect(first).toBeFocused();
    // folded, the next stop is the next block's header
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("profile-toggle-football")).toBeFocused();
    await page.keyboard.press("Space");
    await expect(page.getByTestId("profile-toggle-football")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await expect(page.getByTestId("football-panel")).toBeVisible();
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("an address opens its block: an e-mail's /profile#privacy, #membership and the old #language", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const admin = await owner();
  const { id, email } = await account(admin, "anchor");
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    for (const [hash, key] of [
      ["privacy", "privacy"],
      ["membership", "membership"],
      ["language", "region"],
    ] as const) {
      // from another page, as a link in an e-mail or in Inicio arrives (a fresh profile each time)
      await page.goto("/home");
      await page.goto(`/profile#${hash}`);
      const block = page.getByTestId(`profile-block-${key}`);
      await expect(block, `#${hash} opens ${key}`).toHaveAttribute("data-open", "true");
      await expect(page.getByTestId(CONTENT[key]).first()).toBeVisible();
      await expect(block).toBeInViewport();
      for (const other of BLOCKS.filter((k) => k !== key))
        await expect(page.getByTestId(`profile-block-${other}`)).toHaveAttribute(
          "data-open",
          "false",
        );
    }
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("at a desk: the eight open with their content, the alias changes and the state is said in words, never an internal word", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const { id, email } = await account(admin, "desk");
  try {
    await page.setViewportSize(DESK);
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await page.goto("/profile");
    for (const key of BLOCKS) {
      await expect(page.getByTestId(`profile-block-${key}`)).toHaveAttribute("data-open", "true");
      await expect(page.getByTestId(CONTENT[key]).first()).toBeVisible();
    }
    await settle(page);
    const text = await page.locator("main").innerText();
    expect(text, "no internal word with every block open").not.toMatch(INTERNAL);
    await expect(page.getByTestId("account-state")).toContainText("En prueba hasta el");
    await expect(page.getByTestId("account-since")).toContainText("En PrediGol desde el");
    // the alias: never empty, saved, kept
    const input = page.getByTestId("alias-input");
    await input.fill("   ");
    await expect(page.getByTestId("alias-save")).toBeDisabled();
    await expect(page.locator("#alias-help")).toHaveText(c.alias.empty);
    await input.fill("Hincha de prueba");
    await page.getByTestId("alias-save").click();
    await expect(page.getByTestId("alias-message")).toHaveText(c.alias.saved);
    await page.reload();
    await expect(page.getByTestId("alias-input")).toHaveValue("Hincha de prueba");
    const after = await getJson<Summary>(page.request, "/api/v1/me/account");
    expect(after.body.account.display_name).toBe("Hincha de prueba");
    // folding one shows its line
    await page.getByTestId("profile-toggle-account").click();
    await expect(page.getByTestId("profile-summary-account")).toContainText("Hincha de prueba");
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("a sensitive change asks for the current password: a wrong one changes nothing, the right one does", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const admin = await owner();
  const { id, email } = await account(admin, "password");
  try {
    await page.setViewportSize(DESK);
    // 401/403: the wrong current password is refused, as it should be
    const w = watch(page, { expect401: true, expectStatus: [403, 422] });
    await signIn(page, email);
    await page.goto("/profile#security");
    const panel = page.getByTestId("security-panel");
    const current = panel.locator('input[autocomplete="current-password"]');
    const next = panel.locator('input[autocomplete="new-password"]');
    await current.fill("No-es-la-clave-actual-2026");
    await next.fill(RENEWED);
    await panel.getByRole("button", { name: t.profile.changePassword }).click();
    await expect(panel.getByRole("alert")).toBeVisible();
    const api = await request.newContext({
      baseURL: BASE,
      extraHTTPHeaders: { "x-requested-with": "predigol" },
    });
    expect(
      (await api.post("/api/v1/auth/login", { data: { email, password: PASSWORD } })).status(),
      "the old password still works after a refused change",
    ).toBe(200);
    await current.fill(PASSWORD);
    await next.fill(RENEWED);
    await panel.getByRole("button", { name: t.profile.changePassword }).click();
    await expect(panel.getByRole("status")).toHaveText(t.profile.passwordChanged);
    expect(
      (await api.post("/api/v1/auth/login", { data: { email, password: RENEWED } })).status(),
    ).toBe(200);
    await api.dispose();
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});
