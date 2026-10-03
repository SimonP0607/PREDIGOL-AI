/**
 * The product's main paths, clicked through against the running stack.
 * Every page on the way must also pass the checks in support.ts.
 */
import { expect, test, type Page } from "@playwright/test";
import { JOB_LABEL } from "../src/live/labels";
import { API_URL, api, assertClean, note, settle, watch, type Watch } from "./support";

const MODEL_LABEL: Record<string, string> = {
  poisson: "Poisson (Maher)",
  dixon_coles: "Dixon-Coles",
  elo_ologit: "Elo V2 + ordered logit",
  base_rates: "League base rates",
  mnlogit: "Multinomial logit (features v2)",
};
const VERDICT_TEXT: Record<string, string> = {
  better: "Beats market",
  indistinguishable: "No detectable difference",
  worse: "Worse than market",
};

test.beforeAll(async () => {
  // Fail with the reason, not with forty timeouts, when the API is not up.
  // /health answers 503 while something is down; any JSON answer will do.
  const res = await fetch(`${API_URL}/health`).catch((e: unknown) => {
    throw new Error(`API not reachable at ${API_URL} (${String(e)}): run scripts/dev-up api web`);
  });
  expect(((await res.json()) as { status?: string }).status).toBeTruthy();
});

async function open(page: Page, w: Watch, path: string, heading: string | RegExp): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
  await settle(page);
  await assertClean(page, w);
}

/** Click the first fixture link inside the page body; returns "Home v Away". */
async function followFirstFixture(page: Page, w: Watch): Promise<string | null> {
  const link = page.locator('main a[href^="/matches/"]').first();
  if ((await link.count()) === 0) return null;
  const name = (await link.innerText()).replace(/\s+/g, " ").trim();
  await link.click();
  await expect(page).toHaveURL(/\/matches\/\d+$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
  await settle(page);
  await assertClean(page, w);
  return name;
}

async function everyTab(page: Page, w: Watch, names: readonly string[]): Promise<void> {
  for (const name of names) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const tab = page.getByRole("tab", { name: new RegExp(`^${escaped}`) });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await settle(page);
    await assertClean(page, w);
  }
}

test("Overview → Match Center, every section", async ({ page }, info) => {
  const w = watch(page);
  await open(page, w, "/", "Overview");
  const name = await followFirstFixture(page, w);
  if (name === null) {
    note(info, "the overview lists no fixture on this database");
    return;
  }
  await everyTab(page, w, [
    "Stats",
    "Events",
    "Line-ups",
    "Players",
    "Context",
    "Markets",
    "In-play",
    "Models",
    "Timeline",
    "Lineage",
    "Audit",
    "Overview",
  ]);
});

test("Match Center → Audit shows the chain exactly as the API reconstructs it", async ({
  page,
}, info) => {
  const w = watch(page);
  const list = await api<Array<{ id: number; home: { name: string }; away: { name: string } }>>(
    "/api/v1/matches?status=finished&limit=1",
  );
  const first = list.data[0];
  if (!first) {
    note(info, "no finished fixture on this database");
    return;
  }
  const audit = await api<{ complete: boolean; steps: Array<{ key: string; state: string }> }>(
    `/api/v1/matches/${first.id}/audit`,
  );
  await open(page, w, `/matches/${first.id}`, `${first.home.name} v ${first.away.name}`);
  await everyTab(page, w, ["Audit"]);
  expect(audit.data.steps.map((s) => s.key)).toEqual([
    "provider",
    "raw",
    "normalized",
    "features",
    "models",
    "predictions",
    "market",
    "picks",
    "settlement",
  ]);
  for (const s of audit.data.steps) {
    await expect(page.locator(`[data-step="${s.key}"]`)).toHaveAttribute("data-state", s.state);
  }
  await expect(page.getByTestId("audit-summary")).toContainText(
    audit.data.complete ? "Chain complete" : "with a gap",
  );
});

test("Search: the topbar searches stored data, never the demo index", async ({ page }, info) => {
  const w = watch(page);
  const teams = await api<Array<{ id: number; name: string }>>("/api/v1/teams?limit=1");
  const team = teams.data[0];
  if (!team) {
    note(info, "no team stored: nothing to search for");
    return;
  }
  await open(page, w, "/", "Overview");
  const box = page.getByRole("searchbox", { name: "Search fixtures, teams and models" });
  await box.fill(team.name.slice(0, Math.min(6, team.name.length)));
  await expect(
    page
      .getByRole("button", { name: new RegExp(team.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) })
      .first(),
  ).toBeVisible();
  await expect(page.getByText("indexed demo dataset")).toHaveCount(0);
  await assertClean(page, w);
});

test("Matches → Match", async ({ page }) => {
  const w = watch(page);
  const list = await api<Array<{ id: number }>>("/api/v1/matches?limit=1");
  await open(page, w, "/matches", "Matches");
  const name = await followFirstFixture(page, w);
  if (list.data.length)
    expect(name, "the API has fixtures, the page must list them").not.toBeNull();
});

