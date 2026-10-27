/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { exportUrl, filterParams } from "@/lib/api/v1/client";
import {
  NO_FILTER,
  activeCount,
  dayOrNull,
  toApiFilter,
  type PicksFilterState,
} from "./myPicksFilter";

const f = (patch: Partial<PicksFilterState>): PicksFilterState => ({ ...NO_FILTER, ...patch });

describe("the filter of «Picks guardados» (plan UX, B5)", () => {
  test("no filter: nothing set, nothing asked of the API", () => {
    expect(activeCount(NO_FILTER)).toBe(0);
    expect(toApiFilter(NO_FILTER)).toEqual({
      result: null,
      market: null,
      competition: null,
      origin: null,
      band: null,
      since: null,
      until: null,
      q: null,
    });
    expect(Object.values(filterParams(toApiFilter(NO_FILTER))).every((v) => v === undefined)).toBe(
      true,
    );
  });

  test("each part set counts once; a search counts once it has a letter", () => {
    expect(activeCount(f({ result: "won" }))).toBe(1);
    expect(activeCount(f({ result: "won", market: "1X2", competition: 39 }))).toBe(3);
    expect(
      activeCount(f({ origin: "mine", band: "2-3", since: "2026-10-01", until: "2026-10-26" })),
    ).toBe(4);
    expect(activeCount(f({ q: "   " }))).toBe(0);
    expect(activeCount(f({ q: " betis " }))).toBe(1);
  });

  test("a day range whose ends cross is put in order; the search is trimmed to 60 characters", () => {
    const api = toApiFilter(
      f({ since: "2026-10-20", until: "2026-10-01", q: `  ${"a".repeat(80)}  ` }),
    );
    expect([api.since, api.until]).toEqual(["2026-10-01", "2026-10-20"]);
    expect(api.q).toBe("a".repeat(60));
    expect(toApiFilter(f({ q: "   " })).q).toBeNull();
  });

  test("a date field gives a day or nothing: never an impossible day", () => {
    expect(dayOrNull("2026-10-27")).toBe("2026-10-27");
    expect(dayOrNull("")).toBeNull();
    expect(dayOrNull("2026-13-40")).toBeNull();
    expect(dayOrNull("27/10/2026")).toBeNull();
  });

  test("the list, the totals and the CSV ask with the same parameters", () => {
    const api = toApiFilter(
      f({
        result: "lost",
        market: "OU",
        competition: 140,
        origin: "predigol",
        band: "lt1.5",
        q: "Bahía",
      }),
    );
    expect(filterParams(api)).toEqual({
      result: "lost",
      market: "OU",
      competition: 140,
      origin: "predigol",
      band: "lt1.5",
      since: undefined,
      until: undefined,
      q: "Bahía",
    });
    const url = new URL(exportUrl("picks", api), "https://predigol.test");
    expect(url.pathname).toBe("/api/v1/me/picks/export");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      result: "lost",
      market: "OU",
      competition: "140",
      origin: "predigol",
      band: "lt1.5",
      q: "Bahía",
    });
  });

  test("the parlays' CSV is every parlay of the reader: the picks' filter does not apply to it", () => {
    expect(exportUrl("parlays", toApiFilter(f({ result: "won" })))).toBe(
      "/api/v1/me/parlays/export",
    );
    expect(exportUrl("picks")).toBe("/api/v1/me/picks/export");
  });
});
