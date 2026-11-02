/**
 * What the Match Center's header says about the tie a match is a leg of (plan F2): where it sits in the tie ("Vuelta"), the
 * aggregate ("Global 1–2", or "Ida 0–1" before the match) and who went through.
 *
 * Scores are from THIS match's home and away (the API orients them): the left side of the header is the left side of the
 * aggregate. A live match adds its own goals to what came before it; a finished one uses the API's aggregate; and who went
 * through is said only when the match is over and the API says the tie is decided - the page of a match not yet played never
 * carries it.
 */
import { t } from "@/lib/i18n";
import type { MatchTie, TieDecidedBy } from "@/lib/api/v1/types_center";
import type { Goals, Phase } from "./model";

export interface TieView {
  /** Where the match sits in its tie: "Ida", "Vuelta", "Repetición", "Partido 2 de la serie". */
  place: string | null;
  /** "Ida 0–1" before the match, "Global 1–2" while it is played and once it is over. */
  score: string | null;
  /** Who went through, only for a match that is over and a tie that is decided. */
  outcome: string | null;
}

function pair(score: Goals): string {
  return `${score.home}–${score.away}`;
}

function placeOf(tie: MatchTie): string | null {
  switch (tie.format) {
    case "two_legged":
      if (tie.leg === 1) return t("match.tie.firstLeg");
      if (tie.leg === 2) return t("match.tie.secondLeg");
      return null;
    case "replay":
      return tie.leg !== null && tie.leg >= 2 ? t("match.tie.replay") : null;
    case "series":
      return tie.leg !== null ? t("match.tie.series", { n: tie.leg }) : null;
    default:
      return null;
  }
}

function scoreOf(tie: MatchTie, phase: Phase, live: Goals | null): string | null {
  if (tie.format !== "two_legged") return null;
  if (phase === "finished") {
    // The first leg of a tie that is still open has no aggregate worth a second line: it is its own score.
    if (tie.leg === 1 && tie.state !== "decided") return null;
    return tie.aggregate ? t("match.tie.global", { score: pair(tie.aggregate) }) : null;
  }
  const before = tie.aggregate_before;
  if (!before) return null;
  if (phase === "live" && live) {
    return t("match.tie.global", {
      score: pair({ home: before.home + live.home, away: before.away + live.away }),
    });
  }
  return t("match.tie.first", { score: pair(before) });
}

function howOf(decidedBy: TieDecidedBy): string | null {
  switch (decidedBy) {
    case "extra_time":
      return t("match.tie.by.extraTime");
    case "penalties":
      return t("match.tie.by.penalties");
    case "aggregate":
      return t("match.tie.by.aggregate");
    case "away_goals":
      return t("match.tie.by.awayGoals");
    case "tiebreak":
      return t("match.tie.by.tiebreak");
    case "walkover":
      return t("match.tie.by.walkover");
    case "series":
      return t("match.tie.by.series");
    default:
      return null;
  }
}

function outcomeOf(
  tie: MatchTie,
  phase: Phase,
  names: { home: string; away: string },
): string | null {
  // A single match says who won by its own score and its penalties line; the tie matters where it takes several matches.
  if (phase !== "finished" || tie.format === "single" || !tie.outcome) return null;
  const team = names[tie.outcome.winner];
  const how = howOf(tie.outcome.decided_by);
  const advances = t("match.tie.advances", { team });
  return how ? `${advances} · ${how}` : advances;
}

export function tieView(
  tie: MatchTie | null | undefined,
  phase: Phase,
  live: Goals | null,
  names: { home: string; away: string },
): TieView | null {
  if (!tie) return null;
  const view: TieView = {
    place: placeOf(tie),
    score: scoreOf(tie, phase, live),
    outcome: outcomeOf(tie, phase, names),
  };
  return view.place || view.score || view.outcome ? view : null;
}