test("Odds → Match, and the historical market", async ({ page }, info) => {
  const w = watch(page);
  const captured = await api<Array<{ id: number }>>("/api/v1/odds");
  await open(page, w, "/odds", "Odds");
  if (captured.data.length === 0) {
    // Nothing captured yet: the page must say so rather than show demo prices.
    await expect(page.locator('main a[href^="/matches/"]')).toHaveCount(0);
    note(info, `no captured prices yet (${captured.status}): Odds → Match not exercised`);
  } else {
    await everyTab(page, w, ["Board", "Movement", "Near-close", "Consensus"]);
    const name = await followFirstFixture(page, w);
    expect(name).not.toBeNull();
    await everyTab(page, w, ["Markets"]);
    await expect(page.getByText("Captured prices", { exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Odds");
  }
  await everyTab(page, w, ["Historical market"]);
});

test("Models: every model is shown against the market", async ({ page }, info) => {
  const w = watch(page);
  const res = await api<{
    models: {
      status: string;
      data: Array<{
        name: string;
        latest_backtest: { primary: { verdict: string } | null } | null;
      }> | null;
    };
  }>("/api/v1/models");
  await open(page, w, "/models", "Models");
  const models = res.data.models.data ?? [];
  if (models.length === 0) note(info, `no model versions (${res.data.models.status})`);
  const main = page.locator("main");
  for (const m of models) {
    await expect(main.getByText(MODEL_LABEL[m.name] ?? m.name).first()).toBeVisible();
    const verdict = m.latest_backtest?.primary?.verdict;
    if (verdict)
      await expect(main.getByText(VERDICT_TEXT[verdict] ?? verdict).first()).toBeVisible();
  }
  // The detail of every backtested model, every view of it.
  const tested = models.filter((m) => m.latest_backtest !== null);
  if (tested.length === 0) note(info, "no backtested model: the detail views are not exercised");
  for (const m of tested) {
    await everyTab(page, w, [MODEL_LABEL[m.name] ?? m.name]);
    await everyTab(page, w, [
      "Calibration",
      "Leagues",
      "Temporal stability",
      "Markets",
      "Protocol",
    ]);
  }
  // And the search behind the chosen hyper-parameters.
  await open(page, w, "/backtesting", "Backtesting");
});

test("Analytics: every section shows what the API computed", async ({ page }, info) => {
  const w = watch(page);
  const [profiles, experiments, market, coverage] = await Promise.all([
    api<Array<{ competition: string; season: number }>>("/api/v1/analytics/competitions"),
    api<
      Array<{
        id: number;
        model_family: string;
        research_status: string;
        reproduction_of: number | null;
      }>
    >("/api/v1/analytics/experiments"),
    api<{ n_fixtures: number }>("/api/v1/analytics/market"),
    api<Array<{ competition: string }>>("/api/v1/analytics/coverage"),
  ]);
  await open(page, w, "/analytics", "Analytics");
  const main = page.locator("main");
  const first = profiles.data[0];
  if (first) await expect(main.getByText(first.competition).first()).toBeVisible();
  else note(info, "no competition profile on this database");
  await everyTab(page, w, ["Teams"]);
  await everyTab(page, w, ["Models"]);
  if (experiments.data.length === 0) note(info, `no experiment recorded (${experiments.status})`);
  const originals = experiments.data.filter((e) => e.reproduction_of === null);
  for (const e of originals) await expect(main.getByText(`#${e.id} ·`)).toBeVisible();
  await expect(main.getByText("PRODUCTION", { exact: true })).toHaveCount(
    originals.filter((e) => e.research_status === "PRODUCTION").length,
  );
  await everyTab(page, w, ["Market"]);
  if (market.status === "ok")
    await expect(
      main.getByText(market.data.n_fixtures.toLocaleString("en-US")).first(),
    ).toBeVisible();
  else note(info, `no market baseline (${market.status})`);
  await everyTab(page, w, ["Coverage", "Migration", "Competitions"]);
  expect(coverage.data.length).toBeGreaterThanOrEqual(profiles.data.length > 0 ? 1 : 0);
});

test("Picks: the lifecycle as the API reports it", async ({ page }, info) => {
  const w = watch(page);
  const res = await api<{
    lifecycle: Record<string, number>;
    picks: { data: Array<{ id: number }> | null } | Array<{ id: number }>;
  }>("/api/v1/picks");
  await open(page, w, "/picks", "Picks");
  const main = page.locator("main");
  for (const stage of ["Candidates", "Rejected", "Shadow", "Qualified", "Published"]) {
    await expect(main.getByText(stage, { exact: true }).first()).toBeVisible();
  }
  await expect(main.getByText("disabled in the schema").first()).toBeVisible();
  const lc = res.data.lifecycle;
  if ((lc["shadow"] ?? 0) + (lc["settled"] ?? 0) + (lc["qualified"] ?? 0) === 0) {
    note(info, `no shadow picks yet (status ${res.status}): the lineage view is not exercised`);
  } else {
    // A pick opens onto what produced it: the model version, the data
    // cut-off, and the payload the price came from.
    await expect(main.getByText("Data cut-off", { exact: true })).toHaveCount(0);
    await main.locator("tbody tr").first().click();
    for (const label of ["Model version", "Data cut-off", "Input hash", "Captured", "Payload"]) {
      await expect(main.getByText(label, { exact: true }).first()).toBeVisible();
    }
    await assertClean(page, w);
  }
  await everyTab(page, w, ["Candidates", "Picks"]);
});

test("Data Quality: every tab, and the jobs the ledger knows", async ({ page }) => {
  const w = watch(page);
  const jobs = await api<Array<{ job_type: string }>>("/api/v1/ops/jobs");
  await open(page, w, "/data-quality", "Data Quality");
  await everyTab(page, w, ["Issues", "Coverage", "Jobs"]);
  for (const j of jobs.data) {
    const label = JOB_LABEL[j.job_type] ?? j.job_type;
    await expect(page.locator("main").getByText(label, { exact: true }).first()).toBeVisible();
  }
  await everyTab(page, w, ["Ingestion runs", "Notes"]);
});
