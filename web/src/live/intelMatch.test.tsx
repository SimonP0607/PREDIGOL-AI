/// <reference types="bun" />
/**
 * PLAN F6 in the Admin Console: the dossier's picker and the AI's side of a match. What is held here:
 *
 * - a search is worth sending from two characters, or when it is a match id; the picker says whether the AI studied a
 *   match, how much research its brief asked for and whether it escalated;
 * - the weighted head-to-head, the scenarios of a table and a tie, the tactics and the status of each context factor
 *   read as the server states them - every figure with the size of its sample, a missing one as a dash, never a zero;
 * - a factor that the registry changed after the packet shows as changed; DESCRIPTIVE and VALIDATED are two words, in
 *   both languages;
 * - the research the AI asked for is listed with its reason, each pass says what it did about it and why a request
 *   was left unserved, and a claim refused for resting on a descriptive factor names the factor;
 * - every dynamic text key (a status, a topic, a reason, a group) exists in Spanish and English.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import type {
  IntelBrief,
  IntelFactorRow,
  IntelFactorsBlock,
  IntelH2hBlock,
  IntelPass,
  IntelPicker,
  IntelPickerRow,
  IntelScenarioTable,
  IntelScenarioTie,
  IntelScenariosBlock,
  IntelTacticsBlock,
  IntelTacticsProfile,
} from "@/lib/api/v1/types_intel";
import { BriefPanel, RefusedPanel, ResearchPanel } from "./IntelAiPanels";
import { FactorsBody, H2hPanel, ScenariosPanel, TacticsPanel } from "./IntelMatchPanels";
import { PickerResults } from "./IntelMatchPicker";
import {
  DASH,
  ageText,
  askLines,
  briefFlags,
  canSearch,
  factorLines,
  h2hView,
  hasScenarios,
  marginText,
  passLines,
  pickerBadges,
  pickerParams,
  placesText,
  refusedGroupLabel,
  refusedLines,
  searchText,
  tableView,
  tacticsRows,
  tieView,
  unservedText,
} from "./intelMatch";

afterEach(() => setLocale("es"));

/** Text of rendered markup with the spaces (and the no-break spaces of a percentage) made plain. */
const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
const plain = (s: string) => s.replace(/\s+/g, " ");

// ── the picker ───────────────────────────────────────────────────────────────

function row(over: Partial<IntelPickerRow> = {}): IntelPickerRow {
  return {
    fixture_id: 1,
    kickoff_at: "2026-10-22T23:00:00Z",
    status_short: "NS",
    home: "Alpha",
    away: "Beta",
    competition: "Liga",
    country: "Colombia",
    packet_as_of: "2026-10-22T05:05:00Z",
    brief_pass: "first",
    brief_escalate: false,
    research_asked: 0,
    ...over,
  };
}

describe("the picker's search", () => {
  test("spaces are collapsed and the text is cut at the 60 characters the server accepts", () => {
    expect(searchText("  real   madrid ")).toBe("real madrid");
    expect(searchText("x".repeat(80))).toHaveLength(60);
  });

  test("two characters or a match id are worth sending; one letter is not", () => {
    expect(canSearch("m")).toBe(false);
    expect(canSearch("  ")).toBe(false);
    expect(canSearch("re")).toBe(true);
    expect(canSearch("7")).toBe(true);
    expect(canSearch("123456")).toBe(true);
    expect(canSearch("a ")).toBe(false);
  });

  test("the query carries the day, and the text only when it can search", () => {
    expect(pickerParams("m", "2026-10-22")).toEqual({ day: "2026-10-22", q: undefined });
    expect(pickerParams(" real  madrid", undefined)).toEqual({ day: undefined, q: "real madrid" });
    expect(pickerParams("", undefined)).toEqual({ day: undefined, q: undefined });
  });
});

describe("what the picker says about a match", () => {
  test("a match the AI never studied says so, and nothing more", () => {
    const b = pickerBadges(row({ packet_as_of: null, brief_pass: null, brief_escalate: null }));
    expect(b.map((x) => x.key)).toEqual(["unstudied"]);
    expect(b[0]?.text).toBe("sin paquete");
  });

  test("a studied match says how much research its brief asked for and whether it escalated", () => {
    const b = pickerBadges(row({ research_asked: 2, brief_escalate: true }));
    expect(b.map((x) => x.key)).toEqual(["studied", "research", "escalated"]);
    expect(b.map((x) => x.text)).toEqual(["con paquete", "2 investigaciones pedidas", "escalado"]);
    expect(pickerBadges(row({ research_asked: 1 }))[1]?.text).toBe("1 investigación pedida");
  });

  test("in English", () => {
    setLocale("en");
    const b = pickerBadges(row({ research_asked: 1, brief_escalate: true }));
    expect(b.map((x) => x.text)).toEqual(["has packet", "1 research asked", "escalated"]);
  });
});

