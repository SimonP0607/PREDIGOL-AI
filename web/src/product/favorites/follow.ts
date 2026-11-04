/**
 * What a reader follows, as the pages apply it on top of the common boards (plan UX, A13 and B2; section 38): their
 * favourite leagues and teams - or, while they chose none, the ones suggested for Colombia, labelled - and why a match is
 * theirs, by the API's own rule (fbi.api.services.follows): a followed team plays it - the nearer reason, both named when
 * both are followed, home first - or it belongs to a followed league. The boards stay the same for every reader: this
 * only chooses what a page shows first and says why. Pure: no React, no fetching.
 *
 * FBI_PERSONALIZATION=0 (``personalization`` false): no follow set, and every page shows its common view.
 */
import type { FavoritesView } from "@/lib/api/v1/types_favorites";
import type { FollowReason } from "@/lib/api/v1/types_today";
import type { Why } from "@/product/home/why";

/** What a page shows: the reader's own (their leagues and teams) or every match. */
export type Scope = "mine" | "all";

export interface FollowSet {
  /** A followed league and its place in the reader's order (the order they chose them). */
  leagues: ReadonlyMap<number, number>;
  teams: ReadonlySet<number>;
  /** None chosen: the suggested ones, labelled as suggested. */
  suggested: boolean;
}

interface Named {
  id: number;
  name: string;
}

/** Anything with two sides and a league: a match of the day, a pick, a news item's match. */
export interface Followable {
  home: Named;
  away: Named;
  competition: Named;
}

/** The reader's follow set, or null while it is unknown or personalisation is off (the common view). */
export function followSet(view: FavoritesView | null | undefined): FollowSet | null {
  if (!view || !view.personalization) return null;
  return {
    leagues: new Map(view.leagues.map((league, i) => [league.id, i])),
    teams: new Set(view.teams.map((team) => team.id)),
    suggested: view.suggested,
  };
}

/** Why the match is the reader's, or null: not theirs (or no follow set). */
export function reasonOf(m: Followable, follow: FollowSet | null): FollowReason | null {
  if (!follow) return null;
  const names = [m.home, m.away].filter((side) => follow.teams.has(side.id)).map((s) => s.name);
  if (names.length > 0) return { kind: "team", names };
  if (follow.leagues.has(m.competition.id)) return { kind: "league", names: [m.competition.name] };
  return null;
}

/** The chip a page shows: the reason - or «Sugerida» while the reader chose none (Home's own rule, A13). */
export function whyOf(reason: FollowReason | null, suggested: boolean): Why | null {
  if (!reason) return null;
  return suggested ? { kind: "suggested" } : reason;
}

/** The reader's own among these, in the same order. */
export function mine<T extends Followable>(items: readonly T[], follow: FollowSet | null): T[] {
  return follow ? items.filter((it) => reasonOf(it, follow) !== null) : [...items];
}

/**
 * The reader's order of the day's competitions: the ones with a match in play first (as always), then their leagues in
 * the order they chose them, then the rest - the competitions of a followed team - as they came. Stable.
 */
export function followFirst<G extends { competition: { id: number }; live: number }>(
  groups: readonly G[],
  follow: FollowSet | null,
): G[] {
  if (!follow) return [...groups];
  const rank = (g: G) => follow.leagues.get(g.competition.id) ?? Number.MAX_SAFE_INTEGER;
  return [...groups].sort((a, b) => Number(b.live > 0) - Number(a.live > 0) || rank(a) - rank(b));
}
