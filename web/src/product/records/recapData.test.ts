/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import type { UserParlay, UserPick } from "@/lib/api/v1/types_records";
import { fromParlays, fromPicks, outcomeOf, recap, within, type RecapRecord } from "./recapData";

const r = (
  at: string,
  outcome: RecapRecord["outcome"],
  odds: number | null,
  profit: number,
  market = "1X2",
  staked = outcome !== "void",
) => ({ at, from: at, outcome, odds, profit, market, staked }) satisfies RecapRecord;

describe("Tu recapitulación (REVIEW point 19)", () => {
  test("results read the same for picks and parlays; pending is not a result", () => {
    expect(outcomeOf("HALF_WIN")).toBe("win");
    expect(outcomeOf("LOST")).toBe("loss");
    expect(outcomeOf("PUSH")).toBe("void");
    expect(outcomeOf("PENDING")).toBeNull();
    expect(outcomeOf("ACTIVE")).toBeNull();
  });

  test("profit by day and in total, at the profit each record was settled at - and never a streak", () => {
    const rs = [
      r("2032-08-01T15:00:00Z", "win", 2.0, 1.0),
      r("2032-08-01T18:00:00Z", "loss", 3.5, -1, "OU"),
      r("2032-08-02T15:00:00Z", "win", 1.8, 0.8, "OU"),
      r("2032-08-03T15:00:00Z", "void", 2.2, 0),
      r("2032-08-03T19:00:00Z", "loss", 6.0, -1),
    ];
    const x = recap(rs, "UTC");
    expect([x.settled, x.wins, x.losses, x.voids]).toEqual([5, 2, 2, 1]);
    expect(x.hitRate).toBe(0.5);
    expect(x.profit).toBeCloseTo(-0.2);
    // one formula with the server's history (plan UX, A1): profit over the staked records - the void is not one
    expect(x.staked).toBe(4);
    expect(x.roi).toBeCloseTo(-0.05);
    expect(x.avgOdds).toBeCloseTo((2 + 3.5 + 1.8 + 2.2 + 6) / 5);
    expect(x.avgOddsWon).toBeCloseTo(1.9);
    expect(x.days.map((d) => [d.day, d.count])).toEqual([
      ["2032-08-01", 2],
      ["2032-08-02", 1],
      ["2032-08-03", 2],
    ]);
    expect(x.days.map((d) => Math.round(d.total * 10) / 10)).toEqual([0, 0.8, -0.2]);
    expect(x.bestDay?.day).toBe("2032-08-02");
    expect(x.worstDay?.day).toBe("2032-08-03");
    // plan UX, B5 (section 30): no streak is kept, and the breakdown is the server's
    expect(Object.keys(x).sort()).toEqual(
      [
        "avgOdds",
        "avgOddsWon",
        "bestDay",
        "days",
        "hitRate",
        "losses",
        "profit",
        "roi",
        "settled",
        "staked",
        "voids",
        "wins",
        "worstDay",
      ].sort(),
    );
  });

  test("the user's own odds count when they gave them; pending picks are left out", () => {
    const pick = (status: string, odds: string, user: string | null, profit: string | null) =>
      ({
        status,
        odds,
        user_odds: user,
        profit_units: profit,
        market_key: "1X2",
        match: { kickoff_at: "2032-08-01T15:00:00Z" },
      }) as unknown as UserPick;
    const rs = fromPicks([
      pick("WIN", "2.00", "2.20", "1.20"),
      pick("PENDING", "2.00", null, null),
    ]);
    expect(rs).toEqual([
      {
        at: "2032-08-01T15:00:00Z",
        from: "2032-08-01T15:00:00Z",
        odds: 2.2,
        profit: 1.2,
        outcome: "win",
        market: "1X2",
        staked: true,
      },
    ]);
    const parlay = {
      status: "LOST",
      combined_odds: "7.480",
      profit_units: "-1.00",
      created_at: "2032-07-31T10:00:00Z",
      settled_at: null,
      legs: [
        { match: { kickoff_at: "2032-08-01T15:00:00Z" } },
        { match: { kickoff_at: "2032-08-02T18:00:00Z" } },
      ],
    } as unknown as UserParlay;
    expect(fromParlays([parlay])).toEqual([
      {
        at: "2032-08-02T18:00:00Z",
        from: "2032-08-01T15:00:00Z",
        odds: 7.48,
        profit: -1,
        outcome: "loss",
        market: null,
        staked: true,
      },
    ]);
  });

  test("a period keeps the records of its last days", () => {
    const now = Date.parse("2032-08-31T12:00:00Z");
    const rs = [r("2032-08-01T15:00:00Z", "win", 2, 1), r("2032-08-30T15:00:00Z", "loss", 2, -1)];
    expect(within(rs, 7, now, "UTC")).toHaveLength(1);
    expect(within(rs, null, now, "UTC")).toHaveLength(2);
  });

  test("a period is calendar days in the reader's zone, today included - the server's window (plan UX, A1)", () => {
    // 7 days on 31 Aug: from local midnight of the 25th to the end of the 31st (userdata/records.py, period_bounds)
    const now = Date.parse("2032-08-31T12:00:00Z");
    const edge = [r("2032-08-25T00:30:00Z", "win", 2, 1), r("2032-08-24T23:30:00Z", "loss", 2, -1)];
    expect(within(edge, 7, now, "UTC").map((x) => x.at)).toEqual(["2032-08-25T00:30:00Z"]);
    // in Bogotá (UTC-5) 03:00 UTC on the 25th is still the 24th: outside
    expect(within([r("2032-08-25T03:00:00Z", "win", 2, 1)], 7, now, "America/Bogota")).toEqual([]);
    expect(within([r("2032-08-25T06:00:00Z", "win", 2, 1)], 7, now, "America/Bogota")).toHaveLength(
      1,
    );
  });

  test("a parlay enters a period by its first match, as the server counts it; one without legs never", () => {
    const parlay = (first: string, last: string | null) =>
      ({
        status: "WON",
        combined_odds: "4.000",
        profit_units: "3.0000",
        created_at: "2032-08-20T10:00:00Z",
        settled_at: null,
        legs: [first, last]
          .filter((k): k is string => k !== null)
          .map((k) => ({ match: { kickoff_at: k } })),
      }) as unknown as UserParlay;
    const now = Date.parse("2032-08-31T12:00:00Z");
    const spanning = fromParlays([parlay("2032-08-24T20:00:00Z", "2032-08-26T20:00:00Z")]);
    expect(spanning[0]?.at).toBe("2032-08-26T20:00:00Z");
    expect(within(spanning, 7, now, "UTC")).toEqual([]);
    expect(fromParlays([{ ...parlay("2032-08-30T20:00:00Z", null), legs: [] }])).toEqual([]);
  });
});

