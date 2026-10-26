/**
 * The membership (plan UX, A8), in the browser against the API, on accounts the test makes and deletes at the end.
 *
 * * From the trial to the renewal: an account the owner creates starts its trial; the reader sees it in the profile;
 *   7 days before the end (3 in a trial) a quiet notice; the owner records a payment and extends it in under a
 *   minute (timed), with the reference in words - an account or card number is refused -, and the reader sees the
 *   membership active, the notice gone.
 * * The limit (QA_MEMBERSHIP_ENFORCE=1): an ended membership - after its 3 days of grace - opens only its profile, its
 *   saved picks to read, the help and the legal texts, on a 320 px phone too, with the notice above the page and the
 *   tab bar whole; the owner's payment brings everything back at once.
 *
 * A trial that ends in two days, or ended five days ago, is written in the QA database (E2E_DATABASE_URL, under the
 * customer schema's documented maintenance switch): the state is computed from dates, never stored.
 */
import { execFileSync } from "node:child_process";
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, skipWelcome, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const DB = (process.env["E2E_DATABASE_URL"] ?? "").replace(
  "postgresql+psycopg://",
  "postgresql://",
);
const PASSWORD = "Season-ticket-reader-26"; // gitleaks:allow - a QA account's password, made and deleted here
const SAME_SITE = { "x-requested-with": "predigol" };
const t = L.es;

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

/** An account the owner creates from the console's API: it starts its trial at once (A8). */
async function account(
  admin: APIRequestContext,
  kind: string,
): Promise<{ id: number; email: string }> {
  const email = `e2e.member.${kind}.${Date.now()}@predigol.local`;
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
  expect([200, 409]).toContain(r.status);
}

/** Moves the account's trial in the QA database: it ends ``endsInDays`` from now (negative: it ended). */
function moveTrial(userId: number, endsInDays: number): void {
  const sql =
    "BEGIN; SET LOCAL fbi.customer_maintenance = 'on'; " +
    `UPDATE customer.membership_periods SET starts_at = now() + interval '${endsInDays - 14} days', ` +
    `ends_at = now() + interval '${endsInDays} days' WHERE user_id = ${Number(userId)} AND kind = 'trial'; COMMIT;`;
  execFileSync("psql", [DB, "-v", "ON_ERROR_STOP=1", "-qtAc", sql], { stdio: "pipe" });
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
  // the account's welcome (A13) is another test's: recorded as done, the pages open as the test asks
  await skipWelcome(page.request);
}

/** The QA API runs the consent gate over the draft texts: the new reader ticks its four boxes first. */
async function acceptConsents(page: Page): Promise<void> {
  const gate = page.getByTestId("consent-gate");
  await expect(gate).toBeVisible();
  for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
    await gate.getByTestId(`consent-${kind}`).check();
  await gate.getByTestId("consent-submit").click();
  await expect(gate).toHaveCount(0);
}

