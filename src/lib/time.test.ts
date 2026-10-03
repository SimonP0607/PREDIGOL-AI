/// <reference types="bun" />
/**
 * Times are stored in UTC and shown in the reader's zone - including across the days a
 * zone changes its clocks (DST), when a "day" has 23 or 25 hours.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import {
  dayBounds,
  dayKey,
  formatKickoff,
  formatTime,
  isValidTimeZone,
  offsetMinutes,
  relativeDay,
  setTimeZone,
  shiftDay,
  zonedInstant,
} from "@/lib/time";

afterEach(() => {
  setTimeZone("UTC");
  setLocale("es");
});

describe("UTC to the reader's zone", () => {
  const kickoff = "2026-10-03T18:00:00Z";

  test("Bogotá is UTC-5 all year", () => {
    expect(formatTime(kickoff, "America/Bogota")).toBe("13:00");
    expect(offsetMinutes(Date.parse(kickoff), "America/Bogota")).toBe(-300);
    expect(offsetMinutes(Date.parse("2026-01-15T12:00:00Z"), "America/Bogota")).toBe(-300);
  });

  test("Madrid is UTC+2 in summer and UTC+1 in winter", () => {
    expect(formatTime(kickoff, "Europe/Madrid")).toBe("20:00");
    expect(formatTime("2026-12-05T18:00:00Z", "Europe/Madrid")).toBe("19:00");
  });

  test("the module zone is what formatters use by default", () => {
    setTimeZone("America/Bogota");
    expect(formatTime(kickoff)).toBe("13:00");
    setTimeZone("Not/AZone");
    expect(formatTime(kickoff)).toBe("18:00");
  });

  test("a late UTC kick-off belongs to the previous local day in the Americas", () => {
    expect(dayKey("2026-10-04T01:30:00Z", "America/Bogota")).toBe("2026-10-03");
    expect(dayKey("2026-10-04T01:30:00Z", "Europe/Madrid")).toBe("2026-10-04");
  });
});

describe("DST", () => {
  test("Madrid's autumn change: 25 October 2026 has 25 hours", () => {
    const { from, to } = dayBounds("2026-10-25", "Europe/Madrid");
    expect(from).toBe("2026-10-24T22:00:00.000Z");
    expect(to).toBe("2026-10-25T23:00:00.000Z");
    expect((Date.parse(to) - Date.parse(from)) / 3_600_000).toBe(25);
  });

  test("Madrid's spring change: 29 March 2026 has 23 hours", () => {
    const { from, to } = dayBounds("2026-03-29", "Europe/Madrid");
    expect(from).toBe("2026-03-28T23:00:00.000Z");
    expect(to).toBe("2026-03-29T22:00:00.000Z");
  });

  test("New York falls back on 1 November 2026", () => {
    expect(formatTime("2026-11-01T05:30:00Z", "America/New_York")).toBe("01:30");
    expect(formatTime("2026-11-01T06:30:00Z", "America/New_York")).toBe("01:30");
    const { from, to } = dayBounds("2026-11-01", "America/New_York");
    expect(from).toBe("2026-11-01T04:00:00.000Z");
    expect(to).toBe("2026-11-02T05:00:00.000Z");
  });

  test("a wall-clock time converts back to the right instant on both sides of a change", () => {
    expect(new Date(zonedInstant("2026-10-24", 20, 0, "Europe/Madrid")).toISOString()).toBe(
      "2026-10-24T18:00:00.000Z",
    );
    expect(new Date(zonedInstant("2026-10-26", 20, 0, "Europe/Madrid")).toISOString()).toBe(
      "2026-10-26T19:00:00.000Z",
    );
  });

  test("Bogotá days are always 24 hours", () => {
    const { from, to } = dayBounds("2026-10-03", "America/Bogota");
    expect(from).toBe("2026-10-03T05:00:00.000Z");
    expect(to).toBe("2026-10-04T05:00:00.000Z");
  });
});

describe("days and labels", () => {
  test("shiftDay crosses months and years", () => {
    expect(shiftDay("2026-12-31", 1)).toBe("2027-01-01");
    expect(shiftDay("2026-03-01", -1)).toBe("2026-02-28");
  });

  test("today and tomorrow are the reader's, not UTC's", () => {
    const now = Date.parse("2026-10-03T23:30:00Z"); // 18:30 in Bogotá, 01:30 next day in Madrid
    expect(relativeDay("2026-10-04T01:00:00Z", "America/Bogota", now)).toBe("today");
    expect(relativeDay("2026-10-04T01:00:00Z", "Europe/Madrid", now)).toBe("today");
    expect(relativeDay("2026-10-04T20:00:00Z", "America/Bogota", now)).toBe("tomorrow");
  });

  test("kick-off labels are translated", () => {
    const now = Date.parse("2026-10-03T12:00:00Z");
    setLocale("es");
    expect(formatKickoff("2026-10-03T18:00:00Z", "Europe/Madrid", now)).toBe("Hoy 20:00");
    setLocale("en");
    expect(formatKickoff("2026-10-04T18:00:00Z", "Europe/Madrid", now)).toBe("Tomorrow 20:00");
  });

  test("zone names are validated", () => {
    expect(isValidTimeZone("Europe/Madrid")).toBe(true);
    expect(isValidTimeZone("Mars/Olympus")).toBe(false);
    expect(isValidTimeZone("")).toBe(false);
  });
});