describe("PickerResults", () => {
  const day = (over: Partial<IntelPicker> = {}): IntelPicker => ({
    mode: "day",
    day: "2026-10-22",
    q: null,
    total: 3,
    with_packet: 1,
    matches: [
      row({ fixture_id: 7, research_asked: 1 }),
      row({ fixture_id: 8, packet_as_of: null }),
    ],
    ...over,
  });

  test("the day: the count, each match with its words, and the one being shown is pressed", () => {
    const html = renderToStaticMarkup(
      <PickerResults d={day()} fixture="8" onPick={() => undefined} />,
    );
    const t = text(html);
    expect(t).toContain("3 partidos del día · 1 con paquete de la IA");
    expect(t).toContain("Se muestran los primeros 2 de 3.");
    expect(t).toContain("Alpha - Beta");
    expect(t).toContain("1 investigación pedida");
    expect(t).toContain("sin paquete");
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1);
    expect(html.match(/data-testid="intel-picker-row"/g)).toHaveLength(2);
  });

  test("a search: the count names the text and the day, and an empty answer says so", () => {
    const found = text(
      renderToStaticMarkup(
        <PickerResults
          d={day({ mode: "search", q: "alpha", total: 1, matches: [row()] })}
          fixture=""
          onPick={() => undefined}
        />,
      ),
    );
    expect(found).toContain("1 partido para «alpha» a ±45 días del");
    const none = text(
      renderToStaticMarkup(
        <PickerResults
          d={day({ mode: "search", q: "zzz", total: 0, matches: [] })}
          fixture=""
          onPick={() => undefined}
        />,
      ),
    );
    expect(none).toContain("Ningún partido.");
  });
});

// ── time ─────────────────────────────────────────────────────────────────────

describe("ageText", () => {
  test("days, months and years, each in its own unit", () => {
    expect(ageText(1)).toBe("1 día");
    expect(ageText(12)).toBe("12 días");
    expect(ageText(365)).toBe("12 meses");
    expect(ageText(800)).toBe("2,2 años");
    expect(ageText(null)).toBe(DASH);
    expect(ageText(undefined)).toBe(DASH);
  });

  test("in English", () => {
    setLocale("en");
    expect(ageText(1)).toBe("1 day");
    expect(ageText(100)).toBe("3 months");
    expect(ageText(800)).toBe("2.2 years");
  });
});

// ── the weighted head-to-head ────────────────────────────────────────────────

const H2H: IntelH2hBlock = {
  version: "h2h-v2",
  status: "DESCRIPTIVE",
  n: 3,
  n_effective: 2.6,
  last_days_ago: 40,
  oldest_days_ago: 900,
  relevance: "media",
  note: "el historial directo pesa poco frente a la forma y el mercado",
  record: { n: 3, home_side_wins: 2, draws: 0, away_side_wins: 1 },
  weighted: {
    home_side_win: 0.75,
    draw: 0,
    away_side_win: 0.25,
    goals_home_side_pg: 1.6,
    goals_away_side_pg: 0.8,
  },
  same_venue: { n: 2, home_side_wins: 1, draws: 0, away_side_wins: 1 },
  coaches: { both_same: 1, some_changed: 1, unknown: 1 },
  meetings: [
    {
      fixture_id: 11,
      days_ago: 40,
      competition: "Liga",
      scope: "same_competition",
      home_side_was: "home",
      goals_home_side: 2,
      goals_away_side: 1,
      after_extra_time: false,
      coach_changed: { home: false, away: false },
      weight: 0.8,
    },
    {
      fixture_id: 12,
      days_ago: 400,
      competition: "Copa",
      scope: "same_kind",
      home_side_was: "away",
      goals_home_side: 0,
      goals_away_side: 1,
      after_extra_time: false,
      coach_changed: { home: true, away: null },
      weight: 0.4,
    },
    {
      fixture_id: 13,
      days_ago: 900,
      competition: "Amistoso",
      scope: "friendly",
      home_side_was: "neutral",
      goals_home_side: 3,
      goals_away_side: 1,
      after_extra_time: true,
      coach_changed: { home: null, away: null },
      weight: 0.4,
    },
  ],
  weights_note: "Pesos fijos y redondos, no ajustados a ningún dato.",
};

