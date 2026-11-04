/**
 * Why a row is on Inicio (plan UX, A13; section 38: «siempre explicable»): a team or a league the reader follows, or one
 * suggested for Colombia while they chose none - said as a chip and, with a tap, as a sentence.
 */
import { intlTag, t } from "@/lib/i18n";
import type { FollowReason } from "@/lib/api/v1/types_today";

/** Why a row is on Inicio: a team or a league the reader follows, or one suggested while they chose none. */
export type Why = FollowReason | { kind: "suggested" };

/** «Nacional y Millonarios»: the followed teams as a sentence says them. */
export function namesText(names: readonly string[]): string {
  return new Intl.ListFormat(intlTag(), { type: "conjunction" }).format(names);
}

/** The chip and its help: «Sigues a Nacional» / «Tu liga» / «Sugerida». */
export function whyText(why: Why): { label: string; help: string } {
  if (why.kind === "team") {
    const team = namesText(why.names);
    return {
      label: t("home.today.whyTeam", { team }),
      help: t("home.today.whyTeamHelp", { team }),
    };
  }
  if (why.kind === "league") {
    return { label: t("home.today.whyLeague"), help: t("home.today.whyLeagueHelp") };
  }
  return { label: t("home.today.why"), help: t("home.today.whyHelp") };
}
