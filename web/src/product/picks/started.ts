/** How a started pick reads in the "Ya empezaron hoy" filter (REVIEW point 14). */
import type { StartedPick } from "@/lib/api/v1/types_product";
import { isLivePhase } from "@/product/matches/status";

export type StartedState = "all" | "live" | "won" | "lost" | "other";

/**
 * In play, won, lost, or neither yet (void, push, a match over without its result). An unsettled pick reads
 * `pending` once its result row exists and null before (11 Oct 2026, real data: 389 picks in play were all
 * `pending` and fell under "Otros").
 */
export function startedState(
  p: Pick<StartedPick, "result_status" | "phase">,
): Exclude<StartedState, "all"> {
  const r = p.result_status;
  if (r === "win" || r === "half_win") return "won";
  if (r === "loss" || r === "half_loss") return "lost";
  if ((r === null || r === "pending") && isLivePhase(p.phase)) return "live";
  return "other";
}

/** One match with the started picks taken on it, in the order the list gave them. */
export interface StartedMatchGroup {
  fixtureId: number;
  /** The first pick of the match: the match's own fields (teams, score, phase) are the same on all. */
  head: StartedPick;
  picks: StartedPick[];
}

/**
 * The started picks grouped by match (plan PICKS, F6 / L2): a match with three picks reads as one match with
 * three picks, not as three cards that repeat the teams. The order of the matches is the order in which each
 * first appears, so the list keeps the server's order; inside a match, the picks keep theirs.
 */
export function groupByMatch(picks: readonly StartedPick[]): StartedMatchGroup[] {
  const groups = new Map<number, StartedMatchGroup>();
  for (const p of picks) {
    const g = groups.get(p.fixture_id);
    if (g) g.picks.push(p);
    else groups.set(p.fixture_id, { fixtureId: p.fixture_id, head: p, picks: [p] });
  }
  return [...groups.values()];
}

/** The match's goals as the card shows them: the 90-minute score once it has one, else the live one while in play. */
export function startedScore(
  pick: Pick<StartedPick, "score_home" | "score_away" | "live_home" | "live_away" | "phase">,
): { home: number; away: number } | null {
  if (pick.score_home !== null && pick.score_away !== null)
    return { home: pick.score_home, away: pick.score_away };
  if (isLivePhase(pick.phase) && pick.live_home !== null && pick.live_away !== null)
    return { home: pick.live_home, away: pick.live_away };
  return null;
}