describe("h2hView", () => {
  test("the record, the weighted shares, the coaches and each meeting with its weight and its share of all of them", () => {
    const v = h2hView(H2H);
    expect(v.n).toBe(3);
    expect(v.nEffective).toBe("2,6");
    expect(v.lastAgo).toBe("40 días");
    expect(v.oldestAgo).toBe("2,5 años");
    expect(v.record).toBe("2 G · 0 E · 1 P");
    expect(v.sameVenue).toBe("1 G · 0 E · 1 P");
    expect(plain(v.weighted ?? "")).toBe("75 % · 0 % · 25 %");
    expect(v.goalsPerMeeting).toBe("1,60 – 0,80");
    expect(v.coaches).toBe("1 iguales · 1 con cambio · 1 sin dato");
    expect(v.meetings.map((m) => m.weight)).toEqual(["0,80", "0,40", "0,40"]);
    expect(v.meetings.map((m) => plain(m.share))).toEqual(["50 %", "25 %", "25 %"]);
    expect(v.meetings.map((m) => m.score)).toEqual(["2–1", "0–1", "3–1"]);
    expect(v.meetings.map((m) => m.coaches)).toEqual(["los mismos", "cambió el local", "sin dato"]);
    expect(v.meetings[0]?.scope).toBe("misma competición");
    expect(v.meetings[1]?.ground).toBe("el local jugó fuera");
    expect(v.meetings[2]?.afterExtraTime).toBe(true);
  });

  test("with no meetings nothing is invented: dashes, no table", () => {
    const v = h2hView({
      version: "h2h-v2",
      status: "DESCRIPTIVE",
      n: 0,
      n_effective: 0,
      last_days_ago: null,
      relevance: "nula",
      note: "n",
    });
    expect(v.record).toBeNull();
    expect(v.weighted).toBeNull();
    expect(v.coaches).toBeNull();
    expect(v.lastAgo).toBe(DASH);
    expect(v.meetings).toEqual([]);
  });

  test("the panel: a descriptive status, the figures, the table and the server's own caution", () => {
    const html = renderToStaticMarkup(<H2hPanel block={H2H} home="Alpha" away="Beta" />);
    const t = plain(text(html));
    expect(t).toContain("Cara a cara ponderado");
    expect(t).toContain("Descriptivo");
    expect(t).toContain("Registro a 90 min · Alpha");
    expect(t).toContain("2 G · 0 E · 1 P");
    expect(t).toContain("75 % · 0 % · 25 %");
    expect(t).toContain("misma competición");
    expect(t).toContain("(prórroga)");
    expect(t).toContain("Pesos fijos y redondos, no ajustados a ningún dato.");
    expect(html).toContain('data-testid="intel-h2h-weighted"');
  });
});

// ── what the match does to its table and its tie ────────────────────────────

const side = (points: number, best: number, worst: number, zone: string | null = null) => ({
  points,
  rank_best: best,
  rank_worst: worst,
  zones: [{ description: zone, kind: zone ? "promotion" : null }],
});

const TABLE: IntelScenarioTable = {
  version: "scenarios-v1",
  basis: "this_match_alone",
  group: "Grupo A",
  snapshot_at: "2026-10-22T10:00:00Z",
  teams: 4,
  home: { team_id: 1, rank_now: 3, points_now: 10, played: 6, zone_now: "Ascenso" },
  away: { team_id: 2, rank_now: 1, points_now: 14, played: 6, zone_now: null },
  after: {
    home_win: { home: side(13, 1, 2, "Ascenso"), away: side(14, 1, 1) },
    draw: { home: side(11, 2, 3), away: side(15, 1, 1) },
    away_win: { home: side(10, 3, 4), away: side(17, 1, 1) },
  },
};

const TIE: IntelScenarioTie = {
  version: "scenarios-v1",
  kind: "second_leg",
  aggregate_before: { home_side: 1, away_side: 0 },
  lead_home_side: 1,
  margin: "goles del equipo menos goles del rival en ESTE partido, en 90 minutos",
  home_side: {
    ahead_if_margin_at_least: 0,
    level_if_margin: -1,
    behind_if_margin_at_most: -2,
    can_lose_by_up_to: 0,
    needs_to_win_by_at_least: null,
  },
  away_side: {
    ahead_if_margin_at_least: 2,
    level_if_margin: 1,
    behind_if_margin_at_most: 0,
    can_lose_by_up_to: null,
    needs_to_win_by_at_least: 2,
  },
  if_level: "competition_rules",
};

const SCENARIOS: IntelScenariosBlock = {
  version: "scenarios-v1",
  status: "DESCRIPTIVE",
  table: TABLE,
  tie: TIE,
  note: "Lecturas aritméticas de ESTE partido solo.",
};

