import { describe, expect, test } from "bun:test";
import {
  hasStarted,
  isQuarterLine,
  normLine,
  parlayTone,
  parseSlip,
  resultTone,
  selectionKey,
  slipOdds,
  slipReduce,
  MAX_SLIP_LEGS,
  type SlipLeg,
} from "./model";

function leg(
  fixture: number,
  selection = "Home",
  odds: string | null = "2.00",
): Omit<SlipLeg, "key"> {
  return {
    fixture_id: fixture,
    market_key: "1X2",
    selection,
    line: "0",
    home: `H${fixture}`,
    away: `A${fixture}`,
    kickoff_at: "2032-08-01T18:00:00Z",
    odds,
    bookmaker: "Book",
  };
}

describe("selections", () => {
  test("lines compare as numbers", () => {
    expect(normLine("2.50")).toBe("2.5");
    expect(normLine("0.00")).toBe("0");
    expect(normLine(-0.75)).toBe("-0.75");
    expect(selectionKey({ fixture_id: 1, market_key: "OU", selection: "Over", line: "2.50" })).toBe(
      selectionKey({ fixture_id: 1, market_key: "OU", selection: "Over", line: 2.5 }),
    );
  });

  test("quarter lines", () => {
    expect(isQuarterLine("-0.25")).toBe(true);
    expect(isQuarterLine("2.75")).toBe(true);
    expect(isQuarterLine("2.5")).toBe(false);
    expect(isQuarterLine(0)).toBe(false);
  });

  test("tones", () => {
    expect(resultTone("HALF_WIN")).toBe("win");
    expect(resultTone("PUSH")).toBe("neutral");
    expect(resultTone("PENDING")).toBe("pending");
    expect(parlayTone("PARTIAL_VOID")).toBe("win");
    expect(parlayTone("ACTIVE")).toBe("live");
    expect(parlayTone("BUILDING")).toBe("pending");
  });

  test("a match has started at kick-off or once it is no longer scheduled", () => {
    const at = Date.parse("2032-08-01T18:00:00Z");
    expect(hasStarted({ kickoff_at: "2032-08-01T18:00:00Z" }, at - 1)).toBe(false);
    expect(hasStarted({ kickoff_at: "2032-08-01T18:00:00Z" }, at)).toBe(true);
    expect(
      hasStarted({ kickoff_at: "2032-08-01T18:00:00Z", status_group: "live" }, at - 60_000),
    ).toBe(true);
  });
});

describe("the slip", () => {
  test("adds, removes on a second tap, and keeps one leg per match", () => {
    let legs = slipReduce([], { type: "toggle", leg: leg(1) }).legs;
    legs = slipReduce(legs, { type: "toggle", leg: leg(2) }).legs;
    expect(legs.map((l) => l.fixture_id)).toEqual([1, 2]);
    const replaced = slipReduce(legs, { type: "toggle", leg: leg(1, "Draw") });
    expect(replaced.effect).toBe("replaced");
    expect(replaced.legs.map((l) => l.selection)).toEqual(["Draw", "Home"]);
    const removed = slipReduce(replaced.legs, { type: "toggle", leg: leg(1, "Draw") });
    expect(removed.effect).toBe("removed");
    expect(removed.legs.map((l) => l.fixture_id)).toEqual([2]);
  });

  test("never more than ten legs", () => {
    let legs: SlipLeg[] = [];
    for (let i = 1; i <= MAX_SLIP_LEGS; i++)
      legs = slipReduce(legs, { type: "toggle", leg: leg(i) }).legs;
    const full = slipReduce(legs, { type: "toggle", leg: leg(99) });
    expect(full.effect).toBe("full");
    expect(full.legs).toHaveLength(MAX_SLIP_LEGS);
  });

  test("combined odds only when every leg has a price", () => {
    const legs = [leg(1, "Home", "2.00"), leg(2, "Home", "1.50")].map(
      (l) => slipReduce([], { type: "toggle", leg: l }).legs[0]!,
    );
    expect(slipOdds(legs)).toBe(3);
    expect(
      slipOdds([...legs, slipReduce([], { type: "toggle", leg: leg(3, "Home", null) }).legs[0]!]),
    ).toBeNull();
    expect(slipOdds([])).toBeNull();
  });

  test("a stored slip is read defensively", () => {
    expect(parseSlip(null)).toEqual([]);
    expect(parseSlip("not json")).toEqual([]);
    expect(parseSlip('{"a":1}')).toEqual([]);
    const raw = JSON.stringify([
      { ...leg(1), line: "0.00" },
      { ...leg(1, "Away") },
      { fixture_id: "x", market_key: "1X2", selection: "Home", kickoff_at: "z" },
      { ...leg(2), market_key: "CORNERS" },
    ]);
    const legs = parseSlip(raw);
    expect(legs.map((l) => [l.fixture_id, l.selection, l.line])).toEqual([[1, "Home", "0"]]);
  });
});
