/// <reference types="bun" />
/** The days of a multi-day parlay (plan de Inicio, 2.4): legs grouped by the day they are played, and the span said once. */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { formatDate } from "@/lib/time";
import { dayRange, groupByDay } from "./parlayDays";

setLocale("es");

const leg = (n: number, at: string) => ({ leg_no: n, match: { kickoff_at: at } }) as never;

// noon UTC: the same calendar day in every time zone a reader is in
const D1 = "2031-06-14T12:00:00Z";
const D1B = "2031-06-14T13:30:00Z";
const D2 = "2031-06-15T12:00:00Z";
const D4 = "2031-06-17T12:00:00Z";

describe("legs by day", () => {
  test("one group a day, in the order they come, each leg in its day", () => {
    const groups = groupByDay([leg(1, D1), leg(2, D1B), leg(3, D2), leg(4, D4)]);
    expect(groups.map((g) => g.legs.length)).toEqual([2, 1, 1]);
    expect(groups.map((g) => g.day)).toEqual(["2031-06-14", "2031-06-15", "2031-06-17"]);
  });

  test("a day shows once even when its legs are not next to each other", () => {
    const groups = groupByDay([leg(1, D1), leg(2, D2), leg(3, D1B)]);
    expect(groups.map((g) => g.legs.length)).toEqual([2, 1]);
  });

  test("no legs, no groups", () => {
    expect(groupByDay([])).toEqual([]);
  });
});

describe("the span of a multi-day parlay", () => {
  test("first day to last, both written", () => {
    const groups = groupByDay([leg(1, D1), leg(2, D2), leg(3, D4)]);
    expect(dayRange(groups)).toBe(`${formatDate(D1)} – ${formatDate(D4)}`);
  });

  test("a single day is just that day; none, nothing", () => {
    expect(dayRange(groupByDay([leg(1, D1), leg(2, D1B)]))).toBe(formatDate(D1));
    expect(dayRange([])).toBeNull();
  });
});
