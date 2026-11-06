/// <reference types="bun" />
/**
 * Plan UX, B2 (section 38): what the reader's favourites and own use order, filter and suggest on the pages - always with
 * the reason, never a pick, a probability or a price. Why a match is theirs (the API's own rule), the follow set and its
 * absence with personalisation off, the day's competitions in the reader's order, the switch with its counts, the
 * markets in the reader's order with the rule said, and a suggestion accepted without losing anything. Two accounts with
 * different favourites in the browser: e2e/personal.spec.ts.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { FavoritesView } from "@/lib/api/v1/types_favorites";
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import { orderBoards, orderSentence, viewsText } from "@/product/match/marketOrder";
import { followFirst, followSet, mine, reasonOf, whyOf, type Followable } from "./follow";
import { withSuggestion } from "./model";
import { ScopeSwitch } from "./ScopeSwitch";
import { WhyChip } from "./WhyChip";

const league = (id: number, name: string): CompetitionBadge => ({
  id,
  name,
  country: "Colombia",
  logo_url: null,
  flag_url: null,
});
const team = (id: number, name: string): TeamBadge => ({ id, name, logo_url: null });

function view(over: Partial<FavoritesView> = {}): FavoritesView {
  return {
    leagues: [league(1, "Liga BetPlay"), league(2, "Premier League")],
    teams: [team(10, "Atlético Nacional")],
    suggested: false,
    max_leagues: 10,
    max_teams: 20,
    max_players: 20,
    max_markets: 5,
    players: [],
    markets: [],
    personalization: true,
    ...over,
  };
}

function match(home: [number, string], away: [number, string], comp: [number, string]): Followable {
  return {
    home: { id: home[0], name: home[1] },
    away: { id: away[0], name: away[1] },
    competition: { id: comp[0], name: comp[1] },
  };
}

const NACIONAL: [number, string] = [10, "Atlético Nacional"];
const MILLOS: [number, string] = [11, "Millonarios"];
const INTER: [number, string] = [20, "Inter"];
const MILAN: [number, string] = [21, "Milan"];
const BETPLAY: [number, string] = [1, "Liga BetPlay"];
const SUDAMERICANA: [number, string] = [7, "Copa Sudamericana"];
const SERIE: [number, string] = [3, "Serie A"];

describe("why a match is the reader's (the API's rule: fbi.api.services.follows)", () => {
  test("a team they follow first - both, home first - then a league they follow; otherwise not theirs", () => {
    const follow = followSet(
      view({ teams: [team(11, "Millonarios"), team(10, "Atlético Nacional")] }),
    );
    expect(reasonOf(match(NACIONAL, MILLOS, BETPLAY), follow)).toEqual({
      kind: "team",
      names: ["Atlético Nacional", "Millonarios"],
    });
    expect(reasonOf(match(NACIONAL, [99, "Boca"], SUDAMERICANA), follow)).toEqual({
      kind: "team",
      names: ["Atlético Nacional"],
    });
    expect(reasonOf(match([30, "Junior"], [31, "Medellín"], BETPLAY), follow)).toEqual({
      kind: "league",
      names: ["Liga BetPlay"],
    });
    expect(reasonOf(match(INTER, MILAN, SERIE), follow)).toBeNull();
  });

  test("personalisation off, or nothing known yet: no follow set - the common view", () => {
    expect(followSet(view({ personalization: false }))).toBeNull();
    expect(followSet(undefined)).toBeNull();
    expect(reasonOf(match(NACIONAL, MILLOS, BETPLAY), null)).toBeNull();
    const all = [match(NACIONAL, MILLOS, BETPLAY), match(INTER, MILAN, SERIE)];
    expect(mine(all, null)).toEqual(all);
  });

  test("the chip says «Sugerida» while the reader chose none, and the reason once they did", () => {
    const reason = { kind: "team" as const, names: ["Atlético Nacional"] };
    expect(whyOf(reason, true)).toEqual({ kind: "suggested" });
    expect(whyOf(reason, false)).toEqual(reason);
    expect(whyOf(null, false)).toBeNull();
    setLocale("es");
    const es = renderToStaticMarkup(<WhyChip why={reason} testId="match-why" />);
    expect(es).toContain("Sigues a Atlético Nacional");
    expect(es).toContain('data-testid="match-why"');
    expect(es).toContain("Te mostramos este partido porque sigues a Atlético Nacional.");
    setLocale("en");
    expect(
      renderToStaticMarkup(<WhyChip why={{ kind: "league", names: ["Liga BetPlay"] }} />),
    ).toContain("Your league");
    setLocale("es");
  });
});

describe("the day in the reader's order", () => {
  test("what is in play first, then their leagues in the order they chose, then the rest as they came", () => {
    const follow = followSet(
      view({ leagues: [league(2, "Premier League"), league(1, "Liga BetPlay")] }),
    );
    const g = (id: number, live = 0) => ({ competition: { id }, live });
    const groups = [g(5), g(1), g(9, 1), g(2), g(6)];
    expect(followFirst(groups, follow).map((x) => x.competition.id)).toEqual([9, 2, 1, 5, 6]);
    expect(followFirst(groups, null).map((x) => x.competition.id)).toEqual([5, 1, 9, 2, 6]);
  });

  test("the reader's own among all, in the same order", () => {
    const follow = followSet(view());
    const all = [
      match(INTER, MILAN, SERIE),
      match(NACIONAL, [99, "Boca"], SUDAMERICANA),
      match(MILLOS, [30, "Junior"], BETPLAY),
    ];
    expect(mine(all, follow)).toEqual([all[1]!, all[2]!]);
  });
});

describe("the switch: the reader's own or all, both counted", () => {
  test("«Tus ligas · 3» and «Todos · 12» - «Sugeridas» while they chose none - the pressed one said", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <ScopeSwitch
        value="mine"
        onChange={() => {}}
        mine={3}
        all={12}
        suggested={false}
        ns="matches"
        testId="s"
      />,
    );
    expect(html).toContain("Tus ligas · 3");
    expect(html).toContain("Todos · 12");
    expect(html).toMatch(/aria-pressed="true"[^>]*data-testid="s-mine"/);
    expect(html).toMatch(/aria-pressed="false"[^>]*data-testid="s-all"/);
    const picks = renderToStaticMarkup(
      <ScopeSwitch
        value="all"
        onChange={() => {}}
        mine={0}
        all={5}
        suggested
        ns="picks"
        testId="p"
      />,
    );
    expect(picks).toContain("Sugeridas · 0");
    expect(picks).toContain("Todas · 5");
    setLocale("en");
    expect(
      renderToStaticMarkup(
        <ScopeSwitch
          value="mine"
          onChange={() => {}}
          mine={2}
          all={9}
          suggested={false}
          ns="matches"
          testId="s"
        />,
      ),
    ).toContain("Your leagues · 2");
    setLocale("es");
  });
});

describe("the markets in the reader's order (GET /me/personal)", () => {
  test("theirs first in their order, the rest in the usual order; none: the usual order", () => {
    const boards = ["1X2", "OU", "BTTS", "AH", "DC"].map((market) => ({ market }));
    expect(orderBoards(boards, ["DC", "OU"]).map((b) => b.market)).toEqual([
      "DC",
      "OU",
      "1X2",
      "BTTS",
      "AH",
    ]);
    expect(orderBoards(boards, []).map((b) => b.market)).toEqual(["1X2", "OU", "BTTS", "AH", "DC"]);
    expect(orderBoards([{ market: "BTTS" }], ["OU"]).map((b) => b.market)).toEqual(["BTTS"]);
  });

  test("the rule said in words: each of their markets and how many times", () => {
    setLocale("es");
    const views = [
      { market: "OU" as const, views: 3 },
      { market: "BTTS" as const, views: 2 },
    ];
    expect(viewsText(views)).toMatch(/\(3\) y .*\(2\)$/);
    expect(orderSentence(views)).toMatch(
      /^Primero, los mercados que más consultas: .*\(3\) y .*\(2\)\.$/,
    );
    setLocale("en");
    expect(orderSentence(views)).toMatch(
      /^First, the markets you check most: .*\(3\) and .*\(2\)\.$/,
    );
    setLocale("es");
  });
});

describe("a suggestion accepted", () => {
  test("saves what the reader sees now and it at the end - the suggested ones too while they chose none", () => {
    const serie = { kind: "league" as const, id: 3, name: "Serie A", matches: 4, days: 3 };
    const mineNow = withSuggestion(view(), serie);
    expect(mineNow.leagues.map((l) => l.id)).toEqual([1, 2, 3]);
    expect(mineNow.teams.map((x) => x.id)).toEqual([10]);
    const cold = withSuggestion(view({ suggested: true }), {
      kind: "team",
      id: 20,
      name: "Inter",
      matches: 3,
      days: 2,
    });
    expect(cold.leagues.map((l) => l.id)).toEqual([1, 2]);
    expect(cold.teams.map((x) => x.id)).toEqual([10, 20]);
    const full = view({ max_leagues: 2 });
    expect(withSuggestion(full, serie).leagues.map((l) => l.id)).toEqual([1, 2]);
  });
});
