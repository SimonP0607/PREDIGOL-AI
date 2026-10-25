/**
 * The messages to readers (plan UX, A5), in the browser, on an account the owner creates for the test and switches
 * off at the end. QA sends nothing (FBI_EMAIL_SEND off): the queue fills and the link comes out of it.
 *
 * * The profile's Notifications block: the optional categories are switches a finger can hit and the choice holds;
 *   the account, its security, the reader's data and the legal texts always arrive.
 * * A privacy request queues its receipt - without the reader's words - which the owner sees in the console's queue
 *   with its preview; the button's link, taken from the queue, opens the reader's profile at «Privacidad y datos».
 */
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const t = L.es;
const PASSWORD = "E2e-messages-pass-2026"; // gitleaks:allow - the password of a QA account the test creates and switches off
const SAME_SITE = { "x-requested-with": "predigol" };
const WORDS = "Quiero saber qué datos guardan de mí (prueba e2e).";

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** The QA API runs the consent gate over the draft texts: the new reader accepts the four boxes first. */
async function acceptAll(page: Page): Promise<void> {
  const state = await getJson<{ purposes: Array<{ kind: string; version: string }> }>(
    page.request,
    "/api/v1/me/consents?lang=es",
  );
  const r = await page.request.post("/api/v1/me/consents", {
    headers: SAME_SITE,
    data: {
      decisions: state.body.purposes.map((p) => ({
        kind: p.kind,
        granted: true,
        version: p.version,
      })),
      locale: "es",
      source: "gate",
    },
  });
  expect(r.status()).toBe(200);
}

test("the reader chooses the optional e-mails; a privacy request's receipt waits in the queue and its link opens the profile", async ({
  page,
  browser,
}) => {
  test.setTimeout(150_000);
  const admin = await owner();
  const email = `e2e.messages.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number } }>(admin, "POST", "/api/v1/admin/users", {
    email,
    password: PASSWORD,
    role: "USER",
    language: "es",
    timezone: "America/Bogota",
    must_change_password: false,
  });
  expect(created.status).toBe(201);
  const id = created.body.data.id;
  try {
    const w = watch(page, { expectStatus: [403] });
    await signIn(page, email);
    await acceptAll(page);

    // 1. the Notifications block: two switches, four that always arrive, and a choice that holds
    await page.goto("/profile");
    const block = page.getByTestId("notifications");
    await expect(block).toBeVisible();
    await expect(block.getByRole("switch")).toHaveCount(2);
    for (const c of ["account", "security", "privacy", "legal"])
      await expect(block.getByTestId(`notify-${c}`)).toContainText(t.profile.notifications.always);
    const membership = block.getByTestId("notify-membership").getByRole("switch");
    await expect(membership).toHaveAttribute("aria-checked", "true");
    expect((await membership.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
    await membership.click();
    await expect(membership).toHaveAttribute("aria-checked", "false");
    await page.reload();
    await expect(
      page.getByTestId("notify-membership").getByRole("switch"),
      "the choice is the account's, not the page's",
    ).toHaveAttribute("aria-checked", "false");
    const prefs = await getJson<{ email: Array<{ category: string; on: boolean }> }>(
      page.request,
      "/api/v1/me/preferences",
    );
    expect(prefs.body.email.find((e) => e.category === "membership")?.on).toBe(false);

    // 2. a privacy query from the profile queues its receipt
    const requests = page.getByTestId("privacy-requests");
    await requests.getByTestId("privacy-kind").selectOption("privacy_query");
    await requests.getByTestId("privacy-message").fill(WORDS);
    await requests.getByTestId("privacy-send").click();
    await expect(requests.getByTestId("privacy-result")).toBeVisible();
    await settle(page);
    await assertClean(page, w);

    // 3. the owner's queue: the receipt waits (QA sends nothing), and its preview carries the link, not the words
    const ownerPage = await (
      await browser.newContext({ storageState: statePath("admin"), locale: "en-GB" })
    ).newPage();
    const row = ownerPage.locator('[data-testid^="message-"]', { hasText: email }).first();
    await expect(async () => {
      await ownerPage.goto("/admin/messages");
      await expect(row).toBeVisible({ timeout: 15_000 });
    }).toPass({ timeout: 60_000 });
    await expect(ownerPage.getByTestId("messages-state")).toContainText(
      L.en.admin.messages.sendingOff,
    );
    await expect(row.getByTestId("message-template")).toHaveText(
      L.en.admin.messages.template.privacy_request_received,
    );
    await expect(row).toContainText(L.en.admin.messages.status.queued);
    await row.getByTestId("message-preview-toggle").click();
    const link = row.getByTestId("message-preview-link");
    await expect(link).toBeVisible();
    await expect(row, "the reader's words never reach the queue or its preview").not.toContainText(
      WORDS,
    );
    const href = (await link.getAttribute("href")) ?? "";
    expect(href).toMatch(/\/profile#privacy$/);
    await ownerPage.context().close();

    // 4. the link, followed by the reader: the profile, at «Privacidad y datos»
    const target = new URL(href);
    await page.goto(`${target.pathname}${target.hash}`);
    const section = page.locator("#privacy");
    await expect(section).toBeVisible();
    await expect(section).toBeInViewport();
    await expect(section.getByTestId("privacy-request").first()).toHaveAttribute(
      "data-kind",
      "privacy_query",
    );
  } finally {
    await sendJson(admin, "PATCH", `/api/v1/admin/users/${id}`, { status: "disabled" });
    await admin.dispose();
  }
});
