/// <reference types="bun" />
/**
 * Plan PM, PM-10-06 (OP-16; FE-004): no NEW chart without its evidence level, its reading sentence and its accessibility review.
 * A file that draws a chart - it imports Recharts, the chart primitives of `components/analytics` or `components/ui/chart`, or uses
 * `ChartCard`/`ChartContainer` - must draw it inside `EvidenceChart`, which requires the three. The charts that existed on
 * 20 Nov 2026 are listed below and keep working as they are; the list may only shrink (a piece moved to `EvidenceChart` leaves it).
 */
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = join(import.meta.dir, "..", "..");

/** The charts drawn before PM-10-06 (20 Nov 2026). Do not add to it: a new chart uses EvidenceChart. */
const BEFORE_PM_10_06 = [
  "live/AnalyticsLive.tsx",
  "live/ModelsLive.tsx",
  "product/match/stats/ProbabilitiesPanel.tsx",
  "product/odds/MovementPanel.tsx",
  "product/odds/explorer/MovementChart.tsx",
  "product/records/Recap.tsx",
  "routes/admin.backtesting.tsx",
  "routes/admin.models.tsx",
  "routes/admin.odds.tsx",
  "routes/admin.performance.tsx",
];

/** The building blocks themselves (they are what a chart is made of, not a chart a reader sees). */
function isPrimitive(path: string): boolean {
  return path.startsWith("components/analytics/") || path === "components/ui/chart.tsx";
}

const DRAWS_A_CHART = [
  /from\s+["']recharts["']/,
  /from\s+["']@\/components\/analytics\/(?!evidence|EvidenceChart|stats\/format)[^"']+["']/,
  /from\s+["']@\/components\/ui\/chart["']/,
  /<ChartCard\b/,
  /<ChartContainer\b/,
];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory())
      return name === "locales" || name === "mock" ? [] : sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

function chartFiles(): string[] {
  return sources(ROOT)
    .map((p) => relative(ROOT, p).split("\\").join("/"))
    .filter((p) => !isPrimitive(p))
    .filter((p) => DRAWS_A_CHART.some((re) => re.test(readFileSync(join(ROOT, p), "utf8"))));
}

describe("every new chart carries evidence, reading and review", () => {
  test("a chart file outside the list of 20 Nov 2026 draws inside EvidenceChart", () => {
    const offenders = chartFiles().filter(
      (p) =>
        !BEFORE_PM_10_06.includes(p) &&
        !/\bEvidenceChart\b/.test(readFileSync(join(ROOT, p), "utf8")),
    );
    expect(offenders).toEqual([]);
  });

  test("the list only shrinks: every file in it still draws a chart", () => {
    const found = new Set(chartFiles());
    expect(BEFORE_PM_10_06.filter((p) => !found.has(p))).toEqual([]);
  });

  test("the guard sees a chart where there is one", () => {
    expect(chartFiles()).toContain("routes/admin.models.tsx");
    expect(DRAWS_A_CHART.some((re) => re.test('import { BarChart } from "recharts";'))).toBe(true);
    expect(
      DRAWS_A_CHART.some((re) =>
        re.test('import { EvidenceChart } from "@/components/analytics/EvidenceChart";'),
      ),
    ).toBe(false);
  });
});
