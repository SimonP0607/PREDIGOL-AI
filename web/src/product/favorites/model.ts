/**
 * A reader's favourites on the page (plan UX, A13 and 3.1; sections 20 and 38): what the picker holds while the reader
 * chooses, pure so a test fixes it. Up to `max` leagues, teams, players and markets (the API's limits: 10, 20, 20 and 5),
 * in the order the reader chose them; at the limit nothing more is added - the picker says so before the reader reaches
 * it, and the API refuses rather than trims. Never a betting profile: only what the reader follows (the markets they read,
 * not what they stake on them).
 */
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import type { FavoritesView, PlayerBadge } from "@/lib/api/v1/types_favorites";
import type { Suggestion } from "@/lib/api/v1/types_personal";
import type { MarketKey } from "@/lib/api/v1/types_records";

export interface Choice {
  leagues: CompetitionBadge[];
  teams: TeamBadge[];
  players: PlayerBadge[];
  markets: MarketKey[];
}

export interface Limits {
  leagues: number;
  teams: number;
  players: number;
  markets: number;
}

/** The API's own limits (fbi/customer/favorites.py) while its answer is not here yet. */
export const DEFAULT_LIMITS: Limits = { leagues: 10, teams: 20, players: 20, markets: 5 };

/** The markets a reader can follow, in the order the product lists them (fbi.customer.favorites.FOLLOWABLE_MARKETS). */
export const MARKETS: readonly MarketKey[] = ["1X2", "OU", "BTTS", "AH", "DC"];

/** A market key the reader can follow, or null (a market PrediGol lists but the API does not offer to follow). */
export function followableMarket(key: string): MarketKey | null {
  return (MARKETS as readonly string[]).includes(key) ? (key as MarketKey) : null;
}

export function choiceOf(view: FavoritesView): Choice {
  return {
    leagues: [...view.leagues],
    teams: [...view.teams],
    players: [...(view.players ?? [])],
    markets: [...(view.markets ?? [])],
  };
}

/**
 * What the reader had chosen, for `changes`: the suggested leagues and teams were never theirs (saving them counts as
 * adding them), their players and markets always were.
 */
export function beforeOf(view: FavoritesView): Choice {
  const choice = choiceOf(view);
  return view.suggested ? { ...choice, leagues: [], teams: [] } : choice;
}

export function limitsOf(view: FavoritesView | undefined): Limits {
  return view
    ? {
        leagues: view.max_leagues,
        teams: view.max_teams,
        players: view.max_players ?? DEFAULT_LIMITS.players,
        markets: view.max_markets ?? DEFAULT_LIMITS.markets,
      }
    : DEFAULT_LIMITS;
}

function toggle<T extends { id: number }>(list: readonly T[], item: T, max: number): T[] {
  if (list.some((x) => x.id === item.id)) return list.filter((x) => x.id !== item.id);
  if (list.length >= max) return [...list];
  return [...list, item];
}

/** Adds the league (at the end: the reader's order) or takes it away; at the limit nothing is added. */
export function toggleLeague(choice: Choice, league: CompetitionBadge, limits: Limits): Choice {
  return { ...choice, leagues: toggle(choice.leagues, league, limits.leagues) };
}

export function toggleTeam(choice: Choice, team: TeamBadge, limits: Limits): Choice {
  return { ...choice, teams: toggle(choice.teams, team, limits.teams) };
}

export function hasLeague(choice: Choice, id: number): boolean {
  return choice.leagues.some((l) => l.id === id);
}

export function hasTeam(choice: Choice, id: number): boolean {
  return choice.teams.some((tm) => tm.id === id);
}

export function togglePlayer(choice: Choice, player: PlayerBadge, limits: Limits): Choice {
  return { ...choice, players: toggle(choice.players, player, limits.players) };
}

export function hasPlayer(choice: Choice, id: number): boolean {
  return choice.players.some((p) => p.id === id);
}

/** Adds the market (at the end: the reader's order) or takes it away; at the limit nothing is added. */
export function toggleMarket(choice: Choice, market: MarketKey, limits: Limits): Choice {
  if (choice.markets.includes(market))
    return { ...choice, markets: choice.markets.filter((m) => m !== market) };
  if (choice.markets.length >= limits.markets) return { ...choice, markets: [...choice.markets] };
  return { ...choice, markets: [...choice.markets, market] };
}

export function hasMarket(choice: Choice, market: MarketKey): boolean {
  return choice.markets.includes(market);
}

export function full(
  choice: Choice,
  limits: Limits,
): { leagues: boolean; teams: boolean; players: boolean; markets: boolean } {
  return {
    leagues: choice.leagues.length >= limits.leagues,
    teams: choice.teams.length >= limits.teams,
    players: choice.players.length >= limits.players,
    markets: choice.markets.length >= limits.markets,
  };
}

