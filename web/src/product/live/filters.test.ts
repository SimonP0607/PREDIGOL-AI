/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { NO_FILTERS, competitionKey, inLiveFilters, picksFirst } from "./filters";

const m = (id: number, over: Partial<LiveMatch> = {}): LiveMatch =>
  ({
    fixture_id: id,
    competition: "Primera A",
    country: "Colombia",
    competition_id: 10,
    home: { name: "Atlético Nacional" },
    away: { name: "Millonarios" },
    ...over,
  }) as LiveMatch;

describe("En vivo: search, filters and PrediGol first (REVIEW point 11)", () => {
  const picks = new Map([[3, 2]]);

  test("the matches with PrediGol picks come first, the rest keep their order", () => {
    expect(picksFirst([m(1), m(2), m(3)], picks).map((x) => x.fixture_id)).toEqual([3, 1, 2]);
  });

  test("team, country, league, gender and 'only with picks'", () => {
    const women = m(4, { competition: "Liga Femenina", competition_id: 11 });
    expect(inLiveFilters(m(1), { ...NO_FILTERS, team: "nacional" }, picks)).toBe(true);
    expect(inLiveFilters(m(1), { ...NO_FILTERS, team: "boca" }, picks)).toBe(false);
    expect(inLiveFilters(m(1), { ...NO_FILTERS, country: "Spain" }, picks)).toBe(false);
    expect(inLiveFilters(m(1), { ...NO_FILTERS, competition: competitionKey(m(1)) }, picks)).toBe(
      true,
    );
    expect(inLiveFilters(women, { ...NO_FILTERS, gender: "women" }, picks)).toBe(true);
    expect(inLiveFilters(m(1), { ...NO_FILTERS, gender: "women" }, picks)).toBe(false);
    expect(inLiveFilters(m(1), { ...NO_FILTERS, picksOnly: true }, picks)).toBe(false);
    expect(inLiveFilters(m(3), { ...NO_FILTERS, picksOnly: true }, picks)).toBe(true);
  });
});
