/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { daySummary, recentDays, summaryText } from "./days";

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

  test("a day's result: every pick once - won, lost, void, open - and the units (plan PICKS, D3)", () => {
    expect(
      daySummary([
        { status: "LOSS", profit_units: "-1.00" },
        { status: "WIN", profit_units: "2.75" },
        { status: "HALF_LOSS", profit_units: "-0.50" },
        { status: "PENDING", profit_units: null },
        { status: "VOID", profit_units: "0.00" },
      ]),
    ).toEqual({
      count: 5,
      won: 1,
      lost: 2,
      voids: 1,
      open: 1,
      halfWon: 0,
      halfLost: 1,
      units: 1.25,
    });
    expect(daySummary([{ status: "PENDING", profit_units: null }]).units).toBeNull();
  });

  test("the summary adds up to the count, and a half result is said beside its own side", () => {
    const sum = daySummary([
      { status: "LOSS", profit_units: "-1.00" },
      { status: "HALF_WIN", profit_units: "0.40" },
      { status: "HALF_LOSS", profit_units: "-0.50" },
      { status: "PENDING", profit_units: null },
      { status: "VOID", profit_units: "0.00" },
    ]);
    expect(sum.won + sum.lost + sum.voids + sum.open).toBe(sum.count);
    expect(summaryText(sum)).toBe(
      "5 picks · 1 ganado (1 a medias) · 2 perdidos (1 a medias) · 1 nulo o devuelto · 1 por jugar o en juego",
    );
    setLocale("en");
    try {
      expect(summaryText(sum)).toMatch(
        /^5 picks · 1 won \(1 .+\) · 2 lost \(1 .+\) · 1 void or pushed · 1 /,
      );
    } finally {
      setLocale("es");
    }
  });

  test("without voids nor half results the summary keeps four parts and no note", () => {
    expect(
      summaryText(
        daySummary([
          { status: "WIN", profit_units: "1.00" },
          { status: "PENDING", profit_units: null },
        ]),
      ),
    ).toBe("2 picks · 1 ganado · 0 perdidos · 1 por jugar o en juego");
  });
});
