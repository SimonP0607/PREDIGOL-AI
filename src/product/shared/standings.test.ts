/// <reference types="bun" />
/**
 * A season's tables stay apart (Apertura and Clausura are two tables, a ranking of third-placed teams
 * is not a group, an annual aggregate is its own section), and home / away tables are ranked from
 * the provider's home and away games.
 */
import { describe, expect, test } from "bun:test";
import type {
  CompetitionTable,
  StandingLine,
  StandingsTable,
  TableRow,
} from "@/lib/api/v1/types_center";
import {
  defaultSection,
  figures,
  hasSplits,
  matchTables,
  rankedRows,
  tableSections,
} from "./standings";

function row(over: Partial<TableRow> & { team_id: number; rank: number }): TableRow {
  return {
    team: `T${over.team_id}`,
    played: 2,
    wins: 1,
    draws: 0,
    losses: 1,
    goals_for: 2,
    goals_against: 2,
    points: 3,
    form: null,
    group: null,
    ...over,
  };
}

function table(over: Partial<StandingsTable> & { key: string }): StandingsTable {
  return {
    label: over.key,
    stage: over.key,
    stages: [over.key],
    phase: over.key,
    kind: "full",
    method: "label",
    agreement: "2/2",
    note: "",
    is_current: false,
    rows: [],
    ...over,
  };
}

function competition(tables: StandingsTable[]): CompetitionTable {
  return { competition_id: 1, season: 2026, snapshot_at: "2026-10-04T05:00:00Z", tables, rows: [] };
}

describe("sections", () => {
  test("Colombia: Apertura and Clausura are two sections, the one being played first", () => {
    const sections = tableSections(
      competition([table({ key: "Apertura" }), table({ key: "Clausura", is_current: true })]),
    );
    expect(sections.map((s) => [s.id, s.current])).toEqual([
      ["stage:Apertura", false],
      ["stage:Clausura", true],
    ]);
    expect(defaultSection(sections)).toBe("stage:Clausura");
  });

  test("Argentina: each phase's groups in one section; Peru's annual table apart", () => {
    const sections = tableSections(
      competition([
        table({ key: "Apertura - Group A", stage: "Apertura", phase: "Apertura", kind: "group" }),
        table({ key: "Apertura - Group B", stage: "Apertura", phase: "Apertura", kind: "group" }),
        table({
          key: "Primera Division: Tabla Anual",
          stage: null,
          phase: null,
          stages: ["Apertura", "Clausura"],
          kind: "aggregate",
          method: "games",
        }),
        table({
          key: "Period 1",
          stage: null,
          phase: null,
          stages: [],
          kind: "other",
          method: "unmapped",
        }),
      ]),
    );
    expect(sections.map((s) => [s.kind, s.tables.length])).toEqual([
      ["stage", 2],
      ["aggregate", 1],
      ["other", 1],
    ]);
    expect(defaultSection(sections)).toBe("stage:Apertura");
  });
});

describe("home and away", () => {
  const rows = [
    row({
      team_id: 1,
      rank: 1,
      points: 6,
      home: { played: 1, wins: 0, draws: 1, losses: 0, goals_for: 1, goals_against: 1 },
      away: { played: 1, wins: 1, draws: 0, losses: 0, goals_for: 3, goals_against: 0 },
    }),
    row({
      team_id: 2,
      rank: 2,
      points: 3,
      home: { played: 1, wins: 1, draws: 0, losses: 0, goals_for: 2, goals_against: 0 },
      away: { played: 1, wins: 0, draws: 0, losses: 1, goals_for: 0, goals_against: 1 },
    }),
  ];

  test("all games keep the provider's rank and points", () => {
    expect(rankedRows(rows, "all").map((r) => [r.rank, r.row.team_id, r.figures.points])).toEqual([
      [1, 1, 6],
      [2, 2, 3],
    ]);
  });

  test("home games are ranked by points from wins and draws", () => {
    expect(rankedRows(rows, "home").map((r) => [r.rank, r.row.team_id, r.figures.points])).toEqual([
      [1, 2, 3],
      [2, 1, 1],
    ]);
    expect(figures(rows[0]!, "away")?.goalDiff).toBe(3);
    expect(hasSplits(rows)).toBe(true);
  });

  test("a row without home figures is left out of the home table, never shown as zeros", () => {
    expect(rankedRows([row({ team_id: 3, rank: 1 })], "home")).toEqual([]);
    expect(hasSplits([row({ team_id: 3, rank: 1 })])).toBe(false);
  });
});

test("the Match Center's tables are the ones its two rows come from", () => {
  const line = (key: string): StandingLine => ({ table_key: key }) as unknown as StandingLine;
  const tables = [table({ key: "Clausura - Group A" }), table({ key: "Clausura - Group B" })];
  expect(matchTables([line("Clausura - Group B")], tables).map((t) => t.key)).toEqual([
    "Clausura - Group B",
  ]);
  expect(matchTables([], undefined)).toEqual([]);
});
