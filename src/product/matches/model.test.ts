/// <reference types="bun" />
/**
 * The Matches page's data rules: live follow on top of result rows, state filters,
 * grouping order, search, the day read page by page, and labels for every state.
 */
import { afterEach, describe, expect, spyOn, test } from "bun:test";
import { v1 } from "@/lib/api/v1/client";
import type { Envelope, MatchSummary } from "@/lib/api/v1/types";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { hasKey, setLocale } from "@/lib/i18n";
import { countryLabel } from "./country";
import {
  competitionOptions,
  groupByCompetition,
  matchesText,
  rowScore,
  rowWinner,
  statusCounts,
  toItems,
  wantsLiveBoard,
} from "./model";
import { fetchDay } from "./query";
import { isInPlay, liveLabel, phaseOf, shortStatus } from "./status";
import { readView, writeView } from "./viewState";

afterEach(() => setLocale("es"));

let nextId = 1;
function match(over: Partial<MatchSummary> & { comp?: Partial<MatchSummary["competition"]> }) {
  const { comp, ...rest } = over;
  const id = rest.id ?? nextId++;
  const m: MatchSummary = {
    id,
    provider_fixture_id: id,
    kickoff_at: "2026-10-03T18:00:00Z",
    status_short: "NS",
    status_group: "scheduled",
    round: null,
    competition: {
      id: 1,
      name: "Eerste Divisie",
      country: "Netherlands",
      provider_league_id: 89,
      season: 2026,
      competition_type: "domestic_league",
      is_tracked: true,
      logo_url: null,
      flag_url: null,
      country_code: "NL",
      ...comp,
    },
    home: { id: 10, name: "Waalwijk", provider_team_id: 417, logo_url: null },
    away: { id: 11, name: "Emmen", provider_team_id: 208, logo_url: null },
    score: null,
    odds: {
      snapshots: 0,
      bookmakers: 0,
      markets: 0,
      first_captured_at: null,
      last_captured_at: null,
      near_close_snapshots: 0,
    },
    predictions: 0,
    awaiting_result: false,
    ...rest,
  };
  return m;
}

function follow(over: Partial<LiveMatch> & { fixture_id: number }): LiveMatch {
  return {
    kickoff_at: "2026-10-03T18:00:00Z",
    competition: "Eerste Divisie",
    country: "Netherlands",
    home: { id: 10, name: "Waalwijk" },
    away: { id: 11, name: "Emmen" },
    status: "2H",
    elapsed: 52,
    extra: null,
    goals_home: 1,
    goals_away: 0,
    state_at: "2026-10-03T18:58:17Z",
    state_source: "fixture_feed",
    state_age_seconds: 10,
    odds_feed_at: null,
    markets_offered: null,
    values_suspended: null,
    events: [],
    statistics: [],
    main_odds: [],
    data_status: "ok",
    ...over,
  };
}

const score = (home: number, away: number, pens?: [number, number]) => ({
  home,
  away,
  ht_home: null,
  ht_away: null,
  et_home: null,
  et_away: null,
  pen_home: pens ? pens[0] : null,
  pen_away: pens ? pens[1] : null,
  outcome_1x2:
    home > away ? ("Home" as const) : home < away ? ("Away" as const) : ("Draw" as const),
  total_goals: home + away,
  btts: home > 0 && away > 0,
  source_payload_hash: null,
  source_fetched_at: null,
});

describe("status", () => {
  test("both feeds end up as one short code", () => {
    expect(shortStatus("Halftime")).toBe("HT");
    expect(shortStatus("Not Started")).toBe("NS");
    expect(shortStatus("First Half")).toBe("1H");
    expect(shortStatus("Second Half")).toBe("2H");
    expect(shortStatus("2h")).toBe("2H");
    expect(shortStatus("?")).toBe("");
    expect(shortStatus(null)).toBe("");
  });

  test("phases", () => {
    expect(phaseOf("NS")).toBe("pre");
    expect(phaseOf("HT")).toBe("pause");
    expect(isInPlay("HT")).toBe(true);
    expect(isInPlay("1H")).toBe(true);
    expect(isInPlay("NS")).toBe(false);
    expect(isInPlay("FT")).toBe(false);
  });

  test("a short live label: the minute when known, the state when it is a break", () => {
    expect(liveLabel("2H", 52, null)).toBe("52'");
    expect(liveLabel("2H", 90, 4)).toBe("90+4'");
    expect(liveLabel("Halftime", 45, null)).toBe("Desc.");
    expect(liveLabel("1H", null, null)).toBe("1T");
    expect(liveLabel("1H", 0, null)).toBe("1T");
    expect(liveLabel("?", null, null)).toBe("Vivo");
    setLocale("en");
    expect(liveLabel("Halftime", 45, null)).toBe("HT");
    expect(liveLabel("2H", null, null)).toBe("2H");
  });

  test("every state a label can name exists in both languages", () => {
    for (const code of ["1H", "2H", "HT", "ET", "BT", "P", "INT", "SUSP", "LIVE", "FT", "TBD"]) {
      expect(hasKey(`matches.clock.${code}`, "es")).toBe(true);
      expect(hasKey(`matches.clock.${code}`, "en")).toBe(true);
    }
    for (const code of ["BT", "P", "INT", "SUSP"]) {
      expect(hasKey(`live.clock.${code}`, "es")).toBe(true);
      expect(hasKey(`live.clock.${code}`, "en")).toBe(true);
    }
    for (const code of ["GB-ENG", "GB-SCT", "GB-WLS", "GB-NIR"]) {
      expect(hasKey(`matches.country.${code}`, "es")).toBe(true);
      expect(hasKey(`matches.country.${code}`, "en")).toBe(true);
    }
  });
});

