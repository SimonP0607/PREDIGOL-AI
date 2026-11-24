/// <reference types="bun" />
/**
 * Plan PM, PM-15-01 (CI-021): the availability matrix end to end, the screen half. The four answers of C-16 in
 * `fixtures/matriz_e2e.json` are not written here: `backend/tests/integration/test_matrix_e2e_pm1501.py` seeds four real competitions
 * from annex B (Primera A, level A; NB I, B; K League 1, C; Primera B, D), runs the nightly batch and asks the real API, and fails when
 * this file says something else. Here each answer is drawn as a reader would get it - the Match Center's switches on, as they will be
 * after PM-15-03, and only in this test - on a match whose page holds EVERY figure (shots, xG, players): a screen must not draw what the
 * matrix denies just because a number arrived. Nothing here decides a level.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import type { MatchAvailability } from "@/lib/api/v1/types_availability";
import type { MatchEvent, TeamStatLine } from "@/lib/api/v1/types_center";
import { setLocale } from "@/lib/i18n";
import type { MatchCtx } from "./context";
import { StatsTab } from "./StatsTab";
import { blockAllows, blockLevel, type MatchBlockKey } from "./stats/coverage";
import { tabsFor, tabsForCoverage } from "./useMatchTab";
import e2e from "./fixtures/matriz_e2e.json";

setLocale("es");
afterEach(() => setLocale("es"));

type Level = "A" | "B" | "C" | "D";
interface E2ECase {
  league: number;
  competition: string;
  season: number;
  annex_b: Record<string, Level>;
  match: MatchAvailability;
}
const CASES = e2e.cases as unknown as Record<Level, E2ECase>;
const LEVELS: readonly Level[] = ["A", "B", "C", "D"];
const BLOCK_DATA: Record<MatchBlockKey, readonly string[]> = {
  events: ["events"],
  lineups: ["lineups"],
  team_stats: ["corners", "yellow_cards", "shots"],
  shots_on_target: ["shots_on_target"],
  fouls: ["fouls"],
  xg: ["xg"],
  player_stats: ["player_stats"],
  referee: ["referee"],
};
const RANK: Record<string, number> = { A: 4, B: 3, C: 2, D: 1, MI: 0 };

function line(side: "home" | "away", over: Partial<TeamStatLine>): TeamStatLine {
  return {
    side,
    shots: null,
    shots_on_target: null,
    shots_off_target: null,
    shots_blocked: null,
    shots_inside_box: null,
    shots_outside_box: null,
    corners: null,
    fouls: null,
    offsides: null,
    yellow_cards: null,
    red_cards: null,
    saves: null,
    possession_pct: null,
    passes: null,
    passes_accurate: null,
    expected_goals: null,
    fetched_at: "2026-11-22T22:00:00Z",
    source: "api-football",
    ...over,
  };
}

/** Every figure the Match Center can draw: what a provider that sends everything leaves on the page. */
const LINES: TeamStatLine[] = [
  line("home", {
    shots: 16,
    shots_on_target: 6,
    shots_off_target: 6,
    shots_blocked: 4,
    shots_inside_box: 10,
    shots_outside_box: 6,
    corners: 7,
    fouls: 11,
    yellow_cards: 2,
    red_cards: 0,
    possession_pct: "58",
    passes: 480,
    passes_accurate: 410,
    expected_goals: "1.84",
  }),
  line("away", {
    shots: 9,
    shots_on_target: 3,
    shots_off_target: 4,
    shots_blocked: 2,
    shots_inside_box: 4,
    shots_outside_box: 5,
    corners: 3,
    fouls: 14,
    yellow_cards: 3,
    red_cards: 1,
    possession_pct: "42",
    passes: 350,
    passes_accurate: 270,
    expected_goals: "0.71",
  }),
];

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
const EVENTS: MatchEvent[] = [
  ev(1, 23, "home", "Goal", "Normal Goal"),
  ev(2, 40, "away", "Card", "Yellow Card"),
  ev(3, 58, "away", "Goal", "Normal Goal"),
  ev(4, 81, "home", "Goal", "Normal Goal"),
];

function ctxFor(c: E2ECase): MatchCtx {
  return {
    fixtureId: String(c.match.fixture_id),
    phase: "finished",
    score: { home: 2, away: 1 },
    match: {
      id: c.match.fixture_id,
      home: { id: 1, name: "Cordillera", logo_url: null },
      away: { id: 2, name: "Altiplano", logo_url: null },
      competition: { id: c.league, name: c.competition },
      score: { et_home: null, et_away: null, pen_home: null, pen_away: null },
    },
    center: {
      data: {
        events: { status: "ok", data: EVENTS },
        statistics: { status: "ok", data: LINES },
        lineups: { status: "not_available", data: [] },
        players: { status: "not_available", data: [] },
        absences: { status: "not_available", data: [] },
        form: { status: "not_available", data: [] },
        standings: { status: "not_available", data: [] },
        h2h: { status: "not_available", data: [] },
        live_states: { status: "not_available", data: [] },
        live_odds: { status: "not_available", data: [] },
        live_movement: { status: "not_available", data: [] },
      },
      loading: false,
      error: null,
      status: null,
      retry: () => {},
    },
    goTo: () => {},
  } as unknown as MatchCtx;
}