describe("scenarios", () => {
  test("places are an interval unless it is one place", () => {
    expect(placesText(3, 3)).toBe("puesto 3");
    expect(placesText(1, 2)).toBe("puestos 1–2");
  });

  test("the table: where each side is now and where each result leaves it, with the zones", () => {
    const v = tableView(TABLE);
    expect(v.unavailable).toBe(false);
    expect(v.group).toBe("Grupo A");
    expect(v.home).toBe("3.º · 10 pts · 6 PJ · Ascenso");
    expect(v.away).toBe("1.º · 14 pts · 6 PJ");
    expect(v.rows.map((r) => r.result)).toEqual(["home_win", "draw", "away_win"]);
    expect(v.rows[0]).toEqual({
      result: "home_win",
      home: "13 pts · puestos 1–2 · Ascenso",
      away: "14 pts · puesto 1",
    });
  });

  test("a table that is not ordered by its points says nothing", () => {
    const v = tableView({
      version: "scenarios-v1",
      group: null,
      snapshot_at: null,
      unavailable: "rank_not_by_points",
    });
    expect(v.unavailable).toBe(true);
    expect(v.rows).toEqual([]);
    expect(v.home).toBeNull();
  });

  test("margins carry their sign", () => {
    expect(marginText(2)).toBe("+2");
    expect(marginText(0)).toBe("0");
    expect(marginText(-1)).toBe("−1");
  });

  test("a second leg: the aggregate before, and what each side needs in the 90 minutes", () => {
    const v = tieView(TIE);
    expect(v.kindLabel).toBe("vuelta");
    expect(v.before).toBe("1–0");
    expect(v.sides).toEqual([
      { side: "home", ahead: "≥ 0", level: "−1", behind: "≤ −2", limit: "no puede perder" },
      {
        side: "away",
        ahead: "≥ +2",
        level: "+1",
        behind: "≤ 0",
        limit: "necesita ganar por 2 o más",
      },
    ]);
    expect(
      tieView({
        ...TIE,
        home_side: { ...TIE.home_side!, can_lose_by_up_to: 2, ahead_if_margin_at_least: -1 },
      }).sides[0]?.limit,
    ).toBe("puede perder por hasta 2");
  });

  test("a tie that cannot be read keeps the server's own words; a series says the game and the wins", () => {
    const unknown = tieView({
      version: "scenarios-v1",
      kind: "second_leg",
      aggregate: "unknown",
      note: "falta el resultado de la ida",
    });
    expect(unknown.note).toBe("falta el resultado de la ida");
    expect(unknown.sides).toEqual([]);
    const series = tieView({
      version: "scenarios-v1",
      kind: "series",
      game: 3,
      wins_home_side: 1,
      wins_away_side: 1,
      draws: 0,
    });
    expect(series.kindLabel).toBe("serie");
    expect(series.series).toBe("juego 3 · 1–1 (0 empates)");
  });

  test("a block with neither a table nor a tie has nothing to show", () => {
    expect(hasScenarios(null)).toBe(false);
    expect(hasScenarios({ ...SCENARIOS, table: null, tie: null })).toBe(false);
    expect(hasScenarios(SCENARIOS)).toBe(true);
  });

  test("the panel", () => {
    const html = renderToStaticMarkup(
      <ScenariosPanel block={SCENARIOS} home="Alpha" away="Beta" />,
    );
    const t = plain(text(html));
    expect(t).toContain("Escenarios de este partido");
    expect(t).toContain("Tabla · Grupo A");
    expect(t).toContain("Si gana el local");
    expect(t).toContain("13 pts · puestos 1–2 · Ascenso");
    expect(t).toContain("Eliminatoria · vuelta");
    expect(t).toContain("no puede perder");
    expect(t).toContain("Lecturas aritméticas de ESTE partido solo.");
    expect(html).toContain('data-testid="intel-tie"');
    // Phone: no table whose right-hand column waits beyond the edge. Every line is a term and one cell per side, and
    // each cell names its side so that it reads alone (a phone has no header, a screen reader none at any width).
    expect(html).not.toContain("<table");
    expect(html.match(/<dt/g)?.length).toBe(8);
    expect(html.match(/<dd/g)?.length).toBe(16);
    expect(html.match(/>Alpha</g)?.length).toBeGreaterThanOrEqual(8);
    expect(html.match(/>Beta</g)?.length).toBeGreaterThanOrEqual(8);
  });
});

// ── the observable tactics ───────────────────────────────────────────────────

const FULL: IntelTacticsProfile = {
  team_id: 1,
  n: 10,
  data: {
    sheets: { none: 1, crossed: 2, without_formation: 0, without_the_eleven: 1 },
    events: { none: 1, inconsistent: 0 },
  },
  formations: { n: 7, main: "4-3-3", main_count: 5, last: "4-2-3-1", distinct: 3, changes: 2 },
  starters: { n: 6, pairs: 5, avg_changes: 2.4 },
  coach: { n: 7, distinct: 2, newest_matches: 5 },
  goals: {
    n: 8,
    total_for: 12,
    total_against: 7,
    late: { for: 4, against: 1, matches_for: 3, matches_against: 1 },
  },
  with_the_score: {
    n: 8,
    half_time: {
      n: 9,
      leading: { n: 4, wins: 3, draws: 1, losses: 0 },
      level: { n: 3, wins: 1, draws: 1, losses: 1 },
      trailing: { n: 2, wins: 0, draws: 0, losses: 2 },
    },
    scored_first: { n: 5, wins: 4, draws: 1, losses: 0 },
    conceded_first: { n: 3, wins: 0, draws: 1, losses: 2 },
    goalless: 1,
  },
  substitutions: {
    n: 8,
    with_substitutions: 7,
    per_match: 3.1,
    first_minute: { mean: 61.4, median: 62 },
  },
};
const NOTHING: IntelTacticsProfile = { team_id: 2, n: 0 };
const TACTICS: IntelTacticsBlock = {
  version: "tactics-v1",
  status: "DESCRIPTIVE",
  note: "Lo observable de los últimos partidos de cada equipo.",
  home: FULL,
  away: NOTHING,
};

