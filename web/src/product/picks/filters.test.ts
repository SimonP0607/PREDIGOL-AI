/// <reference types="bun" />
/** Filters become the API query; the API's own defaults stay out of it. */
import { describe, expect, test } from "bun:test";
import { DEFAULT_FILTERS, activeCount, isDefault, toQuery } from "./filters";

describe("toQuery", () => {
  test("the page opens on the next 24 hours (REVIEW point 13), asked as such", () => {
    expect(DEFAULT_FILTERS.hours).toBe(24);
    expect(toQuery(DEFAULT_FILTERS)).toEqual({ hours: 24 });
    expect(isDefault(DEFAULT_FILTERS)).toBe(true);
  });

  test("every filter maps to its API parameter", () => {
    const q = toQuery({
      competition: { id: 40, name: "Liga Profesional Argentina" },
      market: "OU",
      odds: "1.5-2",
      hours: 168,
    });
    expect(q).toEqual({ competition_id: 40, market: "OU", min_odds: 1.5, max_odds: 2, hours: 168 });
  });

  test("72 h is the API's own default: left out; a wider window is a choice", () => {
    expect(toQuery({ ...DEFAULT_FILTERS, hours: 72 })).toEqual({});
    expect(isDefault({ ...DEFAULT_FILTERS, hours: 72 })).toBe(false);
  });

  test("an open-ended odds range has no maximum", () => {
    expect(toQuery({ ...DEFAULT_FILTERS, odds: "3+" })).toEqual({ min_odds: 3, hours: 24 });
  });
});

describe("activeCount (plan UX, A15: the number on the phone's «Filtros» button)", () => {
  test("nothing beyond the page's defaults is nothing on; each changed filter counts once", () => {
    expect(activeCount(DEFAULT_FILTERS)).toBe(0);
    expect(activeCount({ ...DEFAULT_FILTERS, hours: 72 })).toBe(1);
    expect(
      activeCount({
        competition: { id: 40, name: "Liga Profesional Argentina" },
        market: "OU",
        odds: "2-3",
        hours: 168,
      }),
    ).toBe(4);
    // the count agrees with isDefault: zero exactly when nothing is chosen
    expect(activeCount({ ...DEFAULT_FILTERS, odds: "3+" }) > 0).toBe(
      !isDefault({ ...DEFAULT_FILTERS, odds: "3+" }),
    );
  });
});
