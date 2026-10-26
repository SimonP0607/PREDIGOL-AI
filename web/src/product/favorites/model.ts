/**
 * A reader's favourites on the page (plan UX, A13; sections 20 and 38): what the picker holds while the reader chooses,
 * pure so a test fixes it. Up to `max` leagues and teams (the API's limits: 10 and 20), in the order the reader chose them;
 * at the limit nothing more is added - the picker says so before the reader reaches it, and the API refuses rather than
 * trims. Never a betting profile: only what the reader follows.
 */
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import type { FavoritesView } from "@/lib/api/v1/types_favorites";

export interface Choice {
  leagues: CompetitionBadge[];
  teams: TeamBadge[];
}

export interface Limits {
  leagues: number;
  teams: number;
}

/** The API's own limits (fbi/customer/favorites.py) while its answer is not here yet. */
export const DEFAULT_LIMITS: Limits = { leagues: 10, teams: 20 };

export function choiceOf(view: FavoritesView): Choice {
  return { leagues: [...view.leagues], teams: [...view.teams] };
}

export function limitsOf(view: FavoritesView | undefined): Limits {
  return view ? { leagues: view.max_leagues, teams: view.max_teams } : DEFAULT_LIMITS;
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

export function full(choice: Choice, limits: Limits): { leagues: boolean; teams: boolean } {
  return {
    leagues: choice.leagues.length >= limits.leagues,
    teams: choice.teams.length >= limits.teams,
  };
}

/** What the API is sent: ids in the reader's order. */
export function bodyOf(choice: Choice): { leagues: number[]; teams: number[] } {
  return { leagues: choice.leagues.map((l) => l.id), teams: choice.teams.map((tm) => tm.id) };
}

export interface Change {
  kind: "team" | "competition";
  id: number;
}

/**
 * What a save added and removed, for the product's analytics (favorite_added / favorite_removed - the catalog calls a
 * league a «competition»). `before` is what the reader had chosen; the suggested ones were never theirs, so saving them
 * counts as adding them.
 */
export function changes(
  before: Choice | null,
  after: Choice,
): { added: Change[]; removed: Change[] } {
  const was = before ?? { leagues: [], teams: [] };
  const ids = (xs: readonly { id: number }[]) => new Set(xs.map((x) => x.id));
  const [wasL, wasT, nowL, nowT] = [
    ids(was.leagues),
    ids(was.teams),
    ids(after.leagues),
    ids(after.teams),
  ];
  return {
    added: [
      ...after.leagues
        .filter((l) => !wasL.has(l.id))
        .map((l) => ({ kind: "competition" as const, id: l.id })),
      ...after.teams
        .filter((tm) => !wasT.has(tm.id))
        .map((tm) => ({ kind: "team" as const, id: tm.id })),
    ],
    removed: [
      ...was.leagues
        .filter((l) => !nowL.has(l.id))
        .map((l) => ({ kind: "competition" as const, id: l.id })),
      ...was.teams
        .filter((tm) => !nowT.has(tm.id))
        .map((tm) => ({ kind: "team" as const, id: tm.id })),
    ],
  };
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
