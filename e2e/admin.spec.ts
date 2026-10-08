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
  ["ai-layer", "aiLayer"],
  ["ai-analyst", "aiAnalyst"],
  ["evolution", "evolution"],
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

test("Data truth: audit V2 ledger, the audit matrix, freshness, tables, model gate, validation, odds coverage, findings, repairs and audits", async ({
  page,
}, info) => {
  test.setTimeout(180_000);
  const w = watch(page);
  await go(page, w, "/admin/overview");
  await page.getByTestId("admin-nav-data-truth").click();
  await expect(page).toHaveURL(/\/admin\/data-truth$/);
  await expect(page.getByRole("heading", { level: 1 }).first()).toHaveText(t.truth.title);
  await settle(page);
  const tabs = [
    "audit_v2",
    "matrix",
    "freshness",
    "standings",
    "gate",
    "validation",
    "odds",
    "findings",
    "repairs",
    "runs",
  ] as const;
  for (const tab of tabs) {
    await page.getByRole("tab", { name: t.truth.tabs[tab] }).click();
    await settle(page);
    await assertClean(page, w);
    await page.screenshot({ path: info.outputPath(`data-truth-${tab}.png`), fullPage: true });
  }
  const { body } = await getJson<{ data: { run: { id: number } } | null }>(
    page.request,
    "/api/v1/admin/truth/latest",
  );
  if (!body.data) note(info, "no truth audit has run on this database yet");
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
    t.admin.audit.actions.user_status_changed,
  );
  await expect(page.getByTestId("audit-table")).toContainText(
    t.admin.audit.actions.user_role_changed,
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

test("evaluation mode is the owner's: the recorded evaluation picks and parlays, labelled, kept after kick-off", async ({
  page,
}) => {
  const w = watch(page);
  const evaluation = await getJson<{
    data: {
      evaluation_mode: boolean;
      set: { items: Array<{ match: { kickoff_at: string } }> } | null;
      daily_parlay: { legs: unknown[] } | null;
    };
  }>(page.request, "/api/v1/daily?preview=shadow");
  expect(evaluation.status).toBe(200);
  expect(evaluation.body.data.evaluation_mode).toBe(true);
  await go(page, w, "/picks");
  const toggle = page.getByTestId("shadow-toggle").first();
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByTestId("shadow-strip")).toBeVisible();
  await settle(page);
  const items = evaluation.body.data.set?.items ?? [];
  const daily = page.getByTestId("daily-set");
  await expect(daily.getByTestId("daily-item")).toHaveCount(items.length);
  if (items.length > 0) {
    await expect(daily.getByTestId("evaluation-note")).toBeVisible();
    const started = items.filter((i) => Date.parse(i.match.kickoff_at) <= Date.now()).length;
    note(
      test.info(),
      `${items.length} evaluation picks today, ${started} already kicked off and still shown`,
    );
  } else {
    note(test.info(), "no evaluation pick recorded today");
  }
  await assertClean(page, w);

  await go(page, w, "/parlays");
  const legs = evaluation.body.data.daily_parlay?.legs.length ?? 0;
  const card = page.getByTestId("parlay-record-daily");
  if (legs > 0) {
    await expect(card.getByTestId("parlay-leg")).toHaveCount(legs);
    await expect(card.getByTestId("evaluation-badge")).toBeVisible();
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

test("AI research: what is configured and spent, the daily report, flags only, every run; the evolution loop", async ({
  page,
}, info) => {
  test.setTimeout(120_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/ai-analyst");
  await expect(page.getByTestId("ai-status")).toBeVisible();
  await expect(page.getByText(t.ai.report.title, { exact: true })).toBeVisible();
  const status = await getJson<{ data: { llm_configured: boolean; missing: string[] } }>(
    page.request,
    "/api/v1/admin/ai/status",
  );
  expect(status.status).toBe(200);
  const ai = status.body.data;
  note(info, `AI: llm ${ai.llm_configured}, missing ${ai.missing.join(", ") || "none"}`);
  if (ai.missing.length) {
    await expect(page.getByText(ai.missing[0]!, { exact: false }).first()).toBeVisible();
  }
  for (const tab of ["flags", "ask", "usage", "report"] as const) {
    await page.getByRole("tab", { name: t.ai.tabs[tab], exact: true }).click();
    await settle(page);
    await assertClean(page, w);
  }
  await page.getByRole("tab", { name: t.ai.tabs.usage, exact: true }).click();
  await expect(page.getByText(t.ai.schedule.daily_report)).toBeVisible();

  await go(page, w, "/admin/evolution");
  await expect(page.getByText(t.ai.evolution.loop.s5)).toBeVisible();
  const evo = await getJson<{ data: { hypotheses: Array<{ status: string }>; memory: unknown[] } }>(
    page.request,
    "/api/v1/admin/evolution",
  );
  expect(evo.status).toBe(200);
  note(
    info,
    `evolution: ${evo.body.data.hypotheses.length} hypotheses, ${evo.body.data.memory.length} findings`,
  );
  if (evo.body.data.hypotheses.length)
    await expect(page.getByTestId("hypothesis").first()).toBeVisible();
  if (evo.body.data.memory.length) await expect(page.getByTestId("memory")).toBeVisible();
});

test("AI decision layer: mode, models and budget without a key, every view, the owner's run now; Evolución as the decision center", async ({
  page,
}, info) => {
  test.setTimeout(150_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/ai-layer");
  await expect(page.getByTestId("ai-layer-status")).toBeVisible();
  const overview = await getJson<{
    data: {
      settings: { mode: string; llm_configured: boolean; missing: string[] };
      enforcement: { enforced: boolean };
    };
  }>(page.request, "/api/v1/admin/ai/overview");
  expect(overview.status).toBe(200);
  const o = overview.body.data;
  note(
    info,
    `AI layer: mode ${o.settings.mode}, llm ${o.settings.llm_configured}, enforced ${o.enforcement.enforced}`,
  );
  expect(JSON.stringify(overview.body)).not.toMatch(/sk-[A-Za-z0-9]/);
  await expect(page.getByText(t.ai.layer.mode[o.settings.mode as "shadow"]).first()).toBeVisible();
  for (const tab of ["evidence", "costs", "shadow", "memory", "reviews"] as const) {
    await page.getByRole("tab", { name: t.ai.layer.tabs[tab], exact: true }).click();
    await settle(page);
    await assertClean(page, w);
  }
  await page.getByRole("tab", { name: t.ai.layer.tabs.costs, exact: true }).click();
  await expect(page.getByText(t.ai.layer.profile.economico, { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: t.ai.layer.tabs.reviews, exact: true }).click();
  const reviews = await getJson<{ data: Array<{ id: number }> }>(
    page.request,
    "/api/v1/admin/ai/reviews",
  );
  note(info, `reviews today: ${reviews.body.data.length}`);
  if (reviews.body.data.length) {
    await page.locator("tbody tr").first().click();
    await expect(page.getByTestId("ai-review-detail")).toBeVisible();
    await settle(page);
    await assertClean(page, w);
  }

  await go(page, w, "/admin/evolution");
  await expect(page.getByTestId("evolution-counts")).toBeVisible();
  await expect(page.getByText(t.ai.evolution.loop.s8)).toBeVisible();
  await expect(page.getByText(t.ai.evolution.noAuto)).toBeVisible();
  await expect(page.getByRole("button", { name: /activ/i })).toHaveCount(0);
  const evo = await getJson<{ data: { hypotheses: Array<{ status: string }> } }>(
    page.request,
    "/api/v1/admin/evolution",
  );
  const pending = evo.body.data.hypotheses.filter((h) => h.status === "PROPOSED");
  if (pending.length) {
    const first = page.locator('[data-group="pending"]').getByTestId("hypothesis").first();
    for (const d of ["reject", "investigate", "approve_experiment"] as const) {
      await expect(first.locator(`[data-decision="${d}"]`)).toHaveText(t.ai.evolution.decide[d]);
    }
  } else {
    note(info, "no proposed hypothesis to show the owner's three answers on");
  }
});