describe("tacticsRows", () => {
  test("every figure carries the size of its sample", () => {
    const rows = Object.fromEntries(tacticsRows(FULL, NOTHING).map((r) => [r.key, r]));
    expect(rows["read"]?.home).toBe("8 de 10");
    expect(rows["data"]?.home).toBe("1 sin hoja · 2 hojas cruzadas · 1 sin eventos");
    expect(rows["formation"]?.home).toBe("4-3-3 en 5 de 7 · última 4-2-3-1 · 2 cambios");
    expect(rows["rotation"]?.home).toBe("2,4 cambios por partido (5 pares)");
    expect(rows["coach"]?.home).toBe("5 de 7 (2 distintos)");
    expect(rows["goals"]?.home).toBe("12 – 7 (8 partidos)");
    expect(rows["late"]?.home).toBe("4 – 1 (8 partidos)");
    expect(rows["scoredFirst"]?.home).toBe("4 G 1 E 0 P (5)");
    expect(rows["concededFirst"]?.home).toBe("0 G 1 E 2 P (3)");
    expect(rows["htLeading"]?.home).toBe("3 G 1 E 0 P (4)");
    expect(rows["htTrailing"]?.home).toBe("0 G 0 E 2 P (2)");
    expect(rows["firstSub"]?.home).toBe("61,4 (7 de 8 partidos)");
  });

  test("a team with nothing read shows dashes, never zeros", () => {
    const rows = tacticsRows(FULL, NOTHING);
    for (const r of rows) {
      if (r.key === "read") expect(r.away).toBe("0 de 0");
      else expect(r.away).toBe(DASH);
    }
  });

  test("complete data says so", () => {
    const rows = tacticsRows(
      {
        ...FULL,
        data: {
          sheets: { none: 0, crossed: 0, without_formation: 0, without_the_eleven: 0 },
          events: { none: 0, inconsistent: 0 },
        },
      },
      NOTHING,
    );
    expect(rows.find((r) => r.key === "data")?.home).toBe("completos");
  });

  test("the panel", () => {
    const html = renderToStaticMarkup(<TacticsPanel block={TACTICS} home="Alpha" away="Beta" />);
    const t = plain(text(html));
    expect(t).toContain("Táctica observable");
    expect(t).toContain("Descriptivo");
    expect(t).toContain("Si marca primero");
    expect(t).toContain("4 G 1 E 0 P (5)");
    expect(t).toContain("Lo observable de los últimos partidos de cada equipo.");
    expect(html).not.toContain("<table");
    expect(html.match(/<dt/g)?.length).toBe(12);
    expect(html.match(/<dd/g)?.length).toBe(24);
  });
});

// ── the status of each context factor ────────────────────────────────────────

const FACTORS: IntelFactorsBlock = {
  version: "factors-v1",
  note: "Estado de cada factor de contexto del paquete.",
  h2h_weighted: { version: "h2h-v2", block: "h2h", status: "DESCRIPTIVE", decision: null },
  scenarios: {
    version: "scenarios-v1",
    block: "scenarios",
    status: "VALIDATED",
    decision: { id: 5, decided_at: "2026-10-01T00:00:00Z", experiment: "scen-x" },
  },
  tactics_profile: {
    version: "tactics-v1",
    block: "dossier.tactics",
    status: "DESCRIPTIVE",
    decision: null,
  },
};

const REGISTRY: IntelFactorRow[] = [
  {
    key: "h2h_weighted",
    label: "Cara a cara ponderado",
    claim: "que el historial predice",
    version: "h2h-v2",
    block: "h2h",
    status: "VALIDATED",
    decision: { id: 7, decided_at: "2026-10-20T12:00:00Z", experiment: "h2h-vs-form" },
    decisions: [
      {
        id: 7,
        version: "h2h-v2",
        status: "VALIDATED",
        decided_at: "2026-10-20T12:00:00Z",
        decided_by: "owner",
        who: "Simon",
        reason: "mejora el Brier en walk-forward",
        experiment: "h2h-vs-form",
        previous_id: null,
      },
    ],
  },
  {
    key: "scenarios",
    label: "Escenarios",
    claim: "que los escenarios cambian el resultado",
    version: "scenarios-v1",
    block: "scenarios",
    status: "DESCRIPTIVE",
    decision: null,
    decisions: [
      {
        id: 6,
        version: "scenarios-v1",
        status: "DESCRIPTIVE",
        decided_at: "2026-10-10T12:00:00Z",
        decided_by: "owner",
        who: "Simon",
        reason: "el experimento no se confirmó",
        experiment: null,
        previous_id: 5,
      },
    ],
  },
];