describe("country", () => {
  test("translated from the ISO code; home nations from the catalog; World hidden", () => {
    expect(countryLabel("Netherlands", "NL")).toBe("Países Bajos");
    expect(countryLabel("England", "GB-ENG")).toBe("Inglaterra");
    expect(countryLabel("World", null)).toBeNull();
    expect(countryLabel("Kosovo", null)).toBe("Kosovo");
    setLocale("en");
    expect(countryLabel("England", "GB-ENG")).toBe("England");
  });
});

describe("live follow on top of result rows", () => {
  test("a live row takes score and minute from the board", () => {
    const row = match({ id: 100, status_short: "2H", status_group: "live" });
    const [item] = toItems([row], [follow({ fixture_id: 100, goals_home: 3, goals_away: 0 })]);
    expect(item?.group).toBe("live");
    expect(item && rowScore(item)).toEqual({ home: 3, away: 0 });
  });

  test("a row the board shows in play is live even before the row catches up", () => {
    const row = match({ id: 101, status_short: "NS", status_group: "scheduled" });
    const [item] = toItems([row], [follow({ fixture_id: 101, status: "First Half", elapsed: 2 })]);
    expect(item?.group).toBe("live");
  });

  test("priced before kick-off is not live; finished stays finished", () => {
    const soon = match({ id: 102 });
    const done = match({
      id: 103,
      status_short: "FT",
      status_group: "finished",
      score: score(2, 1),
    });
    const items = toItems(
      [soon, done],
      [
        follow({ fixture_id: 102, status: "Not Started", elapsed: 0 }),
        follow({ fixture_id: 103, status: "2H", elapsed: 90 }),
      ],
    );
    expect(items.map((i) => i.group)).toEqual(["scheduled", "finished"]);
    expect(items[1] && rowScore(items[1])).toEqual({ home: 2, away: 1 });
  });

  test("a suspended match is in play; an abandoned one is never live, whatever the board says", () => {
    const suspended = match({
      id: 105,
      status_short: "SUSP",
      status_group: "postponed",
      phase: "suspended",
    });
    const abandoned = match({
      id: 106,
      status_short: "ABD",
      status_group: "cancelled",
      phase: "abandoned",
    });
    const items = toItems(
      [suspended, abandoned],
      [follow({ fixture_id: 106, status: "2H", elapsed: 70 })],
    );
    expect(items.map((i) => i.group)).toEqual(["live", "cancelled"]);
    expect(items[1]?.live).toBeNull();
  });

  test("past kick-off without a result is its own state, not upcoming", () => {
    const stuck = match({ id: 104, awaiting_result: true });
    const [item] = toItems([stuck], []);
    expect(item?.group).toBe("awaiting");
    expect(item && rowScore(item)).toBeNull();
  });

  test("counts per state chip", () => {
    const items = toItems(
      [
        match({ status_group: "live", status_short: "1H" }),
        match({}),
        match({ status_group: "finished", status_short: "FT", score: score(0, 0) }),
        match({ status_group: "postponed", status_short: "PST" }),
        match({ awaiting_result: true }),
      ],
      [],
    );
    expect(statusCounts(items)).toEqual({ all: 5, live: 1, upcoming: 1, finished: 1 });
  });

  test("the board is read only when something may be in play", () => {
    const now = Date.parse("2026-10-03T18:30:00Z");
    expect(wantsLiveBoard([match({ kickoff_at: "2026-10-04T18:00:00Z" })], now)).toBe(false);
    expect(wantsLiveBoard([match({ kickoff_at: "2026-10-03T18:35:00Z" })], now)).toBe(true);
    expect(wantsLiveBoard([match({ status_group: "live", status_short: "1H" })], now)).toBe(true);
  });
});

describe("winner", () => {
  test("goals decide, penalties decide a shoot-out", () => {
    const won = toItems([match({ status_group: "finished", score: score(2, 1) })], [])[0];
    const pens = toItems([match({ status_group: "finished", score: score(1, 1, [3, 4]) })], [])[0];
    const draw = toItems([match({ status_group: "finished", score: score(0, 0) })], [])[0];
    expect(won && rowWinner(won)).toBe("home");
    expect(pens && rowWinner(pens)).toBe("away");
    expect(draw && rowWinner(draw)).toBe("draw");
  });
});