/**
 * The reader's favourites with a suggestion accepted (plan UX, B2): what they see now - the suggested ones while they chose
 * none, so nothing disappears - and it at the end. At the limit nothing is added (the API offers none then).
 */
export function withSuggestion(view: FavoritesView, s: Suggestion): Choice {
  const choice = choiceOf(view);
  const limits = limitsOf(view);
  return s.kind === "league"
    ? toggleLeague(
        choice,
        { id: s.id, name: s.name, country: null, logo_url: null, flag_url: null },
        limits,
      )
    : toggleTeam(choice, { id: s.id, name: s.name, logo_url: null }, limits);
}

/** What the API is sent: ids in the reader's order (the players and the markets too: nothing the reader follows is left out). */
export function bodyOf(choice: Choice): {
  leagues: number[];
  teams: number[];
  players: number[];
  markets: MarketKey[];
} {
  return {
    leagues: choice.leagues.map((l) => l.id),
    teams: choice.teams.map((tm) => tm.id),
    players: choice.players.map((p) => p.id),
    markets: [...choice.markets],
  };
}

/**
 * What is sent when only a player or a market changes (the star in a line-up, the follow of a market): the reader's
 * leagues and teams as they are - and none while the ones they see are the suggested (they were never theirs: saving
 * them would make them the reader's by a tap on a player).
 */
export function extrasBody(view: FavoritesView, next: Choice): ReturnType<typeof bodyOf> {
  const body = bodyOf(next);
  return view.suggested ? { ...body, leagues: [], teams: [] } : body;
}

export type Change =
  { kind: "team" | "competition" | "player"; id: number } | { kind: "market"; market: MarketKey };

/**
 * What a save added and removed, for the product's analytics (favorite_added / favorite_removed - the catalog calls a
 * league a «competition»; a market is named by its key, it has no id). `before` is what the reader had chosen; the
 * suggested ones were never theirs, so saving them counts as adding them.
 */
export function changes(
  before: Choice | null,
  after: Choice,
): { added: Change[]; removed: Change[] } {
  const was: Choice = before ?? { leagues: [], teams: [], players: [], markets: [] };
  const ids = (xs: readonly { id: number }[]) => new Set(xs.map((x) => x.id));
  /** What `to` holds that `from` does not. */
  const newer = (from: Choice, to: Choice): Change[] => {
    const [leagues, teams, players] = [ids(from.leagues), ids(from.teams), ids(from.players)];
    return [
      ...to.leagues
        .filter((l) => !leagues.has(l.id))
        .map((l) => ({ kind: "competition" as const, id: l.id })),
      ...to.teams
        .filter((tm) => !teams.has(tm.id))
        .map((tm) => ({ kind: "team" as const, id: tm.id })),
      ...to.players
        .filter((p) => !players.has(p.id))
        .map((p) => ({ kind: "player" as const, id: p.id })),
      ...to.markets
        .filter((m) => !from.markets.includes(m))
        .map((market) => ({ kind: "market" as const, market })),
    ];
  };
  return { added: newer(was, after), removed: newer(after, was) };
}

export interface CountryGroup {
  country: string | null;
  leagues: CompetitionBadge[];
}

/**
 * The leagues PrediGol follows, by country - the reader's own country first (Colombia, the suggestions' country), then
 * the rest by name, international competitions (no country, or «World») last; inside a group, by name.
 */
export function byCountry(
  leagues: readonly CompetitionBadge[],
  first = "Colombia",
): CountryGroup[] {
  const groups = new Map<string | null, CompetitionBadge[]>();
  for (const l of leagues) {
    const key = l.country && l.country !== "World" ? l.country : null;
    groups.set(key, [...(groups.get(key) ?? []), l]);
  }
  const rank = (c: string | null) => (c === first ? 0 : c === null ? 2 : 1);
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || (a ?? "").localeCompare(b ?? ""))
    .map(([country, ls]) => ({
      country,
      leagues: [...ls].sort((x, y) => x.name.localeCompare(y.name)),
    }));
}

/** The search as the API folds it: lower case, no accents (fbi.customer.favorites.fold). */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Two letters or more (after trimming): the API searches teams only then. */
export function searchable(q: string): boolean {
  return fold(q.trim()).length >= 2;
}

/** Three letters or more (after trimming): the API searches players only then. */
export function playerSearchable(q: string): boolean {
  return fold(q.trim()).length >= 3;
}

/** A league the search names: its name or its country, without accents or case. */
export function leagueMatches(league: CompetitionBadge, q: string): boolean {
  const want = fold(q.trim());
  if (!want) return false;
  return fold(league.name).includes(want) || fold(league.country ?? "").includes(want);
}

/** How many of a group's leagues the reader chose. */
export function chosenIn(choice: Choice, leagues: readonly CompetitionBadge[]): number {
  return leagues.filter((l) => hasLeague(choice, l.id)).length;
}
