/**
 * What the Matches page does with the rows of one local day: put the live follow on top
 * of the result rows, count and filter by state, and group by competition.
 * Pure functions - no React, no fetching - so they can be tested on their own.
 */
import type { CompetitionRef, MatchSummary, StatusGroup } from "@/lib/api/v1/types";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { countryLabel } from "./country";
import { matchesTeamOrCompetition } from "./facets";
import { isInPlay, isOffPhase, matchPhaseOf, shortStatus } from "./status";

/** A row's state for the reader: the stored group, unless the live follow knows better. */
export type RowGroup = StatusGroup | "awaiting";

export interface MatchItem {
  match: MatchSummary;
  group: RowGroup;
  /** The live follow of this match while it is being played. */
  live: LiveMatch | null;
}

export type StatusFilter = "all" | "live" | "upcoming" | "finished";
export const STATUS_FILTERS: readonly StatusFilter[] = ["all", "live", "upcoming", "finished"];

export interface CompetitionGroup {
  id: number;
  competition: CompetitionRef;
  items: MatchItem[];
  live: number;
}

/**
 * Whether the live board is worth reading for these rows: something is in play, or has
 * just kicked off (a row lags the live follow by a minute or two).
 */
export function wantsLiveBoard(rows: readonly MatchSummary[], now: number): boolean {
  return rows.some((m) => {
    if (m.status_group === "live") return true;
    if (m.status_group !== "scheduled") return false;
    const ko = Date.parse(m.kickoff_at);
    return ko <= now + 10 * 60_000 && ko >= now - 4 * 3_600_000;
  });
}

/**
 * A result row only says "live" (and has no score yet): the live board adds the score and
 * minute. A row the board shows in play counts as live even if the row has not caught up;
 * a row already finished, postponed or cancelled keeps its own state.
 */
export function toItems(
  rows: readonly MatchSummary[],
  board: readonly LiveMatch[],
  now: number = Date.now(),
): MatchItem[] {
  const byId = new Map(board.map((m) => [m.fixture_id, m]));
  return rows.map((match) => {
    const follow = byId.get(match.id) ?? null;
    // One rule for every screen (fbi.core.match_state): a suspended match is still in play,
    // though it is stored with the postponed ones; nothing not played to the end is "live".
    const phase = matchPhaseOf(match.status_short, match.kickoff_at, now, match.phase);
    const settled = phase === "finished" || isOffPhase(phase);
    const inPlay = follow !== null && !settled && isInPlay(shortStatus(follow.status));
    const group: RowGroup =
      inPlay || phase === "suspended"
        ? "live"
        : match.awaiting_result && !settled
          ? "awaiting"
          : match.status_group;
    return { match, group, live: inPlay ? follow : null };
  });
}

export function inStatus(group: RowGroup, filter: StatusFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "live":
      return group === "live";
    case "upcoming":
      return group === "scheduled";
    case "finished":
      return group === "finished";
  }
}

export function statusCounts(items: readonly MatchItem[]): Record<StatusFilter, number> {
  const counts: Record<StatusFilter, number> = { all: 0, live: 0, upcoming: 0, finished: 0 };
  for (const it of items) {
    for (const f of STATUS_FILTERS) if (inStatus(it.group, f)) counts[f] += 1;
  }
  return counts;
}

/** Lower case without accents: "Atlético" is found by "atletico". */
export function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** A team, or the competition by its name or country (facets.matchesTeamOrCompetition). */
export function matchesText(item: MatchItem, query: string): boolean {
  return matchesTeamOrCompetition(item.match, query);
}

export interface CompetitionOption {
  id: number;
  name: string;
  country: string | null;
  count: number;
}

/** The competitions present in the loaded rows, by name. */
export function competitionOptions(
  items: readonly MatchItem[],
  locale: string,
): CompetitionOption[] {
  const byId = new Map<number, CompetitionOption>();
  for (const { match } of items) {
    const c = match.competition;
    const known = byId.get(c.id);
    if (known) known.count += 1;
    else
      byId.set(c.id, {
        id: c.id,
        name: c.name,
        country: countryLabel(c.country, c.country_code),
        count: 1,
      });
  }
  return [...byId.values()].sort(
    (a, b) =>
      a.name.localeCompare(b.name, locale) ||
      (a.country ?? "").localeCompare(b.country ?? "", locale) ||
      a.id - b.id,
  );
}

