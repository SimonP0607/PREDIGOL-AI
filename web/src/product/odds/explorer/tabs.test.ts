/// <reference types="bun" />
/**
 * Two levels (plan Cuotas, section 5): the family tabs - seven and «Más», only those with data, each with its matches -,
 * «Principales» as the five classic markets and the rest of Resultado, «Hándicaps» as a view over every family's handicaps
 * (which stay in their own family), the periods of a market across the families it is filed in, the last market of each
 * tab, what a state falls back to, and the market search.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { fakeFamilies } from "./fake";
import type { OddsFamily } from "./model";
import {
  buildTabs,
  familyFor,
  marketOfTab,
  periodOf,
  readMemory,
  rememberMarket,
  resolveView,
  searchMarkets,
  type ExplorerTab,
  type TabKey,
} from "./tabs";

setLocale("es");
afterAll(() => setLocale("es"));

const tabs = buildTabs(fakeFamilies().families);
const tab = (key: TabKey): ExplorerTab => {
  const found = tabs.find((x) => x.key === key);
  if (!found) throw new Error(`no tab ${key}`);
  return found;
};
const keys = (key: TabKey) => tab(key).markets.map((m) => m.key);

describe("the family tabs", () => {
  test("seven at most and «Más», in the plan's order, other sports left out", () => {
    expect(tabs.map((x) => x.key)).toEqual([
      "main",
      "goals",
      "halves",
      "handicaps",
      "corners",
      "cards",
      "players",
      "more",
    ]);
    expect(tabs.flatMap((x) => x.markets.map((m) => m.key))).not.toContain("other.player_singles");
  });

  test("only the families with prices in the window: no cards, no «Tarjetas»", () => {
    const families: OddsFamily[] = fakeFamilies().families.filter((f) => f.key !== "cards");
    expect(buildTabs(families).map((x) => x.key)).not.toContain("cards");
    expect(buildTabs([])).toEqual([]);
    expect(buildTabs(undefined)).toEqual([]);
  });

  test("each tab carries its number of matches: its family's own where it has one", () => {
    expect(tab("main").fixtures).toBe(5);
    expect(tab("cards").fixtures).toBe(2);
    expect(tab("players").fixtures).toBe(3);
    // «Más»: shots (1), goalkeepers (1) and timing (4) - the busiest of them
    expect(tab("more").fixtures).toBe(4);
    // «Hándicaps»: no family of its own, its busiest market
    expect(tab("handicaps").fixtures).toBe(5);
  });

  test("«Principales» is today's five, in today's order, and the rest of Resultado", () => {
    expect(keys("main")).toEqual([
      "result.1x2",
      "goals.total",
      "goals.btts",
      "result.asian_handicap",
      "result.double_chance",
      "result.draw_no_bet",
      "result.european_handicap",
    ]);
    // a team's total is not one of the five: it stays in «Goles» only
    expect(keys("main")).not.toContain("goals.total.home");
    // a team's market right after the match's: «Más/menos», «Más/menos · Local», then the next market
    expect(keys("goals")).toEqual([
      "goals.total",
      "goals.total.home",
      "goals.btts",
      "goals.correct_score",
    ]);
  });

  test("«Hándicaps» gathers the Asian and European handicaps of every family, which stay in their own", () => {
    expect(keys("handicaps")).toEqual([
      "result.asian_handicap",
      "result.european_handicap",
      "corners.asian_handicap",
    ]);
    expect(keys("main")).toContain("result.asian_handicap");
    expect(keys("corners")).toContain("corners.asian_handicap");
    // a view of several families: the chips carry the whole name
    expect(tab("handicaps").markets.every((m) => !m.own)).toBe(true);
    expect(tab("corners").markets.every((m) => m.own)).toBe(true);
  });

  test("«Más» groups its families in order: shots, goalkeepers, specials, timing...", () => {
    expect(tab("more").markets.map((m) => [m.family, m.key])).toEqual([
      ["shots", "shots.on_target"],
      ["saves", "keeper.saves"],
      ["timing", "goals.first_team_to_score"],
    ]);
  });
});

describe("a market's periods", () => {
  const goalsTotal = (key: TabKey) => tab(key).markets.find((m) => m.key === "goals.total");

  test("are those of every family it is filed in, each with its matches when the families say so exactly", () => {
    expect(goalsTotal("goals")?.periods).toEqual([
      { period: "FT", fixtures: 5 },
      { period: "1H", fixtures: 4 },
    ]);
    const corners = tab("corners").markets.find((m) => m.key === "corners.total");
    expect(corners?.periods).toEqual([
      { period: "FT", fixtures: 5 },
      { period: "1H", fixtures: 3 },
    ]);
    // one entry for two halves: how many matches each has is not known
    const result = tab("main").markets.find((m) => m.key === "result.1x2");
    expect(result?.periods).toEqual([
      { period: "FT", fixtures: 5 },
      { period: "1H", fixtures: null },
      { period: "2H", fixtures: null },
    ]);
  });

  test("open on the tab's own: the match in «Goles», the first half in «Mitades»", () => {
    expect(goalsTotal("goals")?.defaultPeriod).toBe("FT");
    expect(goalsTotal("halves")?.defaultPeriod).toBe("1H");
    const market = goalsTotal("halves")!;
    expect(periodOf(market, "FT")).toBe("FT");
    expect(periodOf(market, "2H")).toBe("1H");
    expect(periodOf(market, null)).toBe("1H");
  });

  test("the match's book is asked for the family the period is filed under", () => {
    const market = goalsTotal("goals")!;
    expect(familyFor(market, "FT")).toBe("goals");
    expect(familyFor(market, "1H")).toBe("goals_half");
  });
});

describe("the last market of each tab", () => {
  test("is remembered, and a tab opens on it while it is there", () => {
    let memory = rememberMarket({}, "corners", "corners.asian_handicap");
    expect(marketOfTab(tab("corners"), null, memory)?.key).toBe("corners.asian_handicap");
    // asked for explicitly: that one
    expect(marketOfTab(tab("corners"), "corners.total", memory)?.key).toBe("corners.total");
    // gone from the window: the tab's first
    memory = rememberMarket(memory, "cards", "cards.asian_handicap");
    expect(marketOfTab(tab("cards"), null, memory)?.key).toBe("cards.total");
    expect(rememberMarket(memory, "cards", "cards.asian_handicap")).toBe(memory);
  });

  test("what comes back from storage is checked: only tabs and market keys", () => {
    expect(readMemory({ corners: "corners.total", nope: "x", goals: 4, cards: "<b>" })).toEqual({
      corners: "corners.total",
    });
    expect(readMemory(null)).toEqual({});
    expect(readMemory("corners")).toEqual({});
  });
});

describe("what a state resolves to", () => {
  test("a tab, market or period the window does not have falls back to the first that is", () => {
    const view = resolveView(tabs, { tab: null, market: null, period: null, line: "main" });
    expect([view?.tab.key, view?.market.key, view?.period]).toEqual(["main", "result.1x2", "FT"]);
    const odd = resolveView(tabs, {
      tab: "corners",
      market: "result.1x2",
      period: "INTERVAL",
      line: "2.5",
    });
    expect([odd?.tab.key, odd?.market.key, odd?.period, odd?.line]).toEqual([
      "corners",
      "corners.total",
      "FT",
      "2.5",
    ]);
  });

  test("a market without lines always shows its main one", () => {
    const view = resolveView(tabs, {
      tab: "main",
      market: "goals.btts",
      period: "FT",
      line: "2.5",
    });
    expect(view?.line).toBe("main");
  });

  test("nothing in the window: no view", () => {
    expect(resolveView([], { tab: "main", market: null, period: null, line: "main" })).toBeNull();
  });
});

describe("the market search", () => {
  const find = (q: string) => searchMarkets(tabs, q).map((h) => `${h.tab}:${h.market.key}`);

  test("«córners» offers the corners markets, in their own tab, the first to jump to", () => {
    expect(find("córners")).toEqual(["corners:corners.total", "corners:corners.asian_handicap"]);
    expect(find("CORNERS")[0]).toBe("corners:corners.total");
  });

  test("«goleador» finds the scorers, «hándicap» every handicap once, in its own family's tab", () => {
    expect(find("goleador")).toEqual(["players:player.anytime_scorer"]);
    expect(find("handicap asiatico")).toEqual([
      "main:result.asian_handicap",
      "corners:corners.asian_handicap",
    ]);
    expect(find("más/menos goles")).toContain("goals:goals.total");
  });

  test("too short, or nothing: no market", () => {
    expect(find("co")).toEqual([]);
    expect(find("Brighton")).toEqual([]);
  });
});