describe("Rentabilidad (ROI): one figure with the server's history (plan UX, A1, F54)", () => {
  const pick = (status: string, profit: string | null): UserPick =>
    ({
      id: 1,
      match: { kickoff_at: "2032-08-01T15:00:00Z" },
      market_key: "1X2",
      status,
      odds: "2.000",
      user_odds: null,
      profit_units: profit,
    }) as unknown as UserPick;

  test("a push stakes its unit, a void does not, and a record without a profit counts in neither", () => {
    // GET /me/history (userdata/records.py, GroupStats): profit 1.1 - 1 + 0 over WIN, LOSS and PUSH = 3 staked
    const rs = fromPicks([
      pick("WIN", "1.1000"),
      pick("LOSS", "-1.0000"),
      pick("PUSH", "0.0000"),
      pick("VOID", "0.0000"),
      pick("WIN", null),
      pick("PENDING", null),
    ]);
    const x = recap(rs, "UTC");
    expect(x.staked).toBe(3);
    expect(x.profit).toBeCloseTo(0.1);
    expect(x.roi).toBeCloseTo(0.1 / 3);
  });

  test("a parlay partly void stakes; a void parlay does not", () => {
    const parlay = (status: string, profit: string | null): UserParlay =>
      ({
        id: 1,
        created_at: "2032-08-01T10:00:00Z",
        settled_at: "2032-08-01T20:00:00Z",
        combined_odds: "4.000",
        status,
        profit_units: profit,
        legs: [{ match: { kickoff_at: "2032-08-01T15:00:00Z" } }],
      }) as unknown as UserParlay;
    const x = recap(
      fromParlays([parlay("PARTIAL_VOID", "1.0000"), parlay("VOID", "0.0000")]),
      "UTC",
    );
    expect(x.staked).toBe(1);
    expect(x.roi).toBeCloseTo(1);
  });
});