function kickoffOrder(a: MatchItem, b: MatchItem): number {
  return Date.parse(a.match.kickoff_at) - Date.parse(b.match.kickoff_at) || a.match.id - b.match.id;
}

/**
 * The owner's priority group of a competition (comp-priority-v1, sent by GET /matches): 1 the Champions League and
 * the top leagues, 2 the continental club cups, 3 the national teams' tournaments, 4 the rest. An API older than the
 * field sends none: every competition is then in group 4 and the list is ordered by name, as before.
 */
export function priorityOf(c: Pick<CompetitionRef, "priority_group">): number {
  const g = c.priority_group;
  return typeof g === "number" && Number.isInteger(g) && g >= 1 && g <= 4 ? g : 4;
}

/**
 * Competitions with a match in play first, then the owner's priority groups 1, 2 and 3, then the rest (group 4);
 * the tracked ones first and then by name within a group, kick-off inside (plan Partidos, P1). The reader's own leagues go before the groups
 * (followFirst, applied after this). LaLiga or the Champions League no longer fall under «1. Division» (Cyprus).
 */
export function groupByCompetition(
  items: readonly MatchItem[],
  locale: string,
): CompetitionGroup[] {
  const byId = new Map<number, CompetitionGroup>();
  for (const item of items) {
    const c = item.match.competition;
    let g = byId.get(c.id);
    if (!g) {
      g = { id: c.id, competition: c, items: [], live: 0 };
      byId.set(c.id, g);
    }
    g.items.push(item);
    if (item.group === "live") g.live += 1;
  }
  const groups = [...byId.values()];
  for (const g of groups) g.items.sort(kickoffOrder);
  return groups.sort(
    (a, b) =>
      Number(b.live > 0) - Number(a.live > 0) ||
      priorityOf(a.competition) - priorityOf(b.competition) ||
      Number(b.competition.is_tracked) - Number(a.competition.is_tracked) ||
      a.competition.name.localeCompare(b.competition.name, locale) ||
      (a.competition.country ?? "").localeCompare(b.competition.country ?? "", locale) ||
      a.id - b.id,
  );
}

function sameLive(a: LiveMatch | null, b: LiveMatch | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.status === b.status &&
    a.elapsed === b.elapsed &&
    a.extra === b.extra &&
    a.goals_home === b.goals_home &&
    a.goals_away === b.goals_away
  );
}

/**
 * Whether a list row would draw the same (plan Partidos, P5): every poll of /live builds new items, but a row reads
 * only its stored match (the same object while the day's answer has not changed it), its state, and the live
 * score and minute - the events, statistics and prices of the live follow do not show in the list.
 */
export function sameItem(a: MatchItem, b: MatchItem): boolean {
  return a.match === b.match && a.group === b.group && sameLive(a.live, b.live);
}

/** Goals to show for a row: the live follow while in play, the stored result once over. */
export function rowScore(item: MatchItem): { home: number; away: number } | null {
  if (item.live) {
    const { goals_home: h, goals_away: a } = item.live;
    return h !== null && a !== null ? { home: h, away: a } : null;
  }
  const s = item.match.score;
  if (!s || item.group === "scheduled" || item.group === "awaiting") return null;
  return { home: s.home, away: s.away };
}

/** "home" | "away" won (penalties decide a shoot-out), "draw", or null while not over. */
export function rowWinner(item: MatchItem): "home" | "away" | "draw" | null {
  const s = item.match.score;
  if (item.group !== "finished" || !s) return null;
  if (s.pen_home !== null && s.pen_away !== null && s.pen_home !== s.pen_away) {
    return s.pen_home > s.pen_away ? "home" : "away";
  }
  if (s.home === s.away) return "draw";
  return s.home > s.away ? "home" : "away";
}
