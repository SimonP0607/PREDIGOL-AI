/**
 * The customer's card (plan UX, B10; section 26), in the Admin Console (SUPER_ADMIN, English), on a reader the test makes and
 * deletes:
 *
 * * Customers in the sidebar; the four views with their counts; the reader is found by address; its row opens the card;
 * * the card: identity, membership, use, notices, consents, tickets, feedback, notes and the acts - a note is kept and listed,
 *   reading the consents' proof and the copy of the data are one tap away, the copy asks for the owner's password first;
 * * the act is in the audit trail, and the trail's filter lists the new kind of event; its pages load the whole trail;
 * * on a 320 px phone the list is cards with their dates and nothing scrolls sideways; the users' cards show the creation date
 *   and open the account's sessions;
 * * the API: nothing of the card is a reader's (the integration tests prove the 403 on every route).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, request, test, type APIRequestContext } from "@playwright/test";
import { statePath } from "./accounts";
import { L, assertClean, getJson, sendJson, settle, watch } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const PASSWORD = "Corner-flag-at-noon-27"; // gitleaks:allow - a QA account's password, made and deleted here
const WCAG = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const t = L.en;

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(admin: APIRequestContext): Promise<{ id: number; email: string }> {
  const email = `e2e.customers.${Date.now()}@predigol.local`;
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

test("the list, its views, the card and a note that reaches the audit trail", async ({ page }) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    const w = watch(page);
    await page.goto("/admin/overview");
    await settle(page);
    await page.getByTestId("admin-nav-customers").click();
    await expect(page).toHaveURL(/\/admin\/customers$/);
    await expect(page.getByRole("heading", { level: 1 }).first()).toHaveText(
      t.admin.pages.customers.title,
    );
    await settle(page);

    // the views, each with its count
    for (const view of ["all", "expiring", "inactive", "tickets", "errors"]) {
      await expect(page.getByTestId(`customer-view-${view}`)).toBeVisible();
      await expect(page.getByTestId(`customer-count-${view}`)).toHaveText(/^\d+$/);
    }
    await page.getByTestId("customer-search").fill(email);
    const row = page.getByTestId(`customer-row-${id}`);
    await expect(row).toBeVisible();
    await row.getByRole("link").first().click();
    await expect(page).toHaveURL(new RegExp(`/admin/customers/${id}$`));
    await settle(page);

    // the card
    for (const section of [
      "identity",
      "membership",
      "usage",
      "notifications",
      "consents",
      "feedback",
      "tickets",
      "notes",
      "export",
    ]) {
      await expect(page.getByTestId(`customer-${section}`), section).toBeVisible();
    }
    await expect(page.getByTestId("customer-identity")).toContainText(email);
    const text = await page.locator("main").innerText();
    expect(text, "the card holds no token and no network address").not.toMatch(
      /token|\b\d{1,3}(\.\d{1,3}){3}\b/i,
    );

    // a note
    const words = `Asked for more time ${Date.now()}`;
    await page.getByTestId("customer-note-text").fill(words);
    await page.getByTestId("customer-note-save").click();
    await expect(page.getByTestId("customer-notes")).toContainText(words);

    // the proof of the consents is read on request, and the copy of the data asks for the owner's password
    await page.getByTestId("customer-consent-open").click();
    await expect(
      page.getByTestId("customer-consent-proof").or(page.getByText(t.admin.customers.noConsents)),
    ).toBeVisible();
    await page.getByTestId("customer-export-start").click();
    await expect(page.getByTestId("customer-export-confirm")).toBeDisabled();
    await expect(page.getByTestId("customer-export-password")).toBeVisible();

    // the accessibility of the card
    const axe = await new AxeBuilder({ page }).withTags(WCAG).analyze();
    expect(axe.violations.map((v) => v.id)).toEqual([]);
    await assertClean(page, w);

    // the act is in the trail, which now lists the new kind of event and pages through the whole of it
    await page.goto("/admin/audit");
    await settle(page);
    const filter = page.locator("select").first();
    await expect(
      filter.locator("option", { hasText: t.admin.audit.actions.customer_note }),
    ).toHaveCount(1);
    await filter.selectOption("customer.note");
    await settle(page);
    await expect(page.getByTestId("audit-table")).toContainText(email);
    await expect(page.getByTestId("audit-shown")).toBeVisible();
    const actions = await getJson<{ data: Array<{ action: string; count: number }> }>(
      admin,
      "/api/v1/admin/audit/actions",
    );
    expect(actions.status).toBe(200);
    expect(actions.body.data.map((a) => a.action)).toContain("customer.note");
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});

test("on a 320 px phone: the list and the card are readable, the users' cards carry their dates and sessions", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const admin = await owner();
  const { id, email } = await account(admin);
  try {
    await page.setViewportSize({ width: 320, height: 720 });
    const w = watch(page);
    await page.goto("/admin/customers");
    await settle(page);
    await page.getByTestId("customer-search").fill(email);
    await expect(page.getByTestId(`customer-card-${id}`)).toBeVisible();
    await assertClean(page, w);
    await page.getByTestId(`customer-card-${id}`).getByRole("link").first().click();
    await settle(page);
    await expect(page.getByTestId("customer-identity")).toBeVisible();
    await assertClean(page, w);

    await page.goto("/admin/users");
    await settle(page);
    const card = page.getByTestId(`user-card-${id}`);
    await expect(card).toBeVisible();
    await expect(page.getByTestId(`user-card-created-${id}`)).toBeVisible();
    await card.getByTestId(`sessions-${id}`).click();
    await expect(
      page.getByTestId(`sessions-list-${id}`).or(card.getByText(t.admin.users.noSessions)),
    ).toBeVisible();
    await assertClean(page, w);
  } finally {
    await remove(admin, id, email);
    await admin.dispose();
  }
});
