/// <reference types="bun" />
/** The history of the reader's parlays (UX-148, sheet L05): filters, days, and how the legs stand. */
import { describe, expect, test } from "bun:test";
import { setTimeZone } from "@/lib/time";
import type { UserParlay, UserParlayLeg } from "@/lib/api/v1/types_records";
import { filterParlays, isSettled, legTally, parlaysByDay } from "./parlayHistory";

setTimeZone("America/Bogota");

const leg = (n: number, status: UserParlayLeg["status"]) =>
  ({ leg_no: n, status }) as UserParlayLeg;
const parlay = (
  id: number,
  status: UserParlay["status"],
  created_at: string,
  legs: UserParlayLeg[] = [],
) => ({ id, status, created_at, legs }) as unknown as UserParlay;

const list = [
  parlay(3, "ACTIVE", "2026-11-10T22:25:00Z", [
    leg(1, "WIN"),
    leg(2, "PENDING"),
    leg(3, "PENDING"),
  ]),
  parlay(2, "WON", "2026-11-09T01:00:00Z"),
  parlay(1, "LOST", "2026-11-08T15:00:00Z", [
    leg(1, "WIN"),
    leg(2, "HALF_LOSS"),
    leg(3, "PUSH"),
    leg(4, "LOSS"),
  ]),
];

describe("the parlays' history", () => {
  test("pending and settled split by the parlay's own state", () => {
    expect(filterParlays(list, "pending").map((p) => p.id)).toEqual([3]);
    expect(filterParlays(list, "settled").map((p) => p.id)).toEqual([2, 1]);
    expect(filterParlays(list, "all")).toHaveLength(3);
    expect(isSettled({ status: "PARTIAL_VOID" })).toBe(true);
    expect(isSettled({ status: "READY" })).toBe(false);
  });

  test("grouped by the reader's day: 01:00 UTC on the 9th is the 8th in Bogotá", () => {
    expect(parlaysByDay(list).map((g) => [g.day, g.parlays.map((p) => p.id)])).toEqual([
      ["2026-11-10", [3]],
      ["2026-11-08", [2, 1]],
    ]);
  });

  test("the legs: a half loss is lost, a push is not, pending is still to play", () => {
    expect(legTally(list[0]!)).toEqual({ won: 1, lost: 0, open: 2, total: 3 });
    expect(legTally(list[2]!)).toEqual({ won: 2, lost: 2, open: 0, total: 4 });
  });
});