describe("factorLines", () => {
  test("the packet's factors beside the registry today: a change after the packet shows, an unknown today is not a change", () => {
    const lines = Object.fromEntries(factorLines(FACTORS, REGISTRY).map((l) => [l.key, l]));
    expect(lines["h2h_weighted"]).toMatchObject({
      packet: "DESCRIPTIVE",
      today: "VALIDATED",
      changed: true,
      experiment: null,
    });
    expect(lines["scenarios"]).toMatchObject({
      packet: "VALIDATED",
      today: "DESCRIPTIVE",
      changed: true,
      experiment: "scen-x",
    });
    expect(lines["tactics_profile"]?.today).toBeUndefined();
    expect(lines["tactics_profile"]?.changed).toBe(false);
    expect(factorLines(FACTORS, undefined).every((l) => !l.changed)).toBe(true);
  });

  test("the keys of the block that are not factors are skipped, and so is a missing block", () => {
    expect(factorLines(FACTORS, undefined).map((l) => l.key)).toEqual([
      "h2h_weighted",
      "scenarios",
      "tactics_profile",
    ]);
    expect(factorLines(null, REGISTRY)).toEqual([]);
  });

  test("the names are the owner's words in either language", () => {
    expect(factorLines(FACTORS, undefined)[0]?.name).toBe("Cara a cara ponderado");
    setLocale("en");
    expect(factorLines(FACTORS, undefined)[0]?.name).toBe("Weighted head to head");
  });
});

describe("FactorsBody", () => {
  test("statuses, the experiment, what changed since the packet and the decisions taken, newest first", () => {
    const html = renderToStaticMarkup(<FactorsBody block={FACTORS} registry={REGISTRY} loaded />);
    const t = plain(text(html));
    expect(t).toContain("Descriptivo");
    expect(t).toContain("Validado");
    expect(t).toContain("experimento: scen-x");
    expect(t).toContain("cambió después del paquete");
    expect(t).toContain("mejora el Brier en walk-forward");
    expect(t).toContain("el experimento no se confirmó");
    expect(t.indexOf("mejora el Brier")).toBeLessThan(t.indexOf("el experimento no se confirmó"));
    expect(html).toContain('data-testid="intel-factor-decisions"');
    // One term per factor and a cell for what it was in the packet and one for what it is today, each naming its column.
    expect(html).not.toContain("<table");
    expect(html.match(/<dt/g)?.length).toBe(3);
    expect(html.match(/<dd/g)?.length).toBe(6);
    expect(html.match(/>En el paquete</g)?.length).toBeGreaterThanOrEqual(3);
    expect(html.match(/>Hoy en el registro</g)?.length).toBeGreaterThanOrEqual(3);
  });

  test("a registry without decisions says every factor is still descriptive; one that failed to load says nothing", () => {
    const empty = renderToStaticMarkup(
      <FactorsBody
        block={FACTORS}
        registry={REGISTRY.map((f) => ({ ...f, decisions: [] }))}
        loaded
      />,
    );
    expect(text(empty)).toContain("todos los factores siguen descriptivos");
    const loading = renderToStaticMarkup(
      <FactorsBody block={FACTORS} registry={undefined} loaded={false} />,
    );
    expect(text(loading)).not.toContain("todos los factores siguen descriptivos");
    expect(text(loading)).toContain("Descriptivo");
  });

  test("a packet built while the registry could not be read says so", () => {
    const html = renderToStaticMarkup(
      <FactorsBody
        block={{ ...FACTORS, error: "registry unreadable" }}
        registry={undefined}
        loaded={false}
      />,
    );
    expect(text(html)).toContain("No se pudo leer el registro al armar el paquete");
  });
});

// ── what the AI asked, what the server did, what it refused ─────────────────

