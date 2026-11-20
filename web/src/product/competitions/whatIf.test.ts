/// <reference types="bun" />
/**
 * Plan PM, PM-09-03 (UX-181): the calculator reproduces, case by case, the battery the server checks with its own ranking
 * (`backend/tests/fixtures/competitions/what_if_cases.json`, BE-082): the same points, matches, order and ties. A chosen result
 * adds points; no score is invented, so clubs left level are said to be level.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { applyChoices, zoneShifts, type Choice, type WhatIfRow } from "./scenario";

interface Case {
  name: string;
  kind: "aggregate" | "average";
  points: { win: number; draw: number; loss: number };
  rows: WhatIfRow[];
  remaining: [number, number][];
  choices: Record<string, Choice>;
  expected: { team: number; points: number; played: number; position: number; tied: boolean }[];
}

const FILE = join(
  import.meta.dir,
  "..",
  "..",
  "..",
  "..",
  "backend",
  "tests",
  "fixtures",
  "competitions",
  "what_if_cases.json",
);
const CASES = (JSON.parse(readFileSync(FILE, "utf8")) as { cases: Case[] }).cases;

describe("the shared cases of the server", () => {
  test("the battery is there and covers both kinds of table", () => {
    expect(CASES.length).toBeGreaterThanOrEqual(7);
    expect(new Set(CASES.map((c) => c.kind))).toEqual(new Set(["aggregate", "average"]));
  });

  for (const c of CASES)
    test(c.name, () => {
      const got = applyChoices(c.kind, c.rows, c.remaining, c.choices, c.points);
      expect(
        got.map(({ team, points, played, position, tied }) => ({
          team,
          points,
          played,
          position,
          tied,
        })),
      ).toEqual(c.expected);
    });
});

describe("what the reader sees change", () => {
  test("nothing chosen: the table of today", () => {
    const rows = [
      { team: 1, played: 2, points: 6 },
      { team: 2, played: 2, points: 3 },
    ];
    const got = applyChoices("aggregate", rows, [[2, 1]], {}, { win: 3, draw: 1, loss: 0 });
    expect(got.map((l) => [l.team, l.position, l.before])).toEqual([
      [1, 1, 1],
      [2, 2, 2],
    ]);
  });

  test("who enters and who leaves a zone", () => {
    expect(
      zoneShifts([{ positions: [1, 2] }, { positions: [4] }], [1, 2, 3, 4], [1, 3, 2, 4]),
    ).toEqual([{ zone: 0, entered: [3], left: [2] }]);
  });

  test("a club whose average does not count this season does not move", () => {
    const rows = [
      { team: 1, played: 10, points: 10, counts_now: false },
      { team: 2, played: 10, points: 12, counts_now: true },
    ];
    const got = applyChoices(
      "average",
      rows,
      [[1, 2]],
      { "0": "home" },
      { win: 3, draw: 1, loss: 0 },
    );
    expect(got.find((l) => l.team === 1)).toMatchObject({ points: 10, played: 10 });
    expect(got.find((l) => l.team === 2)).toMatchObject({ points: 12, played: 11 });
  });
});
