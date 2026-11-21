/// <reference types="bun" />
/**
 * Plan PM, PM-14-02 (láminas I01 and I04; UX-177): the Match Center read from C-16. One match per level - A (Premier), B (a cup with
 * events and line-ups only), C (goals with minute only) and D (result only) - gives its tabs in the fixed order, none that would open
 * on nothing and none that has something to show taken away; and Estadísticas of a competition without team statistics shows what it
 * does deliver, with one note.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  BlockAvailability,
  CoverageLevel,
  MarketAvailability,
  MatchAvailability,
} from "@/lib/api/v1/types_availability";
import type { MatchEvent } from "@/lib/api/v1/types_center";
import { setLocale } from "@/lib/i18n";
import type { MatchCtx } from "./context";
import { CoverageStats, actFacts, coverageNotes } from "./stats/CoverageStats";
import { blockLevel } from "./stats/coverage";
import { sectionsFor, tabsFor, tabsForCoverage } from "./useMatchTab";

setLocale("es");
afterEach(() => setLocale("es"));

function block(key: string, level: CoverageLevel, exists = level !== "D"): BlockAvailability {
  return {
    key,
    exists,
    level,
    n: 120,
    provisional: false,
    reason: exists ? "ninguno" : "no_entregado",
  };
}

function market(
  key: string,
  level: CoverageLevel,
  over: Partial<MarketAvailability> = {},
): MarketAvailability {
  return {
    key,
    matrix_market: key,
    exists: level !== "D",
    coverage_ok: level === "A" || level === "B",
    level,
    price_in_force: level !== "D",
    prob_computed: level === "A" || level === "B",
    prob_authorised: false,
    settleable: true,
    reason: "ninguno",
    modules: [],
    ...over,
  };
}

function match(
  levels: Record<string, CoverageLevel>,
  markets: MarketAvailability[],
): MatchAvailability {
  return {
    fixture_id: 1,
    kickoff_at: "2026-11-22T20:00:00Z",
    competition_season_id: 9,
    phase: "todas",
    blocks: Object.entries(levels).map(([k, l]) => block(k, l)),
    markets,
    notes: [],
  };
}

// The four matches of the láminas I01 and I04.
const A = match({ events: "A", lineups: "A", team_stats: "A", player_stats: "A" }, [
  market("1X2", "A"),
]);
const B = match({ events: "B", lineups: "B", team_stats: "D", player_stats: "D" }, [
  market("1X2", "B"),
]);
const C = match({ events: "C", lineups: "D", team_stats: "D", player_stats: "D" }, [
  market("1X2", "C"),
]);
const D = match({ events: "D", lineups: "D", team_stats: "D", player_stats: "D" }, [
  market("1X2", "D"),
]);

describe("the tabs by level (I01, I04)", () => {
  test("A: the six, in their order", () => {
    expect(tabsForCoverage(A, { pricesShown: true })).toEqual(tabsFor());
  });
  test("B: the six (line-ups delivered, PrediGol's reading kept)", () => {
    expect(tabsForCoverage(B, { pricesShown: true })).toEqual([
      "summary",
      "analysis",
      "stats",
      "markets",
      "lineups",
      "news",
    ]);
  });
  test("C: no line-ups and no reading; markets with their note", () => {
    expect(tabsForCoverage(C, { pricesShown: true })).toEqual([
      "summary",
      "stats",
      "markets",
      "news",
    ]);
  });
  test("D: Resumen, Estadísticas and Noticias", () => {
    expect(tabsForCoverage(D, { pricesShown: false })).toEqual(["summary", "stats", "news"]);
  });
  test("nothing that has content is taken away", () => {
    // prices on the page keep Mercados even when C-16 lists none
    expect(tabsForCoverage(D, { pricesShown: true })).toContain("markets");
    // a reading PrediGol computed keeps Análisis in C
    const computed = match({ lineups: "C" }, [market("1X2", "C", { prob_computed: true })]);
    expect(tabsForCoverage(computed, { pricesShown: true })).toContain("analysis");
    // line-ups at C: the line-up alone, the tab stays
    expect(tabsForCoverage(computed, { pricesShown: true })).toContain("lineups");
    // not measured or not listed: as today
    const unmeasured = match({}, []);
    unmeasured.blocks = [{ ...block("lineups", "D"), reason: "sin_medir" }];
    expect(tabsForCoverage(unmeasured, { pricesShown: true })).toEqual(tabsFor());
  });
  test("without C-16, the six; the owner's research view still behind its button", () => {
    expect(tabsForCoverage(null, { pricesShown: false })).toEqual(tabsFor());
    expect(sectionsFor(true, ["summary", "stats", "news"])).toEqual([
      "summary",
      "stats",
      "news",
      "advanced",
    ]);
    expect(sectionsFor(false)).toEqual(tabsFor());
  });
  test("the level of a block, when measured", () => {
    expect(blockLevel(C.blocks, "events")).toBe("C");
    expect(blockLevel(C.blocks, "xg")).toBeNull();
  });
});

function ev(
  seq: number,
  minute: number,
  side: "home" | "away",
  type: string,
  detail: string,
): MatchEvent {
  return {
    seq,
    minute,
    extra_minute: null,
    side,
    player: "X",
    player_id: seq,
    assist: null,
    type,
    detail,
    comments: null,
  };
}

describe("Estadísticas without team statistics (I04 B, C, D)", () => {
  const events = [
    ev(1, 34, "home", "Goal", "Normal Goal"),
    ev(2, 77, "away", "Goal", "Normal Goal"),
    ev(3, 20, "home", "Card", "Yellow Card"),
    ev(4, 50, "away", "Card", "Red Card"),
    ev(5, 60, "home", "subst", "Substitution 1"),
  ];

  test("the facts of the match sheet from the events (I04 B)", () => {
    const rows = actFacts(events, { home: 1, away: 1 })!;
    expect(rows.map((r) => [r.key, r.home, r.away])).toEqual([
      ["goals", 1, 1],
      ["yellow", 1, 0],
      ["red", 0, 1],
      ["subs", 1, 0],
    ]);
    expect(actFacts(null, { home: 0, away: 0 })).toBeNull();
  });

  test("one note for what the competition does not offer", () => {
    const notes = coverageNotes(C.blocks);
    expect(notes.map((n) => n.subject)).toEqual([
      "alineaciones",
      "estadísticas de partido",
      "estadísticas por jugador",
    ]);
    expect(notes.every((n) => n.state?.kind === "no_existe")).toBe(true);
  });

  test("rendered: facts, a single note, form and table; no empty card", () => {
    const ctx = {
      fixtureId: "1",
      phase: "finished",
      score: { home: 1, away: 1 },
      match: {
        id: 1,
        home: { id: 1, name: "Bahía Azul", logo_url: null },
        away: { id: 2, name: "Los Nevados", logo_url: null },
        competition: { id: 9, name: "Copa Regional" },
      },
      center: {
        data: {
          events: { status: "ok", data: events },
          statistics: { status: "not_available", data: [] },
          form: { status: "not_available", data: [] },
          standings: { status: "not_available", data: [] },
        },
        loading: false,
        error: null,
        status: null,
        retry: () => {},
      },
      goTo: () => {},
    } as unknown as MatchCtx;
    const client = new QueryClient({
      defaultOptions: { queries: { enabled: false, retry: false } },
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <CoverageStats ctx={ctx} blocks={B.blocks} />
      </QueryClientProvider>,
    );
    expect(html).toContain("Hechos del acta");
    expect(html).toContain("Tarjetas amarillas");
    expect(html.match(/data-testid="unavailable-notes"/g)?.length).toBe(1);
    expect(html).toContain("Esta competición no ofrece");
    expect(html).toContain("estadísticas de partido");
  });
});
