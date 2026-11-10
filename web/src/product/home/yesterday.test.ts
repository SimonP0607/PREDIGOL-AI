/// <reference types="bun" />
/**
 * Inicio asks for yesterday's set only while today's board says a pick of that day is still open (plan Inicio, P4, UX-077).
 * The server side of the flag has its own integration test; this is the other half, the one production cannot show on a
 * day with no pick left open the night before.
 */
import { describe, expect, test } from "bun:test";
import { wantsYesterday } from "./yesterday";

describe("wantsYesterday", () => {
  test("asks while the day before still has a pick to finish or settle", () => {
    expect(wantsYesterday({ previous_day_open: true })).toBe(true);
  });

  test("does not ask when the day before is closed", () => {
    expect(wantsYesterday({ previous_day_open: false })).toBe(false);
  });

  test("does not ask when the API does not say (a board from before the field existed)", () => {
    expect(wantsYesterday({})).toBe(false);
  });

  test("does not ask while the board has not loaded", () => {
    expect(wantsYesterday(undefined)).toBe(false);
    expect(wantsYesterday(null)).toBe(false);
  });
});
