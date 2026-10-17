/// <reference types="bun" />
/**
 * Movement plots the BEST price available at each capture: the highest price any
 * bookmaker quoted for the selection at that instant, prematch only, at the board's line.
 */
import { describe, expect, test } from "bun:test";
import type { OddsSeries } from "@/lib/api/v1/types";
import { bestPriceLines, oddsDomain, oddsTicks, timeExtent } from "./movement";

function series(
  bookmaker: string,
  selection: string,
  points: Array<[string, string, ("prematch" | "live")?]>,
  { market = "1X2", line = "0.00" }: { market?: string; line?: string } = {},
): OddsSeries {
  return {
    bookmaker_id: bookmaker.length,
    bookmaker,
    market_key: market,
    selection,
    line,
    points: points.map(([captured_at, odds_decimal, source = "prematch"]) => ({
      captured_at,
      odds_decimal,
      minutes_to_ko: 100,
      source,
      payload_hash: "x",
    })),
  };
}

const T1 = "2026-10-01T20:40:29.808601Z";
const T2 = "2026-10-03T17:17:18.456456Z";

describe("bestPriceLines", () => {
  test("takes the highest price across bookmakers at each capture", () => {
    const lines = bestPriceLines(
      [
        series("1xBet", "Away", [
          [T1, "18.000"],
          [T2, "17.000"],
        ]),
        series("Betano", "Away", [
          [T1, "15.000"],
          [T2, "19.500"],
        ]),
        series("Pinnacle", "Home", [
          [T1, "1.170"],
          [T2, "1.180"],
        ]),
      ],
      { market: "1X2", line: "0.00", selections: ["Home", "Draw", "Away"] },
    );
    expect(lines.map((l) => l.selection)).toEqual(["Home", "Draw", "Away"]);
    const away = lines[2]?.points ?? [];
    expect(away.map((p) => [p.odds, p.bookmaker])).toEqual([
      [18, "1xBet"],
      [19.5, "Betano"],
    ]);
    expect(away[0]?.t).toBeLessThan(away[1]?.t ?? 0);
    // No series for the draw: no points, never invented ones.
    expect(lines[1]?.points).toEqual([]);
  });

  test("leaves out live prices, other lines and other markets", () => {
    const lines = bestPriceLines(
      [
        series(
          "Bet365",
          "Over",
          [
            [T1, "1.90"],
            [T2, "3.10", "live"],
          ],
          { market: "OU", line: "2.50" },
        ),
        series("Bet365", "Over", [[T1, "1.40"]], { market: "OU", line: "1.50" }),
        series("Bet365", "Home", [[T1, "2.00"]]),
      ],
      { market: "OU", line: "2.5", selections: ["Over", "Under"] },
    );
    expect(lines[0]?.points.map((p) => p.odds)).toEqual([1.9]);
    expect(lines[1]?.points).toEqual([]);
  });

  test("books stored milliseconds apart in one capture are the same instant", () => {
    const lines = bestPriceLines(
      [
        series("A", "Home", [["2026-10-03T17:17:18.100Z", "2.00"]]),
        series("B", "Home", [["2026-10-03T17:17:19.900Z", "2.10"]]),
      ],
      { market: "1X2", line: 0, selections: ["Home"] },
    );
    expect(lines[0]?.points).toHaveLength(1);
    expect(lines[0]?.points[0]?.odds).toBe(2.1);
  });
});

describe("axes", () => {
  test("one time axis for every selection; none with a single capture", () => {
    const at = (iso: string) => Date.parse(iso);
    expect(
      timeExtent([
        { selection: "Home", points: [{ t: at(T1), odds: 2, bookmaker: "A" }] },
        { selection: "Away", points: [{ t: at(T2), odds: 3, bookmaker: "A" }] },
      ]),
    ).toEqual([at(T1), at(T2)]);
    expect(timeExtent([{ selection: "Home", points: [{ t: 1, odds: 2, bookmaker: "A" }] }])).toBe(
      null,
    );
  });

  test("a small move is not inflated: at least ±2.5 % around the middle", () => {
    const [lo, hi] = oddsDomain([1.16, 1.18]);
    expect(lo).toBeLessThanOrEqual(1.16);
    expect(hi).toBeGreaterThanOrEqual(1.18);
    expect(hi - lo).toBeGreaterThanOrEqual(1.17 * 0.05 - 0.01);
  });

  test("the range holds every price and never goes below 1", () => {
    const [lo, hi] = oddsDomain([15, 19.5]);
    expect(lo).toBeLessThanOrEqual(15);
    expect(hi).toBeGreaterThanOrEqual(19.5);
    expect(oddsDomain([1.01])[0]).toBeGreaterThanOrEqual(1);
  });

  test("ticks are both ends and the middle, never repeated", () => {
    expect(oddsTicks([1.1, 1.3])).toEqual([1.1, 1.2, 1.3]);
    expect(oddsTicks([2, 2])).toEqual([2]);
  });
});
