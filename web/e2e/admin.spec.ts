/**
 * The Admin Console (SUPER_ADMIN, English): every page opens cleanly, accounts can be
 * managed, the audit trail records it, "Preview as USER" shows exactly the product, and
 * the shadow preview is labelled.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
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
  ["operation", "operation"],
  ["learning", "learning"],
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
  // Plan F13: the five pages that talked about the AI are two (Operation and Learning), and the menu has no entry for the old ones
  for (const slug of ["intelligence", "ai-layer", "ai-analyst", "evolution", "memory"]) {
    await expect(page.getByTestId(`admin-nav-${slug}`)).toHaveCount(0);
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

// ── Plan F13 (section 16): the five pages that talked about the AI are two - Operación and Aprendizaje ──────────

const OP = t.admin.operation;
const LEARN = t.admin.learning;

/** The tab strip with this name. */
function strip(page: Page, name: string): Locator {
  return page.getByRole("tablist", { name, exact: true });
}

/** Open a tab of the strip with this name. */
async function choose(page: Page, name: string, tab: string): Promise<void> {
  await strip(page, name).getByRole("tab", { name: tab, exact: true }).click();
}

/** The tab of the strip with this name that is open. */
function openTab(page: Page, name: string): Locator {
  return strip(page, name).getByRole("tab", { selected: true });
}

function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Everything the AI decides is in shadow, and the page says so once - not once per tab. */
async function oneShadowLine(page: Page): Promise<void> {
  await expect(page.getByTestId("ai-shadow-line")).toHaveCount(1);
}