describe("grouping and search", () => {
  test("live competitions first, then tracked, then by name; kick-off order inside", () => {
    const items = toItems(
      [
        match({ id: 1, comp: { id: 3, name: "Zeta League", is_tracked: true } }),
        match({ id: 2, comp: { id: 2, name: "Alpha Cup", is_tracked: false } }),
        match({
          id: 3,
          kickoff_at: "2026-10-03T20:00:00Z",
          comp: { id: 4, name: "Beta League", is_tracked: true },
        }),
        match({
          id: 4,
          kickoff_at: "2026-10-03T16:00:00Z",
          comp: { id: 4, name: "Beta League", is_tracked: true },
        }),
        match({
          id: 5,
          status_group: "live",
          status_short: "1H",
          comp: { id: 5, name: "Omega League", is_tracked: false },
        }),
      ],
      [],
    );
    const groups = groupByCompetition(items, "es-ES");
    expect(groups.map((g) => g.competition.name)).toEqual([
      "Omega League",
      "Beta League",
      "Zeta League",
      "Alpha Cup",
    ]);
    expect(groups[1]?.items.map((i) => i.match.id)).toEqual([4, 3]);
    expect(groups[0]?.live).toBe(1);
  });

  test("search ignores accents and case, across teams and competition", () => {
    const [item] = toItems(
      [
        match({
          home: { id: 1, name: "Atlético Goianiense", provider_team_id: 1 },
          comp: { name: "Serie B", country: "Brazil", country_code: "BR" },
        }),
      ],
      [],
    );
    if (!item) throw new Error("no item");
    expect(matchesText(item, "atletico")).toBe(true);
    expect(matchesText(item, "SERIE b")).toBe(true);
    expect(matchesText(item, "brasil")).toBe(true);
    expect(matchesText(item, "emmen goianiense")).toBe(true);
    expect(matchesText(item, "barcelona")).toBe(false);
  });

  test("competition options come from the loaded rows, by name, with counts", () => {
    const items = toItems(
      [
        match({ comp: { id: 7, name: "FA Cup", country: "England", country_code: "GB-ENG" } }),
        match({ comp: { id: 7, name: "FA Cup", country: "England", country_code: "GB-ENG" } }),
        match({ comp: { id: 8, name: "Copa del Rey", country: "Spain", country_code: "ES" } }),
      ],
      [],
    );
    expect(competitionOptions(items, "es-ES")).toEqual([
      { id: 8, name: "Copa del Rey", country: "España", count: 1 },
      { id: 7, name: "FA Cup", country: "Inglaterra", count: 2 },
    ]);
  });
});

describe("a day read page by page", () => {
  test("pages past the 200-row cap are fetched and joined once", async () => {
    const all = Array.from({ length: 202 }, (_, i) => match({ id: 5000 + i }));
    const calls: number[] = [];
    const spy = spyOn(v1, "matches").mockImplementation(async (q = {}) => {
      const offset = q.offset ?? 0;
      calls.push(offset);
      // The second page repeats one row of the first, as if a row moved in between.
      const data = offset === 0 ? all.slice(0, 200) : all.slice(199, 202);
      const page: Envelope<MatchSummary[]> = {
        status: "ok",
        data,
        reason: null,
        meta: {
          generated_at: "2026-10-03T18:58:28Z",
          api_version: "v1",
          count: data.length,
          total: 202,
          limit: 200,
          offset,
          data_as_of: null,
        },
      };
      return page;
    });
    try {
      const day = await fetchDay("2026-10-03T05:00:00.000Z", "2026-10-04T05:00:00.000Z");
      expect(calls).toEqual([0, 200]);
      expect(day.rows).toHaveLength(202);
      expect(new Set(day.rows.map((r) => r.id)).size).toBe(202);
      expect(day.total).toBe(202);
    } finally {
      spy.mockRestore();
    }
  });
});

describe("the view kept for the tab", () => {
  test("restored on the same day, dropped once the day has changed", () => {
    const store = new Map<string, string>();
    const g = globalThis as unknown as { window?: unknown };
    const before = g.window;
    g.window = {
      sessionStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    };
    try {
      writeView({
        day: "2026-01-02",
        status: "live",
        competition: 7,
        query: "Emmen",
        country: "NL",
        category: "league",
      });
      expect(readView()).toEqual({
        day: "2026-01-02",
        status: "live",
        competition: 7,
        query: "Emmen",
        country: "NL",
        category: "league",
      });
      const saved = JSON.parse(store.get("predigol.matches.view") ?? "{}") as object;
      store.set("predigol.matches.view", JSON.stringify({ ...saved, savedOn: "1999-01-01" }));
      expect(readView().status).toBe("all");
    } finally {
      g.window = before;
    }
  });
});
