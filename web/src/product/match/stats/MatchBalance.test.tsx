/// <reference types="bun" />
/**
 * Plan PM, PM-10-02 (OP-25, lámina I01 «M04»; FE-006): the balance of the match and the strip of the score's state. The ficha's
 * three cases: a complete match, a match without statistics (the strip alone, as in level C), and one that went to extra time (the
 * strip is the 90 minutes and says so). The balance says «dominio aproximado; no es field tilt»; each figure has its sample and origin.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { reviewProblems } from "@/components/analytics/evidence";
import type { MatchEvent, TeamStatLine } from "@/lib/api/v1/types_center";
import { setLocale } from "@/lib/i18n";
import { MATCH_BALANCE_REVIEW, balanceRows, pairShare, scoreState } from "./balance";
import { BalanceCard, ScoreStateCard } from "./MatchBalance";

setLocale("es");
afterEach(() => setLocale("es"));

function line(side: "home" | "away", over: Partial<TeamStatLine> = {}): TeamStatLine {
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
    fetched_at: "2026-11-16T22:00:00Z",
    ...over,
  };
}

function ev(
  seq: number,
  minute: number,
  side: "home" | "away",
  type = "Goal",
  detail = "Normal Goal",
  extra: number | null = null,
  comments: string | null = null,
): MatchEvent {
  return {
    seq,
    minute,
    extra_minute: extra,
    side,
    player: "X",
    player_id: seq,
    assist: null,
    type,
    detail,
    comments,
  };
}

// Lámina I01: 56–44 % possession, 16–9 shots, 10–4 in the box, 7–3 corners; goals 23' and 71' home, 58' away.
const LINES = [
  line("home", { possession_pct: "56", shots: 16, shots_inside_box: 10, corners: 7 }),
  line("away", { possession_pct: "44", shots: 9, shots_inside_box: 4, corners: 3 }),
];
const EVENTS = [
  ev(1, 23, "home"),
  ev(2, 58, "away"),
  ev(3, 71, "home"),
  ev(4, 30, "away", "Card", "Yellow Card"),
];
const TEAMS = { home: { name: "Cordillera" }, away: { name: "Altiplano" } };

describe("the balance (pure)", () => {
  test("lámina I01: four rows, each bar the side's share of the pair", () => {
    const rows = balanceRows(LINES)!;
    expect(rows.map((r) => r.key)).toEqual(["possession", "shots", "shotsInsideBox", "corners"]);
    expect(pairShare(rows[0]!, "home")).toBeCloseTo(56, 5);
    expect(pairShare(rows[3]!, "away")).toBeCloseTo(30, 5);
  });

  test("without statistics, or with one figure only, there is no balance", () => {
    expect(balanceRows([])).toBeNull();
    expect(balanceRows([line("home", { corners: 3 }), line("away", { corners: 2 })])).toBeNull();
    const zero = balanceRows([
      line("home", { corners: 0, shots: 4, possession_pct: "50" }),
      line("away", { corners: 0, shots: 2, possession_pct: "50" }),
    ])!;
    expect(zero.map((r) => r.key)).toEqual(["possession", "shots"]);
  });
});

describe("the strip (pure)", () => {
  test("a complete match: 54' ahead, 36' level, 0' behind (lámina I01)", () => {
    const s = scoreState(EVENTS, { home: 2, away: 1 })!;
    expect(s.drawing.kind).toBe("timeline");
    expect(s.drawing.minutes).toEqual({ home_ahead: 54, level: 36, away_ahead: 0 });
    expect(s.beyond90).toBe(false);
    expect(s.goals).toBe(3);
  });

  test("stoppage time counts as the 90th; events that do not add up draw nothing", () => {
    const s = scoreState([ev(1, 90, "away", "Goal", "Normal Goal", 4)], { home: 0, away: 1 })!;
    expect(s.drawing.minutes).toEqual({ home_ahead: 0, level: 90, away_ahead: 0 });
    expect(scoreState([ev(1, 10, "home")], { home: 2, away: 0 })).toBeNull();
    expect(scoreState(null, { home: 0, away: 0 })).toBeNull();
  });

  test("with extra time: the 90 minutes, the goal of the 105th and the shoot-out left out, and said", () => {
    const events = [
      ev(1, 40, "home"),
      ev(2, 80, "away"),
      ev(3, 105, "home"),
      ev(4, 120, "away", "Goal", "Penalty", null, "Penalty Shootout"),
    ];
    const s = scoreState(events, { home: 2, away: 1 }, true)!;
    expect(s.drawing.minutes).toEqual({ home_ahead: 40, level: 50, away_ahead: 0 });
    expect(s.beyond90).toBe(true);
  });

  test("a goalless match is level for 90 minutes", () => {
    expect(
      scoreState([ev(1, 30, "home", "Card", "Yellow Card")], { home: 0, away: 0 })?.drawing.minutes,
    ).toEqual({
      home_ahead: 0,
      level: 90,
      away_ahead: 0,
    });
  });
});

describe("the cards", () => {
  test("the balance: «dominio aproximado; no es field tilt», sample and origin, E1, ficha and table", () => {
    const html = renderToStaticMarkup(
      <BalanceCard rows={balanceRows(LINES)!} teams={TEAMS} source="estadísticas del partido" />,
    );
    expect(html).toContain("Balanza del partido");
    expect(html).toContain("Dominio aproximado; no es field tilt");
    expect(html).toContain("No mide en qué zona del campo se jugó");
    expect(html).toContain('data-evidence="E1"');
    expect(html).toContain('data-review="completa"');
    expect(html).toContain("Fuente: estadísticas del partido · 1 partido.");
    for (const s of ["Posesión", "Remates en el área", "Córners", "Ver como tabla"]) {
      expect(html).toContain(s);
    }
    expect(html).toMatch(/56\s%/);
    expect(html).toMatch(/44\s%/);
  });

  test("the strip: the three states with their minutes, a zero included, and the source", () => {
    const html = renderToStaticMarkup(
      <ScoreStateCard state={scoreState(EVENTS, { home: 2, away: 1 })!} teams={TEAMS} />,
    );
    expect(html).toContain("Estado del marcador");
    expect(html).toContain("Cordillera por delante");
    expect(html).toContain("54 min");
    expect(html).toContain("36 min");
    expect(html).toContain("0 min");
    expect(html).toContain('data-testid="knowledge-bar"');
    expect(html).toContain("1 partido; eventos del partido");
    expect(html).not.toContain("score-state-beyond90");
  });

  test("with extra time the strip says what it leaves out; in English", () => {
    setLocale("en");
    const events = [ev(1, 40, "home"), ev(2, 80, "away"), ev(3, 105, "home")];
    const html = renderToStaticMarkup(
      <ScoreStateCard state={scoreState(events, { home: 2, away: 1 }, true)!} teams={TEAMS} />,
    );
    expect(html).toContain("State of the score");
    expect(html).toContain("extra time and penalties are not drawn");
  });

  test("the review is complete", () => {
    expect(reviewProblems(MATCH_BALANCE_REVIEW)).toEqual([]);
  });
});
