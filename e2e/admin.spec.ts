/**
 * The Admin Console (SUPER_ADMIN, English): every page opens cleanly, accounts can be
 * managed, the audit trail records it, "Preview as USER" shows exactly the product, and
 * the shadow preview is labelled.
 */
import { expect, test, type Page } from "@playwright/test";
import { credentials } from "./accounts";
import { L, assertClean, getJson, note, settle, watch, type Watch } from "./support";

const t = L.en;
const PAGES: Array<[string, keyof typeof t.admin.pages]> = [
  ["overview", "overview"],
  ["picks", "picks"],
  ["performance", "performance"],
  ["odds", "odds"],
  ["models", "models"],
  ["backtesting", "backtesting"],
  ["analytics", "analytics"],
  ["ai-analyst", "aiAnalyst"],
  ["competitions", "competitions"],
  ["teams", "teams"],
  ["players", "players"],
  ["rankings", "rankings"],
  ["data-quality", "dataQuality"],
  ["system", "system"],
  ["migration", "migration"],
  ["users", "users"],
  ["audit", "audit"],
  ["settings", "settings"],
];

async function go(page: Page, w: Watch, path: string): Promise<void> {
  await page.goto(path);
  await settle(page);
  await assertClean(page, w);
}

test("every Admin Console page opens from the sidebar, translated", async ({ page }) => {
  test.setTimeout(180_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/overview");
  for (const [slug, key] of PAGES) {
    await page.getByTestId(`admin-nav-${slug}`).click();
    await expect(page).toHaveURL(new RegExp(`/admin/${slug}$`));
    await expect(page.getByRole("heading", { level: 1 }).first()).toHaveText(
      t.admin.pages[key].title,
    );
    await settle(page);
    await assertClean(page, w);
  }
});

test("accounts: list, deactivate and reactivate, change a role - all audited", async ({ page }) => {
  const w = watch(page);
  const target = credentials("target").email;
  await go(page, w, "/admin/users");
  const row = page.locator("tr", { hasText: target });
  await expect(row).toBeVisible();
  const id = (await row.getAttribute("data-testid"))?.replace("user-row-", "") ?? "";
  // deactivate (two-step confirm), then reactivate
  await row.getByTestId(`status-${id}`).click();
  await row.getByTestId(`confirm-status-${id}`).click();
  await expect(row).toContainText(t.admin.users.disabled);
  await row.getByTestId(`status-${id}`).click();
  await row.getByTestId(`confirm-status-${id}`).click();
  await expect(row).toContainText(t.admin.users.active);
  // USER -> SUPER_ADMIN -> USER
  await row.getByTestId(`role-${id}`).click();
  await row.getByTestId(`confirm-role-${id}`).click();
  const role = row.locator("td").nth(1);
  await expect(role).toHaveText("SUPER_ADMIN");
  await row.getByTestId(`role-${id}`).click();
  await row.getByTestId(`confirm-role-${id}`).click();
  await expect(role).toHaveText("USER");
  await assertClean(page, w);
  await go(page, w, "/admin/audit");
  await expect(page.getByTestId("audit-table")).toContainText(
    t.admin.audit.actions["user.status_changed"],
  );
  await expect(page.getByTestId("audit-table")).toContainText(
    t.admin.audit.actions["user.role_changed"],
  );
});

test("Preview as USER shows the product only, until it is switched off", async ({ page }) => {
  const w = watch(page);
  await go(page, w, "/admin/overview");
  await page.getByTestId("preview-as-user").click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByTestId("preview-banner")).toBeVisible();
  await expect(page.getByTestId("shadow-toggle")).toHaveCount(0);
  await page.goto("/admin/overview");
  await expect(page.getByTestId("forbidden")).toBeVisible();
  await page.getByTestId("exit-preview").click();
  await expect(page).toHaveURL(/\/admin\/overview$/);
  await expect(page.getByTestId("preview-banner")).toHaveCount(0);
  await settle(page);
  await assertClean(page, w);
});

test("the shadow preview is the owner's and is labelled on every block it changes", async ({
  page,
}) => {
  const w = watch(page);
  const shadow = await getJson<{ data: { top_picks: { status: string } } }>(
    page.request,
    "/api/v1/home?preview=shadow",
  );
  await go(page, w, "/home");
  const toggle = page.getByTestId("shadow-toggle").first();
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByTestId("shadow-strip")).toBeVisible();
  await settle(page);
  if (shadow.body.data.top_picks.status === "ok") {
    await expect(page.getByTestId("home-top-picks").getByTestId("pick-card").first()).toBeVisible();
  } else {
    note(test.info(), "no shadow pick in the window either");
  }
  await assertClean(page, w);
  await page.getByTestId("shadow-toggle").first().click();
  await expect(page.getByTestId("shadow-strip")).toHaveCount(0);
});

test("the Match Center has the Advanced / Audit tab for the owner", async ({ page }) => {
  const w = watch(page);
  const { body } = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    "/api/v1/odds?limit=1",
  );
  const id = body.data[0]?.id;
  test.skip(!id, "no fixture with prices to open");
  await go(page, w, `/matches/${id}`);
  await page.getByRole("tab", { name: t.match.tabs.advanced }).click();
  await settle(page);
  await assertClean(page, w);
});