test("Operation: the day, the decisions, the match, the AI's work with its five views, the costs and the runs - one page, one shadow line, no key", async ({
  page,
}, info) => {
  test.setTimeout(180_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/operation");
  await expect(page.getByRole("heading", { level: 1 }).first()).toHaveText(
    t.admin.pages.operation.title,
  );
  await oneShadowLine(page);
  const tabs = OP.tabs.label;
  await expect(openTab(page, tabs)).toHaveText(OP.tabs.day);
  for (const tab of ["decisions", "match", "ai", "costs", "runs", "day"] as const) {
    await choose(page, tabs, OP.tabs[tab]);
    await expect(openTab(page, tabs)).toHaveText(OP.tabs[tab]);
    await settle(page);
    await assertClean(page, w);
    await oneShadowLine(page);
  }

  // the AI's work: the state of the layer (mode, models and budget without a key), then its five views
  await choose(page, tabs, OP.tabs.ai);
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
  for (const path of ["today", "research", "sources", "reviews"]) {
    const res = await getJson<{ data: unknown }>(page.request, `/api/v1/admin/ai/${path}`);
    expect(res.status, path).toBe(200);
    expect(JSON.stringify(res.body)).not.toMatch(/sk-[A-Za-z0-9]/);
  }
  const today = await getJson<{ data: { fixtures: unknown[]; without_market: number } }>(
    page.request,
    "/api/v1/admin/ai/today",
  );
  note(
    info,
    `AI today: ${today.body.data.fixtures.length} with a market, ${today.body.data.without_market} without`,
  );
  const views = OP.aiViews.label;
  await expect(openTab(page, views)).toHaveText(OP.aiViews.today);
  for (const view of ["research", "reviews", "evidence", "sources", "today"] as const) {
    await choose(page, views, OP.aiViews[view]);
    await expect(openTab(page, views)).toHaveText(OP.aiViews[view]);
    await settle(page);
    await assertClean(page, w);
  }
  await choose(page, views, OP.aiViews.reviews);
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

  // what it costs: one budget, one stack, the simulation per profile - not one copy per page that talked about the AI
  await choose(page, tabs, OP.tabs.costs);
  await expect(page.getByTestId("ai-costs")).toBeVisible();
  await expect(page.getByTestId("ai-budget-card")).toHaveCount(1);
  await expect(page.getByText(t.ai.layer.profile.economico, { exact: true })).toBeVisible();
  await settle(page);
  await assertClean(page, w);

  // what ran
  await choose(page, tabs, OP.tabs.runs);
  await expect(page.getByTestId("intel-runs")).toBeVisible();
  await assertClean(page, w);
});

test("Learning: the close of the day, what was learned, the post-mortems, the memory, the experiments, the calibration, the markets and the AI against the model - one page, nothing activates by itself", async ({
  page,
}, info) => {
  test.setTimeout(180_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/learning");
  await expect(page.getByRole("heading", { level: 1 }).first()).toHaveText(
    t.admin.pages.learning.title,
  );
  const tabs = LEARN.tabs.label;
  await expect(openTab(page, tabs)).toHaveText(LEARN.tabs.close);
  for (const tab of [
    "learned",
    "postmortems",
    "memory",
    "experiments",
    "calibration",
    "markets",
    "families",
    "shadow",
    "close",
  ] as const) {
    await choose(page, tabs, LEARN.tabs[tab]);
    await expect(openTab(page, tabs)).toHaveText(LEARN.tabs[tab]);
    await settle(page);
    await assertClean(page, w);
    await oneShadowLine(page);
    // the page says, on every tab, that nothing changes a model or a rule on its own
    await expect(page.getByText(t.ai.evolution.noAuto)).toBeVisible();
    await expect(page.getByRole("button", { name: /activ/i })).toHaveCount(0);
  }
  for (const path of ["postmortems", "learning", "comparison"]) {
    const res = await getJson<{ data: unknown }>(page.request, `/api/v1/admin/ai/${path}`);
    expect(res.status, path).toBe(200);
    expect(JSON.stringify(res.body)).not.toMatch(/sk-[A-Za-z0-9]/);
  }

  // what was learned: the day's tiles, the notes with their evidence, the proposals
  await choose(page, tabs, LEARN.tabs.learned);
  await expect(page.getByTestId("evolution-day")).toBeVisible();
  await expect(page.getByTestId("evolution-counts")).toBeVisible();
  const evo = await getJson<{ data: { hypotheses: Array<{ status: string }>; memory: unknown[] } }>(
    page.request,
    "/api/v1/admin/evolution",
  );
  expect(evo.status).toBe(200);
  note(
    info,
    `evolution: ${evo.body.data.hypotheses.length} hypotheses, ${evo.body.data.memory.length} findings`,
  );

  // the post-mortems have a tab of their own: the panel itself, not its list - the list exists only once one has been written
  await choose(page, tabs, LEARN.tabs.postmortems);
  await expect(page.getByTestId("memory-postmortems")).toBeVisible();
});

test("Memory, a tab of Learning: the entities with their version, confidence and evidence, and the other three kinds of memory as its views", async ({
  page,
}, info) => {
  test.setTimeout(150_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/learning#tab=memory");
  await expect(openTab(page, LEARN.tabs.label)).toHaveText(LEARN.tabs.memory);
  await expect(page.getByTestId("memory-entities")).toBeVisible();
  const memory = await getJson<{
    data: {
      items: Array<{ version: string; confidence: number | null; evidence_ref: unknown }>;
      total: number;
    };
  }>(page.request, "/api/v1/admin/intelligence/memory?entity_type=team&limit=200");
  expect(memory.status).toBe(200);
  expect(JSON.stringify(memory.body)).not.toMatch(/sk-[A-Za-z0-9]/);
  const items = memory.body.data.items;
  const measured = items.filter((m) => m.confidence !== null);
  note(
    info,
    `memory: ${items.length} of ${memory.body.data.total} team series, ${measured.length} with confidence`,
  );
  // every series names the version that wrote it; one written by memory-v4 says how far to trust it and what it rests on
  for (const m of items) expect(m.version).toBeTruthy();
  for (const m of measured) {
    expect(m.confidence).toBeGreaterThanOrEqual(0);
    expect(m.confidence).toBeLessThan(1);
  }
  if (items.some((m) => m.evidence_ref))
    await expect(page.getByTestId("memory-evidence").first()).toBeVisible();
  // an aspect narrows the list on the server, so a crowded aspect cannot hide the others
  const corners = await getJson<{ data: { items: Array<{ aspect: string }> } }>(
    page.request,
    "/api/v1/admin/intelligence/memory?aspect=corners&limit=50",
  );
  expect(corners.status).toBe(200);
  for (const m of corners.body.data.items) expect(m.aspect).toBe("corners");

  const views = t.memory.tabs.label;
  await expect(openTab(page, views)).toHaveText(LEARN.memoryViews.entities);
  for (const view of ["matches", "notes", "findings", "entities"] as const) {
    await choose(page, views, LEARN.memoryViews[view]);
    await expect(openTab(page, views)).toHaveText(LEARN.memoryViews[view]);
    await settle(page);
    await assertClean(page, w);
  }
  await choose(page, views, LEARN.memoryViews.notes);
  await expect(page.getByTestId("memory-notes")).toBeVisible();
  await choose(page, views, LEARN.memoryViews.findings);
  await expect(page.getByTestId("memory-research")).toBeVisible();
});

test("Families, a tab of Learning: the cycle of the families in shadow, a card per family, the last word on each market and what they remember - read only, nothing to switch on", async ({
  page,
}, info) => {
  test.setTimeout(150_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/learning#tab=families");
  await expect(openTab(page, LEARN.tabs.label)).toHaveText(LEARN.tabs.families);
  await expect(page.getByTestId("families-tab")).toBeVisible();
  const res = await getJson<{
    data: {
      mode: string | null;
      steps: unknown[];
      families: Array<{ family: string }>;
      items: unknown[];
      total: number;
      memory: unknown[];
    };
  }>(page.request, "/api/v1/admin/intelligence/families");
  expect(res.status).toBe(200);
  expect(JSON.stringify(res.body)).not.toMatch(/sk-[A-Za-z0-9]/);
  const d = res.body.data;
  note(
    info,
    `families: mode ${d.mode ?? "none"}, ${d.steps.length} steps run, ${d.total} last words, ${d.memory.length} remembered`,
  );

  // the cycle: its four steps and the mode of the worker - and nothing to switch on (the switch is the owner's, in the server's environment)
  await expect(page.getByTestId("families-cycle")).toBeVisible();
  await expect(page.getByTestId("families-mode")).toBeVisible();
  for (const step of ["families", "family_outcomes", "family_postmortems", "family_memory"])
    await expect(page.getByTestId(`families-step-${step}`)).toBeVisible();
  await expect(page.getByRole("button", { name: /activ|encend/i })).toHaveCount(0);

  // one card per family, in the server's order
  await expect(page.getByTestId("families-cards")).toBeVisible();
  expect(d.families.map((f) => f.family)).toEqual(["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"]);
  for (const f of d.families)
    await expect(page.getByTestId(`families-card-${f.family}`)).toBeVisible();

  // the last word of each model on each market (or why there is none), and what the families remember (or that nothing yet)
  await expect(page.getByTestId("families-items")).toBeVisible();
  if (d.total === 0) await expect(page.getByTestId("families-items-empty")).toBeVisible();
  await expect(page.getByTestId("families-memory")).toBeVisible();
  if (d.memory.length === 0) await expect(page.getByTestId("families-memory-empty")).toBeVisible();
  await settle(page);
  await assertClean(page, w);
});

test("Experiments, a tab of Learning: every hypothesis by stage with the owner's three answers, the loop, and the model code against its promotions", async ({
  page,
}, info) => {
  test.setTimeout(150_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/learning#tab=experiments");
  await expect(openTab(page, LEARN.tabs.label)).toHaveText(LEARN.tabs.experiments);
  await expect(page.getByTestId("evolution-experiments")).toBeVisible();
  await expect(page.getByText(t.ai.evolution.loop.s5)).toBeVisible();
  await expect(page.getByText(t.ai.evolution.loop.s8)).toBeVisible();
  await expect(page.getByText(t.ai.evolution.noAuto)).toBeVisible();
  await expect(page.getByRole("button", { name: /activ/i })).toHaveCount(0);
  const evo = await getJson<{ data: { hypotheses: Array<{ status: string }> } }>(
    page.request,
    "/api/v1/admin/evolution",
  );
  expect(evo.status).toBe(200);
  if (evo.body.data.hypotheses.length)
    await expect(page.getByTestId("hypothesis").first()).toBeVisible();
  const pending = evo.body.data.hypotheses.filter((h) => h.status === "PROPOSED");
  if (pending.length) {
    const first = page.locator('[data-group="pending"]').getByTestId("hypothesis").first();
    for (const d of ["reject", "investigate", "approve_experiment"] as const) {
      await expect(first.locator(`[data-decision="${d}"]`)).toHaveText(t.ai.evolution.decide[d]);
    }
  } else {
    note(info, "no proposed hypothesis to show the owner's three answers on");
  }

  // Plan F12: the model code against its promotions - reading only, and the code this server runs is the ledger's.
  const code = await getJson<{
    data: {
      running_code: string;
      in_force_matches_running: boolean;
      counts: { counted: number; traced: number };
    };
  }>(page.request, "/api/v1/admin/evolution/code-promotions");
  expect(code.status).toBe(200);
  expect(code.body.data.in_force_matches_running).toBe(true);
  await expect(page.getByTestId("code-promotions")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("code-tiles")).toContainText(code.body.data.running_code);
  await settle(page);
  await assertClean(page, w);
  note(
    info,
    `model code: ${code.body.data.running_code} runs; ${code.body.data.counts.traced} of ${code.body.data.counts.counted} changes with a promotion`,
  );
});

/**
 * The addresses people kept. Each old page, opened with the tab it had in the address, lands on the tab of Operation or Learning that now holds it;
 * a page with no tab (or with one it never had) lands on the tab it used to open on.
 */
const OLD_ADDRESSES: Array<{
  from: string;
  to: string;
  tabs: string;
  tab: string;
  views?: string;
  view?: string;
}> = [
  { from: "/admin/intelligence", to: "/admin/operation", tabs: OP.tabs.label, tab: OP.tabs.day },
  {
    from: "/admin/intelligence#tab=decisions",
    to: "/admin/operation#tab=decisions",
    tabs: OP.tabs.label,
    tab: OP.tabs.decisions,
  },
  {
    from: "/admin/intelligence#tab=costs",
    to: "/admin/operation#tab=costs",
    tabs: OP.tabs.label,
    tab: OP.tabs.costs,
  },
  {
    from: "/admin/intelligence#tab=calibration",
    to: "/admin/learning#tab=calibration",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.calibration,
  },
  {
    from: "/admin/intelligence#tab=markets",
    to: "/admin/learning#tab=markets",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.markets,
  },
  {
    from: "/admin/ai-layer",
    to: "/admin/operation#tab=ai&view=reviews",
    tabs: OP.tabs.label,
    tab: OP.tabs.ai,
    views: OP.aiViews.label,
    view: OP.aiViews.reviews,
  },
  {
    from: "/admin/ai-layer#tab=evidence",
    to: "/admin/operation#tab=ai&view=evidence",
    tabs: OP.tabs.label,
    tab: OP.tabs.ai,
    views: OP.aiViews.label,
    view: OP.aiViews.evidence,
  },
  {
    from: "/admin/ai-layer#tab=costs",
    to: "/admin/operation#tab=costs",
    tabs: OP.tabs.label,
    tab: OP.tabs.costs,
  },
  {
    from: "/admin/ai-layer#tab=shadow",
    to: "/admin/learning#tab=shadow",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.shadow,
  },
  {
    from: "/admin/ai-analyst",
    to: "/admin/operation#tab=ai",
    tabs: OP.tabs.label,
    tab: OP.tabs.ai,
    views: OP.aiViews.label,
    view: OP.aiViews.today,
  },
  {
    from: "/admin/ai-analyst#tab=sources",
    to: "/admin/operation#tab=ai&view=sources",
    tabs: OP.tabs.label,
    tab: OP.tabs.ai,
    views: OP.aiViews.label,
    view: OP.aiViews.sources,
  },
  {
    from: "/admin/ai-analyst#tab=close",
    to: "/admin/learning",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.close,
  },
  {
    from: "/admin/ai-analyst#tab=learning",
    to: "/admin/learning#tab=learned",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.learned,
  },
  {
    from: "/admin/evolution",
    to: "/admin/learning#tab=learned",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.learned,
  },
  {
    from: "/admin/memory",
    to: "/admin/learning#tab=memory",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.memory,
    views: t.memory.tabs.label,
    view: LEARN.memoryViews.entities,
  },
  {
    from: "/admin/memory#tab=events",
    to: "/admin/learning#tab=memory&view=notes",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.memory,
    views: t.memory.tabs.label,
    view: LEARN.memoryViews.notes,
  },
  {
    from: "/admin/memory#tab=postmortems",
    to: "/admin/learning#tab=postmortems",
    tabs: LEARN.tabs.label,
    tab: LEARN.tabs.postmortems,
  },
];

test("the addresses of the five old AI pages open what they opened, in the two pages that replace them", async ({
  context,
}) => {
  test.setTimeout(240_000);
  for (const old of OLD_ADDRESSES) {
    // A page of its own for each address: the redirect is the app's, on the first load, not a navigation inside one page.
    const page = await context.newPage();
    const w = watch(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(old.from);
    await expect(page, old.from).toHaveURL(new RegExp(`${escapeRe(old.to)}$`));
    await expect(openTab(page, old.tabs), old.from).toHaveText(old.tab);
    if (old.views) await expect(openTab(page, old.views), old.from).toHaveText(old.view ?? "");
    await settle(page);
    await assertClean(page, w);
    await page.close();
  }
});

test("a tab and a view are in the address: a reload keeps them, the first of each leaves the address clean, and a tab of the other page is moved to the page that has it", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await go(page, w, "/admin/operation");
  const tabs = OP.tabs.label;
  const views = OP.aiViews.label;
  await choose(page, tabs, OP.tabs.ai);
  await choose(page, views, OP.aiViews.sources);
  await expect(page).toHaveURL(/\/admin\/operation#tab=ai&view=sources$/);
  await page.reload();
  await settle(page);
  await expect(openTab(page, tabs)).toHaveText(OP.tabs.ai);
  await expect(openTab(page, views)).toHaveText(OP.aiViews.sources);
  await assertClean(page, w);

  // the first view and the first tab leave the address clean
  await choose(page, views, OP.aiViews.today);
  await expect(page).toHaveURL(/\/admin\/operation#tab=ai$/);
  await choose(page, tabs, OP.tabs.day);
  await expect(page).toHaveURL(/\/admin\/operation#?$/);

  // a link that names a tab of Learning, opened on Operation, is moved to Learning (a redirect that kept the hash of an old address)
  await page.goto("/admin/operation#tab=calibration");
  await expect(page).toHaveURL(/\/admin\/learning#tab=calibration$/);
  await expect(openTab(page, LEARN.tabs.label)).toHaveText(LEARN.tabs.calibration);
  await page.goto("/admin/learning#tab=memory&view=notes");
  await settle(page);
  await expect(openTab(page, LEARN.tabs.label)).toHaveText(LEARN.tabs.memory);
  await expect(openTab(page, t.memory.tabs.label)).toHaveText(LEARN.memoryViews.notes);
  await page.reload();
  await settle(page);
  await expect(openTab(page, t.memory.tabs.label)).toHaveText(LEARN.memoryViews.notes);
  await assertClean(page, w);
});
