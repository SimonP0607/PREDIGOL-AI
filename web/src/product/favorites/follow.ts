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
  /**
   * The current team of each followed player (the team of their latest line-up, by name, without accents or case) and the
   * players' names, so that the matches of that team are the reader's too (AP-P04).
   */
  playerTeams: ReadonlyMap<string, string[]>;
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
    playerTeams: playerTeamsOf(view),
    suggested: view.suggested,
  };
}

/** A team's name as two sources write it: no accents, no case, no extra spaces. */
export function teamKey(name: string): string {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function playerTeamsOf(view: FavoritesView): Map<string, string[]> {
  const byTeam = new Map<string, string[]>();
  for (const p of view.players ?? []) {
    if (!p.team) continue;
    const key = teamKey(p.team);
    byTeam.set(key, [...(byTeam.get(key) ?? []), p.name]);
  }
  return byTeam;
}

/** A followed player's team plays the match (AP-P04): the reason says the player, never a team the reader did not choose. */
export interface PlayerReason {
  kind: "player";
  names: string[];
}

/** Why the match is the reader's, or null: not theirs (or no follow set). */
export function reasonOf(
  m: Followable,
  follow: FollowSet | null,
): FollowReason | PlayerReason | null {
  if (!follow) return null;
  const names = [m.home, m.away].filter((side) => follow.teams.has(side.id)).map((s) => s.name);
  if (names.length > 0) return { kind: "team", names };
  if (follow.leagues.has(m.competition.id)) return { kind: "league", names: [m.competition.name] };
  const players = [m.home, m.away].flatMap(
    (side) => follow.playerTeams.get(teamKey(side.name)) ?? [],
  );
  if (players.length > 0) return { kind: "player", names: players };
  return null;
}

/** The chip a page shows: the reason - or «Sugerida» while the reader chose none (Home's own rule, A13). */
export function whyOf(reason: FollowReason | PlayerReason | null, suggested: boolean): Why | null {
  if (!reason) return null;
  return suggested ? { kind: "suggested" } : reason;
}

/**
 * Where «Todos · Mis favoritos» opens (AP-P04): what the reader chose stays; otherwise «Mis favoritos» only when they chose
 * favourites (not the suggested ones) and one of them plays that day - never a page that looks empty. No follow set: everything.
 */
export function defaultScope(
  follow: FollowSet | null,
  chosen: Scope | null,
  ownCount: number,
): Scope {
  if (!follow) return "all";
  if (chosen) return chosen;
  return !follow.suggested && ownCount > 0 ? "mine" : "all";
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
