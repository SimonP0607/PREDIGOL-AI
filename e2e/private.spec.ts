/**
 * The private platform's new paths: Live, the Match Center football sections,
 * Players, System / Admin, Performance slices, and every item of the sidebar.
 * Against the running stack; where real data is too thin, the test says so.
 */
import { expect, test, type Page } from "@playwright/test";
import { api, assertClean, note, settle, watch, type Watch } from "./support";

async function open(page: Page, w: Watch, path: string, heading: string | RegExp): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
  await settle(page);
  await assertClean(page, w);
}

async function tab(page: Page, w: Watch, name: string): Promise<void> {
  const t = page.getByRole("tab", { name: new RegExp(`^${name}`) });
  await t.click();
  await expect(t).toHaveAttribute("aria-selected", "true");
  await settle(page);
  await assertClean(page, w);
}

const NAV: Array<[string, string | RegExp]> = [
  ["Overview", "Overview"],
  ["Matches", "Matches"],
  ["Live", "Live"],
  ["Picks", "Picks"],
  ["Odds", "Odds"],
  ["Performance", "Performance"],
  ["Models", "Models"],
  ["Backtesting", "Backtesting"],
  ["Analytics", "Analytics"],
  ["Competitions", "Competitions"],
  ["Teams", "Teams"],
  ["Players", "Players"],
  ["Rankings", "Rankings"],
  ["Data Quality", "Data Quality"],
  ["System / Admin", "System / Admin"],
  ["Settings", "Settings"],
];

test("Every sidebar item opens its page cleanly", async ({ page }) => {
  test.setTimeout(150_000);
  const w = watch(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, w, "/", "Overview");
  for (const [label, heading] of NAV) {
    await page
      .getByRole("navigation")
      .getByRole("link", { name: label, exact: true })
      .first()
      .click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
    await settle(page);
    await assertClean(page, w);
  }
});

test("Live: the board matches the API, and a match opens its in-play data", async ({
  page,
}, info) => {
  const w = watch(page);
  const board = await api<{
    matches: Array<{ fixture_id: number; home: { name: string }; away: { name: string } }>;
  }>("/api/v1/live");
  await open(page, w, "/live", "Live");
  const first = board.data.matches[0];
  if (!first) {
    await expect(page.getByText("No tracked match is in play right now.")).toBeVisible();
    note(info, "no match in play at test time: only the empty state was checked");
    return;
  }
  await expect(page.getByText(first.home.name).first()).toBeVisible();
  await page.locator(`a[href="/matches/${first.fixture_id}"]`).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    `${first.home.name} v ${first.away.name}`,
  );
  await settle(page);
  for (const t of ["In-play", "Stats", "Events"]) await tab(page, w, t);
  await expect(page.getByText("never used to judge, train or backtest").first()).toBeHidden();
});

test("Match Center: every football section of a played match", async ({ page }, info) => {
  test.setTimeout(90_000);
  const w = watch(page);
  const list = await api<Array<{ id: number; home: { name: string }; away: { name: string } }>>(
    "/api/v1/matches?status=finished&order=desc&limit=25",
  );
  let chosen: { id: number; home: { name: string }; away: { name: string } } | null = null;
  for (const m of list.data) {
    const c = await api<{ statistics: { status: string }; lineups: { status: string } } | null>(
      `/api/v1/matches/${m.id}/center`,
    );
    if (c.data && c.data.statistics.status === "ok" && c.data.lineups.status === "ok") {
      chosen = m;
      break;
    }
  }
  if (!chosen) {
    note(info, "none of the 25 latest finished matches has statistics and line-ups stored");
    return;
  }
  await open(page, w, `/matches/${chosen.id}`, `${chosen.home.name} v ${chosen.away.name}`);
  for (const t of [
    "Stats",
    "Events",
    "Line-ups",
    "Players",
    "Context",
    "In-play",
    "Markets",
    "Overview",
  ]) {
    await tab(page, w, t);
  }
  await tab(page, w, "Line-ups");
  await expect(page.getByText(/Starting XI \(\d+\)/i).first()).toBeVisible();
});

test("Players: search, open a profile, follow a match", async ({ page }, info) => {
  const w = watch(page);
  await open(page, w, "/players", "Players");
  const top = await api<Array<{ id: number; name: string }>>("/api/v1/players?limit=5");
  const someone = top.data[0];
  if (!someone) {
    note(info, "no player statistics in the last 30 days");
    return;
  }
  const term = someone.name.split(" ").pop() ?? someone.name;
  await page.getByLabel("Player search").fill(term.slice(0, 12));
  await settle(page);
  await page.getByRole("link", { name: someone.name }).first().click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(someone.name);
  await settle(page);
  await assertClean(page, w);
  await expect(page.getByText("By competition and season")).toBeVisible();
  const match = page.locator('main a[href^="/matches/"]').first();
  if ((await match.count()) > 0) {
    await match.click();
    await expect(page).toHaveURL(/\/matches\/\d+$/);
    await settle(page);
    await assertClean(page, w);
  }
});

test("System / Admin shows the running system", async ({ page }) => {
  const w = watch(page);
  const admin = await api<{ schema_revision: string; quota: { budget: number } }>(
    "/api/v1/admin/overview",
  );
  await open(page, w, "/admin", "System / Admin");
  for (const section of [
    "Worker jobs",
    "Captures",
    "History migration",
    "Data quality",
    "Backups",
    "Versions",
  ]) {
    await expect(page.getByRole("heading", { name: section, exact: true })).toBeVisible();
  }
  await expect(page.getByText(`schema ${admin.data.schema_revision}`)).toBeVisible();
});

test("Performance: slices appear only with settled bets", async ({ page }, info) => {
  const w = watch(page);
  const perf = await api<{ settled: number; slices?: unknown[] }>("/api/v1/performance");
  await open(page, w, "/performance", "Performance");
  if (perf.status !== "ok" || !perf.data.slices?.length) {
    note(info, "not enough settled shadow bets for slices");
    return;
  }
  for (const title of ["By model", "By market", "By month of kick-off"]) {
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  }
});
