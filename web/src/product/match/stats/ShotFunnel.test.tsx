/// <reference types="bun" />
/**
 * Plan PM, PM-10-01 (OP-22, lámina I01 «M01»; FE-005): the shot funnel and the two shot zones. Every figure carries its sample (one
 * match) and its origin; the funnel narrows or is not drawn; own goals and shoot-out kicks are not shots of the team; the zones say
 * they are two and not a map; the same figures are in a table; nothing is drawn while the switch is off or C-16 says the team
 * statistics are under B.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { reviewProblems } from "@/components/analytics/evidence";
import type { BlockAvailability } from "@/lib/api/v1/types_availability";
import type { MatchEvent, TeamStatLine } from "@/lib/api/v1/types_center";
import { setLocale } from "@/lib/i18n";
import { blockAllows } from "./coverage";
import { ShotFunnelCard, ShotZonesCard } from "./ShotFunnel";
import {
  SHOT_FUNNEL_REVIEW,
  funnelGoals,
  share,
  shotFunnel,
  shotZones,
  statSource,
  xgPerShot,
} from "./shots";

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
    source: "api-football",
    ...over,
  };
}

// Lámina I01: Cordillera 16 shots, 6 on target, 2 goals, 10 inside, 6 outside; Altiplano 9, 3, 1, 4, 5.
const LINES: TeamStatLine[] = [
  line("home", {
    shots: 16,
    shots_on_target: 6,
    shots_blocked: 4,
    shots_inside_box: 10,
    shots_outside_box: 6,
    expected_goals: "1.84",
  }),
  line("away", {
    shots: 9,
    shots_on_target: 3,
    shots_blocked: 2,
    shots_inside_box: 4,
    shots_outside_box: 5,
    expected_goals: "0.71",
  }),
];

function goal(
  seq: number,
  minute: number,
  side: "home" | "away",
  detail = "Normal Goal",
  comments: string | null = null,
): MatchEvent {
  return {
    seq,
    minute,
    extra_minute: null,
    side,
    player: "X",
    player_id: seq,
    assist: null,
    type: "Goal",
    detail,
    comments,
  };
}

const EVENTS = [goal(1, 23, "home"), goal(2, 58, "away"), goal(3, 71, "home")];
const TEAMS = { home: { name: "Atlético Cordillera" }, away: { name: "Real Altiplano" } };
const SOURCE = "estadísticas del partido";

describe("the funnel (pure)", () => {
  test("lámina I01: 16 · 6 · 2 against 9 · 3 · 1, goals from the events", () => {
    const f = shotFunnel(LINES, EVENTS, { home: 2, away: 1 });
    expect(f).toEqual({
      home: { shots: 16, onTarget: 6, goals: 2 },
      away: { shots: 9, onTarget: 3, goals: 1 },
      goalsFrom: "events",
      ownGoals: { home: 0, away: 0 },
    });
    expect(share(6, 16)).toBe(38);
    expect(share(2, 16)).toBe(13);
    expect(share(1, 9)).toBe(11);
    expect(share(3, 0)).toBeNull();
  });

  test("an own goal is not the team's shot; a shoot-out kick is not a shot at all", () => {
    const own = goal(4, 80, "away", "Own Goal");
    const kick = goal(5, 120, "home", "Penalty", "Penalty Shootout");
    const g = funnelGoals([...EVENTS, own, kick], { home: 3, away: 1 });
    expect(g?.from).toBe("events");
    expect(g?.goals).toEqual({ home: 2, away: 1 });
    expect(g?.ownGoals).toEqual({ home: 1, away: 0 });
  });

  test("events that do not add up to the score: the score, said", () => {
    const g = funnelGoals([goal(1, 10, "home")], { home: 2, away: 1 });
    expect(g).toEqual({
      goals: { home: 2, away: 1 },
      from: "score",
      ownGoals: { home: 0, away: 0 },
    });
    expect(funnelGoals(null, null)).toBeNull();
  });

  test("a funnel that does not narrow, or a side without the figure, is not drawn", () => {
    expect(
      shotFunnel([LINES[0]!, line("away", { shots: 9 })], EVENTS, { home: 2, away: 1 }),
    ).toBeNull();
    const wide = [LINES[0]!, line("away", { shots: 3, shots_on_target: 5 })];
    expect(shotFunnel(wide, EVENTS, { home: 2, away: 1 })).toBeNull();
    expect(shotFunnel(LINES, null, null)).toBeNull();
  });

  test("the two zones, and none when a side lacks them", () => {
    const z = shotZones(LINES);
    expect(z?.home).toEqual({ inside: 10, outside: 6, blocked: 4, xg: 1.84 });
    expect(z?.away.inside).toBe(4);
    expect(shotZones([LINES[0]!, line("away", { shots_inside_box: 4 })])).toBeNull();
    expect(xgPerShot(1.84, 16)).toBeCloseTo(0.115, 3);
    expect(xgPerShot(null, 16)).toBeNull();
    expect(statSource(LINES)).toBe("api_football");
    expect(statSource([line("home", { source: "football-data.co.uk" })])).toBe("football_data");
  });
});

describe("the cards", () => {
  const funnel = shotFunnel(LINES, EVENTS, { home: 2, away: 1 })!;
  const zones = shotZones(LINES)!;

  test("the funnel: its steps and shares, sample and origin, E1, the ficha and the table", () => {
    const html = renderToStaticMarkup(
      <ShotFunnelCard funnel={funnel} teams={TEAMS} source={SOURCE} />,
    );
    expect(html).toContain("Embudo de remate");
    expect(html).toContain('data-evidence="E1"');
    expect(html).toContain('data-review="completa"');
    expect(html).toContain("1 partido; estadísticas del partido");
    expect(html).toContain("Fuente: estadísticas del partido · 1 partido.");
    for (const s of ["Remates", "A puerta", "Goles", "100 %", "38 %", "13 %", "33 %", "11 %"]) {
      expect(html).toContain(s);
    }
    expect(html).toContain("Ver como tabla");
    expect(html).toContain("<table");
    expect(html).toContain("6 (38 %)");
    expect(html).toContain("Atlético Cordillera: 16 remates, 6 a puerta, 2 goles");
    expect(html).not.toContain("shot-funnel-own-goals");
    expect(html).not.toContain("shot-funnel-from-score");
  });

  test("the zones: «2 zonas», not a map, blocked shots and the provider's xG", () => {
    const html = renderToStaticMarkup(
      <ShotZonesCard zones={zones} teams={TEAMS} source={SOURCE} shots={{ home: 16, away: 9 }} />,
    );
    expect(html).toContain("Zona de remate · 2 zonas");
    expect(html).toContain("No es un mapa de tiros");
    expect(html).toContain("xG según los datos del partido.");
    expect(html).toContain("dentro · 63 %");
    expect(html).toContain("fuera · 38 %");
    expect(html).toContain("dentro · 44 %");
    expect(html).toContain("fuera · 56 %");
    expect(html).toContain("Remates bloqueados");
    expect(html).toContain("1,84");
    expect(html).toContain("0,12");
    expect(html).toContain("0,08");
    expect(html).toContain('data-evidence="E1"');
  });

  test("without xG or blocked shots the rows are not drawn, never a zero", () => {
    const bare = shotZones([
      line("home", { shots_inside_box: 3, shots_outside_box: 2 }),
      line("away", { shots_inside_box: 1, shots_outside_box: 1 }),
    ])!;
    const html = renderToStaticMarkup(<ShotZonesCard zones={bare} teams={TEAMS} source={SOURCE} />);
    expect(html).not.toContain("shot-zones-figures");
    expect(html).not.toContain("xG");
  });

  test("in English", () => {
    setLocale("en");
    const html = renderToStaticMarkup(
      <ShotFunnelCard funnel={funnel} teams={TEAMS} source="match statistics" />,
    );
    expect(html).toContain("Shot funnel");
    expect(html).toContain("On target");
    expect(html).toContain("Show as a table");
  });

  test("the review is complete (the notes use muted-foreground, AA on a card: Unavailable.test.tsx)", () => {
    expect(reviewProblems(SHOT_FUNNEL_REVIEW)).toEqual([]);
  });
});

describe("C-16 decides: level B or better", () => {
  const block = (level: "A" | "B" | "C" | "D", exists = true): BlockAvailability => ({
    key: "team_stats",
    exists,
    level,
    n: 120,
    provisional: false,
    reason: "ninguno",
  });
  test("A and B draw; C and D do not; nothing said leaves it to the data", () => {
    expect(blockAllows([block("A")], "team_stats")).toBe(true);
    expect(blockAllows([block("B")], "team_stats")).toBe(true);
    expect(blockAllows([block("C")], "team_stats")).toBe(false);
    expect(blockAllows([block("D")], "team_stats")).toBe(false);
    expect(blockAllows([block("A", false)], "team_stats")).toBe(false);
    expect(blockAllows(null, "team_stats")).toBeNull();
    expect(blockAllows([block("A")], "xg")).toBeNull();
    expect(blockAllows([{ ...block("A"), reason: "sin_medir" }], "team_stats")).toBeNull();
  });
});
