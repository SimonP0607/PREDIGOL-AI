/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import type { UserParlay, UserPick } from "@/lib/api/v1/types_records";
import {
  fromParlays,
  fromPicks,
  outcomeOf,
  recap,
  streaksOf,
  within,
  type RecapRecord,
} from "./recapData";

const r = (
  at: string,
  outcome: RecapRecord["outcome"],
  odds: number | null,
  profit: number,
  market = "1X2",
) => ({ at, outcome, odds, profit, market }) satisfies RecapRecord;

describe("Tu recapitulación (REVIEW point 19)", () => {
  test("results read the same for picks and parlays; pending is not a result", () => {
    expect(outcomeOf("HALF_WIN")).toBe("win");
    expect(outcomeOf("LOST")).toBe("loss");
    expect(outcomeOf("PUSH")).toBe("void");
    expect(outcomeOf("PENDING")).toBeNull();
    expect(outcomeOf("ACTIVE")).toBeNull();
  });

  test("the streaks: current, best won, worst lost - a void neither", () => {
    expect(streaksOf(["win", "win", "loss", "win", "win", "win", "loss", "loss"])).toEqual({
      current: { kind: "loss", length: 2 },
      bestWin: 3,
      worstLoss: 2,
    });
    expect(streaksOf([])).toEqual({ current: null, bestWin: 0, worstLoss: 0 });
  });

  test("profit by day and in total, odds and markets, at the profit each record was settled at", () => {
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
    expect(x.roi).toBeCloseTo(-0.04);
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
    expect(x.byOdds.find((b) => b.key === "1.5-2")).toMatchObject({
      count: 1,
      wins: 1,
      hitRate: 1,
    });
    expect(x.byOdds.find((b) => b.key === "5+")).toMatchObject({ count: 1, wins: 0, hitRate: 0 });
    expect(x.byMarket.map((m) => [m.market, m.count, m.hitRate])).toEqual([
      ["1X2", 3, 0.5],
      ["OU", 2, 0.5],
    ]);
    expect(x.last).toEqual(["win", "loss", "win", "loss"]);
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
      { at: "2032-08-01T15:00:00Z", odds: 2.2, profit: 1.2, outcome: "win", market: "1X2" },
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
      { at: "2032-08-02T18:00:00Z", odds: 7.48, profit: -1, outcome: "loss", market: null },
    ]);
  });

  test("a period keeps the records of its last days", () => {
    const now = Date.parse("2032-08-31T12:00:00Z");
    const rs = [r("2032-08-01T15:00:00Z", "win", 2, 1), r("2032-08-30T15:00:00Z", "loss", 2, -1)];
    expect(within(rs, 7, now)).toHaveLength(1);
    expect(within(rs, null, now)).toHaveLength(2);
  });
});
