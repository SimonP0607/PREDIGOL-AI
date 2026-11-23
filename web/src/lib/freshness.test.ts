import { describe, expect, test } from "bun:test";
import { ageMs, DELAY_AFTER_MS, isDelayed, showFreshness } from "./freshness";

const NOW = Date.parse("2026-11-23T20:00:00Z");
const ago = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

describe("freshness thresholds (D16)", () => {
  test("the live threshold is 5 minutes and the day's is 60", () => {
    expect(DELAY_AFTER_MS.live).toBe(300_000);
    expect(DELAY_AFTER_MS.day).toBe(3_600_000);
  });

  test("live data is late after 5 minutes and not before", () => {
    expect(isDelayed("live", ago(4.9), NOW)).toBe(false);
    expect(isDelayed("live", ago(5), NOW)).toBe(false);
    expect(isDelayed("live", ago(5.1), NOW)).toBe(true);
  });

  test("the day's data is late after 60 minutes and not before", () => {
    expect(isDelayed("day", ago(59), NOW)).toBe(false);
    expect(isDelayed("day", ago(60), NOW)).toBe(false);
    expect(isDelayed("day", ago(61), NOW)).toBe(true);
  });

  test("a time that is not known is never called late", () => {
    expect(isDelayed("live", null, NOW)).toBe(false);
    expect(isDelayed("day", undefined, NOW)).toBe(false);
    expect(isDelayed("day", "not a date", NOW)).toBe(false);
    expect(ageMs(null, NOW)).toBeNull();
  });

  test("a time in the future is no age at all", () => {
    expect(ageMs(NOW + 60_000, NOW)).toBe(0);
    expect(isDelayed("live", NOW + 60_000, NOW)).toBe(false);
  });

  test("a reader hears of it only when it is late; the administrator always", () => {
    expect(showFreshness("live", ago(1), false, NOW)).toBe(false);
    expect(showFreshness("live", ago(9), false, NOW)).toBe(true);
    expect(showFreshness("day", ago(30), false, NOW)).toBe(false);
    expect(showFreshness("day", ago(90), false, NOW)).toBe(true);
    expect(showFreshness("live", ago(1), true, NOW)).toBe(true);
    expect(showFreshness("day", null, true, NOW)).toBe(true);
    expect(showFreshness("day", null, false, NOW)).toBe(false);
  });
});