test("from the trial to the renewal: the profile says it, the notice comes before the end, the owner extends it in under a minute", async ({
  page,
  browser,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin, "renew");
  try {
    // 403 while the consents are owed; 401 from the anonymous /auth/me
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await acceptConsents(page);
    await page.goto("/profile#membership");
    const card = page.getByTestId("membership-card");
    await expect(card).toHaveAttribute("data-state", "trial");
    await expect(card.getByTestId("membership-line")).toContainText("En prueba hasta el");
    await expect(card.getByTestId("membership-days-left")).toContainText("14");
    await page.goto("/home");
    await settle(page);
    await expect(
      page.getByTestId("membership-banner"),
      "a trial with days left says nothing",
    ).toHaveCount(0);
    if (DB) {
      // three days before the end of a trial: the quiet notice on every page
      moveTrial(id, 2);
      await page.reload();
      await settle(page);
      const banner = page.getByTestId("membership-banner");
      await expect(banner).toContainText(
        t.profile.membership.banner.expiringTrial.split("{")[0] ?? "",
      );
      await expect(banner).toHaveAttribute("data-state", "expiring");
    } else {
      test.info().annotations.push({
        type: "data",
        description: "no E2E_DATABASE_URL: the notice is not checked",
      });
    }
    await assertClean(page, w);

    // the owner (the console in English, the QA owner's language): «Record payment and extend», timed from opening
    // the account's membership to the confirmation
    const ownerPage = await (
      await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
    ).newPage();
    const w2 = watch(ownerPage, { expectStatus: [422] });
    await ownerPage.goto("/admin/users");
    const cell = ownerPage.getByTestId(`membership-${id}`).first();
    await expect(cell).toHaveAttribute("data-state", DB ? "expiring" : "trial");
    const started = Date.now();
    await cell.getByTestId(`membership-manage-${id}`).click();
    const dialog = ownerPage.getByTestId(`membership-dialog-${id}`);
    await expect(dialog.getByTestId("membership-pay-form")).toBeVisible();
    await dialog.getByTestId("pay-amount").fill("50000");
    await dialog.getByTestId("pay-method").selectOption("nequi");
    // an account or a card number is refused, with what to write instead
    await dialog.getByTestId("pay-reference").fill("tarjeta 4111 1111 1111 1111");
    await dialog.getByTestId("pay-submit").click();
    await expect(dialog.getByRole("alert")).toContainText(L.en.errors.code.reference_has_number);
    await dialog.getByTestId("pay-reference").fill("Nequi 25 oct");
    await dialog.getByTestId("pay-submit").click();
    await expect(dialog.getByTestId("membership-notice")).toContainText(
      L.en.profile.membership.state.active,
    );
    const seconds = (Date.now() - started) / 1000;
    expect(seconds, "a renewal recorded in under a minute").toBeLessThan(60);
    await expect(dialog.getByTestId("membership-history")).toContainText("Nequi 25 oct");
    await assertClean(ownerPage, w2);
    await ownerPage.context().close();

    // the reader: active, the notice gone, the payment in the history
    await page.goto("/profile#membership");
    await expect(card).toHaveAttribute("data-state", "active");
    await expect(card.getByTestId("membership-periods").locator("li")).toHaveCount(2);
    await expect(card.getByTestId("membership-periods")).toContainText("Nequi");
    await expect(page.getByTestId("membership-banner")).toHaveCount(0);
    const mine = await getJson<{ membership: { state: string; kind: string } }>(
      page.request,
      "/api/v1/me/membership",
    );
    expect(mine.body.membership).toMatchObject({ state: "active", kind: "paid" });
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("an ended membership opens only what a limited account reads, on a 320 px phone too, until the owner renews it", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const state = await getJson<{ enforced: boolean }>(admin, "/api/v1/me/membership");
  test.skip(!DB, "no E2E_DATABASE_URL: an ended membership cannot be written");
  test.skip(
    !state.body.enforced,
    "the QA API runs with the membership gate off (QA_MEMBERSHIP_ENFORCE=1)",
  );
  const { id, email } = await account(admin, "limited");
  try {
    moveTrial(id, -5); // the trial ended five days ago: the 3 days of grace are over
    await page.setViewportSize({ width: 320, height: 720 });
    // 403: the consent gate first, then the membership's on what the page asks before it knows
    const w = watch(page, { expect401: true, expectStatus: [403] });
    await signIn(page, email);
    await acceptConsents(page);
    await page.goto("/home");
    const limited = page.getByTestId("limited-access");
    await expect(limited).toBeVisible();
    await expect(limited).toHaveAttribute("data-state", "expired");
    await expect(limited).toContainText(t.profile.membership.limited.expiredTitle);
    const banner = page.getByTestId("membership-banner");
    await expect(banner).toContainText(t.profile.membership.banner.expired);
    await expect(page.getByTestId("tab-my-picks"), "the tab bar stays whole").toBeVisible();
    const api = await page.request.get("/api/v1/home", { headers: SAME_SITE });
    expect(api.status()).toBe(403);
    expect(((await api.json()) as { error: { code: string } }).error.code).toBe(
      "membership_expired",
    );
    // its saved picks, to read
    await limited.getByTestId("limited-my-picks").click();
    await expect(page).toHaveURL(/\/my-picks$/);
    await expect(page.getByTestId("my-picks-read-only")).toBeVisible();
    await expect(page.getByTestId("limited-access")).toHaveCount(0);
    // the profile: why, and how to renew
    await page.goto("/profile#membership");
    await expect(page.getByTestId("membership-card")).toHaveAttribute("data-state", "expired");
    await page.goto("/picks");
    await expect(page.getByTestId("limited-access")).toBeVisible();
    await assertClean(page, w);

    // the owner renews: everything is back
    const r = await sendJson<{ created: boolean }>(
      admin,
      "POST",
      `/api/v1/admin/users/${id}/membership/payments`,
      {
        amount: "50000",
        currency: "COP",
        method: "transfer",
        reference: "transferencia 26 oct",
        months: 1,
        idempotency_key: `e2e${Date.now()}`,
      },
    );
    expect(r.status).toBe(200);
    await page.goto("/home");
    await settle(page);
    await expect(page.getByTestId("limited-access")).toHaveCount(0);
    await expect(page.getByTestId("membership-banner")).toHaveCount(0);
    expect((await page.request.get("/api/v1/home", { headers: SAME_SITE })).status()).toBe(200);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});