const BRIEF: IntelBrief = {
  id: 1,
  created_at: "2026-10-22T13:05:00Z",
  pass: "first",
  version: "brief-v8",
  engine: "llm",
  model: "claude-haiku-5-5",
  status: "ok",
  summary: "Un partido parejo.",
  escalate: true,
  reasons: ["important_news"],
  uncertainty: "medium",
  data_quality: "fair",
  cost_usd: 0.0123,
  research: [
    {
      topic: "availability",
      side: "both",
      why: { text: "No hay bajas en el paquete.", type: "DATA", refs: ["P:absences"] },
    },
    { topic: "preview", side: "home", why: { text: "Falta la previa." } },
  ],
  refused: [
    {
      group: "cards.why",
      text: "Ventaja por el cara a cara.",
      why: "rests on h2h_weighted, a DESCRIPTIVE factor: it describes the match, it does not justify a selection",
    },
    { group: "narrative.form", text: "Viene en racha.", why: "numbers not in the packet: 7" },
  ],
  refused_total: 2,
};

const pass = (over: Partial<IntelPass>): IntelPass => ({
  pass: "pre",
  day: "2026-10-22",
  status: "ok",
  started_at: "2026-10-22T17:00:00Z",
  finished_at: "2026-10-22T17:01:00Z",
  escalated: false,
  reasons: [],
  cost_usd: 0.01,
  note: null,
  research: { requested: 0, asked: 1, searched: 1, unserved: {}, web_searches: 2 },
  ...over,
});
const PASSES: IntelPass[] = [
  pass({
    pass: "final",
    finished_at: "2026-10-22T22:01:00Z",
    research: {
      requested: 0,
      asked: 1,
      searched: 0,
      unserved: { no_search_pass: 1 },
      web_searches: 0,
    },
  }),
  pass({}),
];

describe("the research the AI asked for", () => {
  test("each request with its topic, side and reason", () => {
    expect(askLines(BRIEF.research)).toEqual([
      {
        topic: "Quién puede jugar (bajas, dudas, sanciones)",
        side: "los dos",
        reason: "No hay bajas en el paquete.",
        refs: ["P:absences"],
      },
      {
        topic: "Previa de medios internacionales",
        side: "local",
        reason: "Falta la previa.",
        refs: [],
      },
    ]);
    expect(askLines(undefined)).toEqual([]);
  });

  test("a request left unserved says why, reason by reason", () => {
    expect(unservedText({})).toBe(DASH);
    expect(unservedText({ no_allowance: 1, near_budget: 2, pass_budget: 0 })).toBe(
      "cerca del presupuesto: 2 · sin búsquedas disponibles: 1",
    );
    expect(unservedText({ no_search_pass: 1 })).toBe("este pase no lee la web: 1");
    expect(unservedText({ research_failed: 1 })).toBe(
      "la investigación por entidad falló en este pase: 1",
    );
    expect(unservedText({ something_new: 3 })).toBe("something new: 3");
  });

  test("each pass: what it received, what it searched, what it left unserved", () => {
    const lines = passLines(PASSES);
    expect(lines.map((l) => l.pass)).toEqual(["final", "pre"]);
    expect(lines[0]).toMatchObject({
      asked: "1",
      searched: "0",
      unserved: "este pase no lee la web: 1",
    });
    expect(lines[1]).toMatchObject({ asked: "1", searched: "1", unserved: DASH, webSearches: "2" });
  });

  test("the panel: the request with its reason, the passes, and how it works", () => {
    const html = renderToStaticMarkup(<ResearchPanel brief={BRIEF} passes={PASSES} />);
    const t = plain(text(html));
    expect(t).toContain("Investigación pedida por la IA");
    expect(t).toContain("Quién puede jugar (bajas, dudas, sanciones)");
    expect(t).toContain("No hay bajas en el paquete.");
    expect(t).toContain("P:absences");
    expect(t).toContain("este pase no lee la web: 1");
    expect(t).toContain("Pedir no escala el partido ni cambia ninguna decisión.");
    expect(html.match(/data-testid="intel-research-ask"/g)).toHaveLength(2);
  });

  test("a brief that asked for nothing, and no pass: both say so", () => {
    const html = renderToStaticMarkup(
      <ResearchPanel brief={{ ...BRIEF, research: [] }} passes={[]} />,
    );
    const t = text(html);
    expect(t).toContain("El último informe no pidió investigación.");
    expect(t).toContain("Ningún pase registrado.");
  });
});

describe("the claims the server refused", () => {
  test("the group in the owner's words, and the factor a claim rested on when that was the reason", () => {
    const lines = refusedLines(BRIEF.refused);
    expect(lines[0]).toMatchObject({
      groupLabel: "Por qué de una selección",
      factor: "h2h_weighted",
    });
    expect(lines[1]).toMatchObject({ groupLabel: "Narrativa · form", factor: null });
  });

  test("every group the server writes has its words in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const g of [
        "context",
        "changes",
        "injuries",
        "cards",
        "cards.why",
        "cards.risks",
        "research",
        "narrative.summary",
      ]) {
        expect(refusedGroupLabel(g)).not.toBe(g);
        expect(refusedGroupLabel(g).length).toBeGreaterThan(2);
      }
    }
    expect(refusedGroupLabel("a.group.nobody.knows")).toBe("a.group.nobody.knows");
  });

  test("the panel names the factor and the reason, and says how many were refused when it lists fewer", () => {
    const html = renderToStaticMarkup(<RefusedPanel brief={BRIEF} />);
    const t = plain(text(html));
    expect(t).toContain("Afirmaciones que el servidor rechazó");
    expect(t).toContain("descansaba en h2h_weighted, un factor descriptivo");
    expect(t).toContain("Ventaja por el cara a cara.");
    expect(t).toContain("numbers not in the packet: 7");
    const cut = renderToStaticMarkup(<RefusedPanel brief={{ ...BRIEF, refused_total: 57 }} />);
    expect(text(cut)).toContain("2 de 57");
  });
});

