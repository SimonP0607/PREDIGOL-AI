/// <reference types="bun" />
/**
 * The day narrowed by the reader's filters (plan Partidos, P2 and P3): a category that does not play that day is
 * ignored as a country is, and the state chips count with every other filter on.
 */
import { describe, expect, test } from "bun:test";
import type { MatchSummary } from "@/lib/api/v1/types";
import type { MatchItem, RowGroup } from "./model";
import { narrowDay, type DayFilters } from "./narrow";

let nextId = 1;
function item(
  group: RowGroup,
  comp: Partial<MatchSummary["competition"]>,
  teams: [string, string] = ["Home", "Away"],
): MatchItem {
  const id = nextId++;
  return {
    group,
    live: null,
    match: {
      id,
      kickoff_at: "2026-11-07T18:00:00Z",
      competition: {
        id: 1,
        name: "La Liga",
        country: "Spain",
        country_code: "ES",
        competition_type: "domestic_league",
        ...comp,
      },
      home: { id: id * 2, name: teams[0] },
      away: { id: id * 2 + 1, name: teams[1] },
    } as MatchSummary,
  };
}

const DAY: MatchItem[] = [
  item("live", { id: 140, name: "La Liga" }, ["Real Betis", "Sevilla"]),
  item("scheduled", { id: 140, name: "La Liga" }, ["Real Madrid", "Getafe"]),
  item("finished", { id: 143, name: "Copa del Rey", competition_type: "domestic_cup" }),
  item("scheduled", { id: 39, name: "Premier League", country: "England", country_code: "GB-ENG" }),
  item("finished", { id: 39, name: "Premier League", country: "England", country_code: "GB-ENG" }),
  item("postponed", { id: 239, name: "Primera A", country: "Colombia", country_code: "CO" }),
];

const ALL: DayFilters = {
  status: "all",
  country: null,
  category: null,
  competition: null,
  query: "",
};
const labels = { international: "Internacional", category: (k: string) => k };
const narrow = (f: Partial<DayFilters>) => narrowDay(DAY, { ...ALL, ...f }, "es", labels);

describe("the day narrowed (plan Partidos, P2 and P3)", () => {
  test("nothing chosen: every row, every count", () => {
    const d = narrow({});
    expect(d.visible).toHaveLength(6);
    expect(d.counts).toEqual({ all: 6, live: 1, upcoming: 2, finished: 2 });
  });

  test("a category that does not play that day is ignored, as a country is (P2)", () => {
    const women = narrow({ category: "women" });
    expect(women.category).toBeNull();
    expect(women.visible).toHaveLength(6);
    const nowhere = narrow({ country: "DE" });
    expect(nowhere.country).toBeNull();
    expect(nowhere.visible).toHaveLength(6);
    // within the country picked: Colombia has no cup that day, so «Copas» is ignored there
    const cupInColombia = narrow({ country: "CO", category: "cup" });
    expect(cupInColombia.category).toBeNull();
    expect(cupInColombia.visible.map((i) => i.match.competition.name)).toEqual(["Primera A"]);
    // a competition of neither: ignored too
    expect(narrow({ country: "CO", competition: 140 }).competition).toBeNull();
  });

  test("the state counts read the country, the category, the competition and the search (P3)", () => {
    expect(narrow({ country: "ES" }).counts).toEqual({ all: 3, live: 1, upcoming: 1, finished: 1 });
    expect(narrow({ category: "cup" }).counts).toEqual({
      all: 1,
      live: 0,
      upcoming: 0,
      finished: 1,
    });
    expect(narrow({ competition: 39 }).counts).toEqual({
      all: 2,
      live: 0,
      upcoming: 1,
      finished: 1,
    });
    expect(narrow({ query: "betis" }).counts).toEqual({
      all: 1,
      live: 1,
      upcoming: 0,
      finished: 0,
    });
    // and the state chosen narrows the rows, never the counts
    const live = narrow({ country: "ES", status: "live" });
    expect(live.visible).toHaveLength(1);
    expect(live.counts.all).toBe(3);
  });

  test("the search finds a team or a competition, by its name or its country", () => {
    expect(narrow({ query: "premier" }).visible).toHaveLength(2);
    expect(narrow({ query: "colombia" }).visible).toHaveLength(1);
    expect(narrow({ query: "  real  " }).query).toBe("real");
    expect(narrow({ query: "real" }).visible).toHaveLength(2);
  });

  test("the pickers offer what plays: categories within the country", () => {
    expect(narrow({}).categories.map((c) => [c.key, c.count])).toEqual([
      ["league", 5],
      ["cup", 1],
    ]);
    expect(narrow({ country: "GB-ENG" }).categories.map((c) => c.key)).toEqual(["league"]);
    expect(narrow({ category: "cup" }).options.map((o) => o.id)).toEqual([143]);
  });
});
