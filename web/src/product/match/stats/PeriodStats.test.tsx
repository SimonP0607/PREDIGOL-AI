/// <reference types="bun" />
/**
 * Plan PM, PM-10-03 (OP-06; FE-010): the statistics by half. A competition that built the halves gets the match, the first and the
 * second half in the system's pieces; a figure the provider did not send is a «—», never a zero; a statistic the competition has not
 * built is not drawn; and the two ways the halves can be absent say so with the shared «información no disponible».
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { reviewProblems } from "@/components/analytics/evidence";
import type { Envelope } from "@/lib/api/v1/types";
import type { MatchPeriodStats } from "@/lib/api/v1/types_period_stats";
import { setLocale } from "@/lib/i18n";
import { MATCH_PERIODS_REVIEW, PeriodStats, PeriodStatsCard } from "./PeriodStats";
import { halvesAddUp, periodRows, periodsWithRows } from "./periods";

setLocale("es");
afterEach(() => setLocale("es"));

const TEAMS = { home: { name: "Cordillera" }, away: { name: "Altiplano" } };

const DATA: MatchPeriodStats = {
  fixture_id: 7,
  built: ["shots", "corners"],
  asked: 12,
  as_of: "2026-11-24T20:00:00Z",
  source: "api-football",
  periods: [
    {
      period: "total",
      figures: [
        { key: "shots", home: 11, away: 7 },
        { key: "corners", home: 7, away: 3 },
      ],
    },
    {
      period: "1h",
      figures: [
        { key: "shots", home: 6, away: 4 },
        { key: "corners", home: null, away: 2 },
      ],
    },
    {
      period: "2h",
      figures: [
        { key: "shots", home: 5, away: 3 },
        { key: "corners", home: 3, away: 1 },
      ],
    },
  ],
};

function envelope(over: Partial<Envelope<MatchPeriodStats>>): Envelope<MatchPeriodStats> {
  return {
    status: "ok",
    data: DATA,
    reason: null,
    meta: { generated_at: "2026-11-24T20:00:00Z", api_version: "v1" },
    ...over,
  } as Envelope<MatchPeriodStats>;
}

function seeded(answer: Envelope<MatchPeriodStats>): string {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(["v1", "match-period-stats", "7"], answer);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <PeriodStats fixtureId="7" teams={TEAMS} />
    </QueryClientProvider>,
  );
}

describe("periods (the rows)", () => {
  test("each period gives its rows under the Match Center's keys, a missing side stays null", () => {
    expect(periodRows(DATA, "total").map((r) => [r.key, r.home, r.away])).toEqual([
      ["shots", 11, 7],
      ["corners", 7, 3],
    ]);
    const first = periodRows(DATA, "1h").find((r) => r.key === "corners");
    expect(first?.home).toBeNull();
    expect(first?.away).toBe(2);
    expect(periodsWithRows(DATA)).toEqual(["total", "1h", "2h"]);
  });

  test("a statistic with both sides missing is left out, a period without rows is not offered", () => {
    const thin: MatchPeriodStats = {
      ...DATA,
      periods: [
        { period: "total", figures: [{ key: "shots", home: 1, away: 2 }] },
        { period: "1h", figures: [{ key: "shots", home: null, away: null }] },
      ],
    };
    expect(periodRows(thin, "1h")).toEqual([]);
    expect(periodsWithRows(thin)).toEqual(["total"]);
  });

  test("the halves add up to the match, and a figure that does not is detected", () => {
    expect(halvesAddUp(DATA)).toBe(true);
    const off: MatchPeriodStats = {
      ...DATA,
      periods: DATA.periods.map((p) =>
        p.period === "total"
          ? { ...p, figures: [{ key: "shots", home: 12, away: 7 }, ...p.figures.slice(1)] }
          : p,
      ),
    };
    expect(halvesAddUp(off)).toBe(false);
  });
});

describe("PeriodStatsCard", () => {
  test("draws the match first with the switch, its sentence and the table of the same figures", () => {
    const html = renderToStaticMarkup(
      <PeriodStatsCard data={DATA} teams={TEAMS} source="estadísticas por mitad del proveedor" />,
    );
    expect(html).toContain('data-testid="match-periods"');
    expect(html).toContain("Estadísticas por mitad");
    expect(html).toContain('data-testid="match-periods-switch"');
    expect(html).toContain('data-period="total"');
    expect(html).toContain("1.er tiempo");
    expect(html).toContain("2.º tiempo");
    expect(html).toContain("Cordillera");
    expect(html).not.toContain("no coincide");
  });

  test("the card's review has its fourteen checks", () => {
    expect(reviewProblems(MATCH_PERIODS_REVIEW)).toEqual([]);
  });
});

describe("PeriodStats (the answer)", () => {
  test("an ok answer is the card", () => {
    expect(seeded(envelope({}))).toContain('data-testid="match-periods"');
  });

  test("a competition that does not deliver the halves is one line, no card", () => {
    const html = seeded(
      envelope({
        status: "not_available",
        reason: "sin_estadisticas_por_mitad",
        data: { ...DATA, built: [], periods: [] },
      }),
    );
    expect(html).toContain('data-unavailable="no_existe"');
    expect(html).not.toContain("match-periods");
  });

  test("a match whose halves have not come is the pending card", () => {
    const html = seeded(
      envelope({
        status: "not_available",
        reason: "partido_sin_mitades",
        data: { ...DATA, periods: [] },
      }),
    );
    expect(html).toContain('data-unavailable="pendiente"');
    expect(html).not.toContain("match-periods");
  });

  test("nothing while there is no answer", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <PeriodStats fixtureId="9" teams={TEAMS} />
      </QueryClientProvider>,
    );
    expect(html).toBe("");
  });
});
