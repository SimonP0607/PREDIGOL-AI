/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { groupByMatch, startedState } from "./started";

describe("the state filter of 'Ya empezaron hoy' (REVIEW point 14)", () => {
  test("in play, won, lost - and the rest", () => {
    expect(startedState({ result_status: null, phase: "live" })).toBe("live");
    expect(startedState({ result_status: "win", phase: "finished" })).toBe("won");
    expect(startedState({ result_status: "half_loss", phase: "finished" })).toBe("lost");
    expect(startedState({ result_status: "void", phase: "postponed" })).toBe("other");
    expect(startedState({ result_status: null, phase: "awaiting" })).toBe("other");
  });

  test("a pick in play whose result row is already there (pending) is in play", () => {
    expect(startedState({ result_status: "pending", phase: "live" })).toBe("live");
    expect(startedState({ result_status: "pending", phase: "suspended" })).toBe("live");
    expect(startedState({ result_status: "pending", phase: "postponed" })).toBe("other");
  });
});

describe("the started picks grouped by match (plan PICKS, F6 / L2)", () => {
  const pick = (pick_id: number, fixture_id: number) =>
    ({ pick_id, fixture_id }) as Parameters<typeof groupByMatch>[0][number];

  test("one group per match, in the order each match first appears, picks in their order", () => {
    const groups = groupByMatch([pick(1, 10), pick(2, 20), pick(3, 10), pick(4, 30), pick(5, 20)]);
    expect(groups.map((g) => g.fixtureId)).toEqual([10, 20, 30]);
    expect(groups.map((g) => g.picks.map((p) => p.pick_id))).toEqual([[1, 3], [2, 5], [4]]);
    expect(groups[0]?.head.pick_id).toBe(1);
  });

  test("no picks, no groups; no pick is lost or counted twice", () => {
    expect(groupByMatch([])).toEqual([]);
    const all = [pick(1, 1), pick(2, 1), pick(3, 2), pick(4, 3), pick(5, 3), pick(6, 3)];
    expect(groupByMatch(all).flatMap((g) => g.picks)).toHaveLength(all.length);
  });
});
