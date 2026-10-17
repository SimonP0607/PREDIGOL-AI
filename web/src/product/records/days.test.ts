/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { daySummary, recentDays } from "./days";

describe("the day's picks navigation (REVIEW point 12)", () => {
  test("today and the six days before it, newest first", () => {
    expect(recentDays("2026-10-11")).toEqual([
      "2026-10-11",
      "2026-10-10",
      "2026-10-09",
      "2026-10-08",
      "2026-10-07",
      "2026-10-06",
      "2026-10-05",
    ]);
  });

  test("a day's result: won, lost, still open and the units", () => {
    expect(
      daySummary([
        { status: "LOSS", profit_units: "-1.00" },
        { status: "WIN", profit_units: "2.75" },
        { status: "HALF_LOSS", profit_units: "-0.50" },
        { status: "PENDING", profit_units: null },
        { status: "VOID", profit_units: "0.00" },
      ]),
    ).toEqual({ count: 5, won: 1, lost: 2, open: 1, units: 1.25 });
    expect(daySummary([{ status: "PENDING", profit_units: null }]).units).toBeNull();
  });
});
