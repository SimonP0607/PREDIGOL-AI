import { describe, expect, it } from "bun:test";
import { savedBody, selectionKey, type SlipLeg } from "./model";

function leg(fixture: number, odds: string | null): SlipLeg {
  const base = {
    fixture_id: fixture,
    market_key: "1X2" as const,
    selection: "Home",
    line: "0",
    home: "A",
    away: "B",
    kickoff_at: "2032-08-01T18:00:00Z",
    odds,
    bookmaker: null,
  };
  return { ...base, key: selectionKey(base) };
}

describe("savedBody: the odds the screen showed and when they were captured", () => {
  it("sends the server's odds with their capture time", () => {
    const l = leg(1, "2.10");
    const seen = new Map([
      [l.key, { odds: "2.300", odds_captured_at: "2032-08-01T11:30:00+00:00" }],
    ]);
    expect(savedBody([l], seen)).toEqual([
      {
        fixture_id: 1,
        market_key: "1X2",
        selection: "Home",
        line: "0",
        odds: "2.300",
        odds_captured_at: "2032-08-01T11:30:00+00:00",
      },
    ]);
  });

  it("sends no odds when the server did not price it or gave no time", () => {
    const priced = leg(1, "2.10");
    const unpriced = leg(2, "1.90");
    const seen = new Map([
      [priced.key, { odds: "2.300", odds_captured_at: null }],
      [unpriced.key, { odds: null, odds_captured_at: "2032-08-01T11:30:00+00:00" }],
    ]);
    for (const row of savedBody([priced, unpriced], seen)) {
      expect("odds" in row).toBe(false);
      expect("odds_captured_at" in row).toBe(false);
    }
  });

  it("never falls back to the price we showed when the selection was added (it has no time)", () => {
    const l = leg(3, "2.10");
    expect("odds" in savedBody([l], new Map())[0]!).toBe(false);
  });
});