describe("the brief", () => {
  test("its flags, in the owner's words", () => {
    const flags = Object.fromEntries(briefFlags(BRIEF).map((f) => [f.key, f.value]));
    expect(flags["engine"]).toBe("el modelo económico, verificado por el servidor");
    expect(flags["uncertainty"]).toBe("media");
    expect(flags["quality"]).toBe("regular");
    expect(flags["escalate"]).toBe("sí");
  });

  test("a brief of the rules alone, with no uncertainty or quality to say", () => {
    const flags = briefFlags({
      engine: "rules",
      uncertainty: null,
      data_quality: null,
      escalate: false,
    });
    expect(flags.map((f) => f.key)).toEqual(["engine", "escalate"]);
    expect(flags[0]?.value).toBe("las reglas, a partir de los datos");
    expect(flags[1]?.value).toBe("no");
  });

  test("the panel: the summary, the reasons to escalate and the counts", () => {
    const html = renderToStaticMarkup(<BriefPanel brief={BRIEF} />);
    const t = plain(text(html));
    expect(t).toContain("Informe de la IA");
    expect(t).toContain("Un partido parejo.");
    expect(t).toContain("brief-v8");
    expect(t).toContain("claude-haiku-5-5");
    expect(html).toContain('data-testid="intel-brief"');
  });
});

// ── the words ────────────────────────────────────────────────────────────────

describe("the dynamic texts exist in both languages", () => {
  const KEYS = [
    ...["DESCRIPTIVE", "VALIDATED"].map((k) => `intel.match.factors.status.${k}`),
    ...["h2h_weighted", "scenarios", "tactics_profile", "rest_congestion"].map(
      (k) => `intel.match.factors.labels.${k}`,
    ),
    ...["availability", "confirmation", "preview"].map((k) => `intel.match.research.topic.${k}`),
    ...["home", "away", "both"].map((k) => `intel.match.research.side.${k}`),
    ...["no_allowance", "near_budget", "pass_budget", "no_search_pass", "research_failed"].map(
      (k) => `intel.match.research.unserved.${k}`,
    ),
    ...["home_win", "draw", "away_win"].map((k) => `intel.match.scen.result.${k}`),
    ...["single_match", "first_leg", "second_leg", "replay", "series"].map(
      (k) => `intel.match.scen.kind.${k}`,
    ),
    ...[
      "read",
      "data",
      "formation",
      "rotation",
      "coach",
      "goals",
      "late",
      "scoredFirst",
      "concededFirst",
      "htLeading",
      "htTrailing",
      "firstSub",
    ].map((k) => `intel.match.tactics.row.${k}`),
    ...["low", "medium", "high"].map((k) => `intel.match.brief.level.${k}`),
    ...["good", "fair", "poor"].map((k) => `intel.match.brief.dataQuality.${k}`),
    ...["none", "home", "away", "both", "unknown"].map((k) => `intel.match.h2hw.coach.${k}`),
    ...["same_competition", "same_kind", "other_official", "friendly"].map(
      (k) => `center.context.h2h.scope.${k}`,
    ),
    ...["home", "away", "neutral"].map((k) => `center.context.h2h.ground.${k}`),
    "intel.match.refused.group.narrative",
    ...["context", "changes", "injuries", "cards", "cards_why", "cards_risks", "research"].map(
      (k) => `intel.match.refused.group.${k}`,
    ),
    "ai.v2.pass.first",
    "ai.v2.pass.pre",
    "ai.v2.pass.final",
  ];

  test("each key has its words in Spanish and English", () => {
    for (const locale of ["es", "en"] as const) {
      const missing = KEYS.filter((k) => !hasKey(k, locale));
      expect(missing).toEqual([]);
    }
  });

  test("DESCRIPTIVE and VALIDATED are two different words in each language", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      const a = renderToStaticMarkup(<H2hPanel block={H2H} home="A" away="B" />);
      const b = renderToStaticMarkup(
        <H2hPanel block={{ ...H2H, status: "VALIDATED" }} home="A" away="B" />,
      );
      expect(text(a)).not.toEqual(text(b));
    }
  });
});