/** Estadísticas as a reader gets it with the Match Center's switches on and C-16 answering this case (nothing fetched). */
function drawStats(c: E2ECase): string {
  const client = new QueryClient({
    defaultOptions: { queries: { enabled: false, retry: false, staleTime: Infinity } },
  });
  client.setQueryData(["auth", "me"], {
    id: 1,
    role: "USER",
    availability: true,
    match_coverage: true,
    match_shot_funnel: true,
    match_balance: true,
    lineup_layers: true,
  });
  client.setQueryData(["v1", "match-availability", String(c.match.fixture_id)], {
    data: {
      contract: "C-16",
      projection: "public",
      scope: "partido",
      competitions: [],
      match: c.match,
    },
  });
  // the provider reads the browser's language when nobody is signed in; bun's navigator has none
  const nav = globalThis.navigator as { language?: string } | undefined;
  const stub = nav !== undefined && typeof nav.language !== "string";
  if (stub) Object.defineProperty(nav, "language", { value: "es-ES", configurable: true });
  try {
    return renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <StatsTab ctx={ctxFor(c)} />
        </AuthProvider>
      </QueryClientProvider>,
    );
  } finally {
    if (stub) delete (nav as { language?: string }).language;
  }
}

describe("the four cases come from the batch and the API, not from this file", () => {
  test("Primera A, NB I, K League 1 and Primera B, one per level", () => {
    expect(LEVELS.map((l) => [l, CASES[l].league, CASES[l].competition])).toEqual([
      ["A", 239, "Primera A"],
      ["B", 271, "NB I"],
      ["C", 292, "K League 1"],
      ["D", 240, "Primera B"],
    ]);
  });
  test("each block is the worst of its data in annex B", () => {
    for (const l of LEVELS) {
      const c = CASES[l];
      for (const [key, data] of Object.entries(BLOCK_DATA)) {
        const worst = data.map((d) => c.annex_b[d]!).sort((a, b) => RANK[a]! - RANK[b]!)[0] ?? null;
        expect([l, key, blockLevel(c.match.blocks, key as MatchBlockKey)]).toEqual([l, key, worst]);
      }
    }
  });
});

describe("what the page may draw, block by block", () => {
  test("a block is drawn only at A or B", () => {
    for (const l of LEVELS) {
      for (const b of CASES[l].match.blocks) {
        const allowed = blockAllows(CASES[l].match.blocks, b.key as MatchBlockKey);
        expect([l, b.key, allowed]).toEqual([l, b.key, b.level === "A" || b.level === "B"]);
      }
    }
  });
  test("the team statistics: A and B yes, C and D no", () => {
    expect(LEVELS.map((l) => blockAllows(CASES[l].match.blocks, "team_stats"))).toEqual([
      true,
      true,
      false,
      false,
    ]);
  });
  test("the layers of the line-up (player statistics): A and B yes, C and D no", () => {
    expect(LEVELS.map((l) => blockAllows(CASES[l].match.blocks, "player_stats"))).toEqual([
      true,
      true,
      false,
      false,
    ]);
  });
  test("the referee block: A (Primera A), B (NB I) and A (K League 1) yes; Primera B no", () => {
    expect(LEVELS.map((l) => blockAllows(CASES[l].match.blocks, "referee"))).toEqual([
      true,
      true,
      true,
      false,
    ]);
  });
});

describe("the tabs (lámina I04)", () => {
  test("A, B and C keep the six; D loses Análisis (no reading, 1X2 at D) and Mercados (no price)", () => {
    expect(tabsForCoverage(CASES.A.match, { pricesShown: false })).toEqual(tabsFor());
    expect(tabsForCoverage(CASES.B.match, { pricesShown: false })).toEqual(tabsFor());
    expect(tabsForCoverage(CASES.C.match, { pricesShown: false })).toEqual(tabsFor());
    expect(tabsForCoverage(CASES.D.match, { pricesShown: false })).toEqual([
      "summary",
      "stats",
      "lineups",
      "news",
    ]);
    // a price on the page keeps Mercados: nothing with something to show is taken away
    expect(tabsForCoverage(CASES.D.match, { pricesShown: true })).toContain("markets");
  });
});

describe("Estadísticas drawn, with every figure on the page", () => {
  test("A and B: the card of figures and the shot funnel; no note of what is missing", () => {
    for (const l of ["A", "B"] as const) {
      const html = drawStats(CASES[l]);
      expect([l, html.includes('data-testid="match-viz"')]).toEqual([l, true]);
      expect([l, html.includes("Estadísticas del partido")]).toEqual([l, true]);
      expect([l, html.includes("Mejores valorados")]).toEqual([l, true]);
      expect([l, html.includes('data-testid="coverage-stats"')]).toEqual([l, false]);
    }
  });
  test("C and D: no card of team figures, no funnel, no balance - what the competition delivers and one note", () => {
    for (const l of ["C", "D"] as const) {
      const html = drawStats(CASES[l]);
      expect([l, html.includes('data-testid="coverage-stats"')]).toEqual([l, true]);
      expect([l, html.includes('data-testid="shot-zones-figures"')]).toEqual([l, false]);
      expect([l, html.includes('data-testid="match-balance-badge"')]).toEqual([l, false]);
      expect([l, html.includes("Estadísticas del partido")]).toEqual([l, false]);
      expect([l, html.includes("Mejores valorados")]).toEqual([l, false]);
      expect([l, html.match(/data-testid="unavailable-notes"/g)?.length]).toEqual([l, 1]);
      expect([l, html.includes("estadísticas de partido")]).toEqual([l, true]);
      // the events are at A in both: the facts of the match sheet and the score's strip stay
      expect([l, html.includes("Hechos del acta")]).toEqual([l, true]);
    }
  });
});
