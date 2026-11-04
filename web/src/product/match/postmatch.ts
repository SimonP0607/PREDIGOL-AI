/**
 * The Postpartido's words (plan UX, A9 and B4): what PrediGol's forecast said against what happened, how each pick PrediGol
 * published for the match ended and why - the match's own facts as the post-mortem found them, worded here from their codes and
 * figures - and the news published once it had started. Nothing here is a sentence that came from the server.
 */
import { t } from "@/lib/i18n";
import { fmtPct, localFixed, toNumber } from "@/lib/i18n/format";
import type { ForecastMarket } from "@/lib/api/v1/types_forecast";
import type { NewsItem } from "@/lib/api/v1/types_news";
import type { PostmatchCause, PostmatchPick } from "@/lib/api/v1/types_postmatch";
import { outcomeLabel } from "./forecast";
import { failsInTen } from "./intelligence";

export type Goals = { home: number; away: number };
export type Sides = { home: string; away: string };

/** The markets whose forecast is set against the result, in this order: the result, the goals at 2.5, both teams to score. */
export const FORECAST_MARKETS: ReadonlyArray<readonly [string, string]> = [
  ["1X2", "0"],
  ["OU", "2.5"],
  ["BTTS", "0"],
];

/** The 1X2 selection the score says: Home, Draw or Away. */
export function resultSelection(score: Goals): "Home" | "Draw" | "Away" {
  return score.home > score.away ? "Home" : score.home === score.away ? "Draw" : "Away";
}

/** The selection of a market the score says; null when the score falls on the line (a whole line returns the stake). */
export function resultSelectionFor(
  market: Pick<ForecastMarket, "market" | "line">,
  score: Goals,
): string | null {
  if (market.market === "1X2") return resultSelection(score);
  if (market.market === "BTTS") return score.home > 0 && score.away > 0 ? "Yes" : "No";
  if (market.market === "OU") {
    const line = toNumber(market.line);
    const total = score.home + score.away;
    if (line === null || total === line) return null;
    return total > line ? "Over" : "Under";
  }
  return null;
}

export function forecastVsResult(
  market: ForecastMarket,
  score: Goals,
  sides: Sides,
): { line: string; hit: boolean } | null {
  const likely = market.outcomes.find((o) => o.likely);
  const p = toNumber(likely?.probability ?? null);
  const actual = resultSelectionFor(market, score);
  if (!likely || p === null || actual === null) return null;
  const line = t("match.postmatch.line", {
    outcome: outcomeLabel(market, likely, sides),
    pct: fmtPct(p, 0),
    uncal: market.calibration === "UNCALIBRATED" ? t("match.postmatch.uncalibrated") : "",
    score: `${score.home}-${score.away}`,
    actual: outcomeLabel(market, { selection: actual }, sides),
  });
  return { line, hit: likely.selection === actual };
}

/** The forecast markets of the page that the result can be set against, in FORECAST_MARKETS's order. */
export function forecastMarkets(markets: readonly ForecastMarket[]): ForecastMarket[] {
  return FORECAST_MARKETS.flatMap(([key, line]) => {
    const m = markets.find((x) => x.market === key && toNumber(x.line) === toNumber(line));
    return m ? [m] : [];
  });
}

/** How a published pick ended, in a sentence; a loss says how often a selection like it fails. */
export function outcomeText(p: PostmatchPick): string {
  const result = p.result ?? "pending";
  const base = t(`match.postmatch.why.outcome.${result}`);
  if (result !== "loss" && result !== "half_loss") return base;
  const n = failsInTen(p.p_model);
  return n === null ? base : `${base} ${t("match.postmatch.why.failsInTen", { n })}`;
}

/** PrediGol's probability when it published the pick and, once analysed, the market's at its close. */
export function chancesText(p: PostmatchPick): string {
  const model = fmtPct(p.p_model, 0);
  return p.p_close === null
    ? t("match.postmatch.why.chancesAlone", { p: model })
    : t("match.postmatch.why.chances", { p: model, close: fmtPct(p.p_close, 0) });
}

/** One fact of the match in the reader's words: whose, when, how much - never a judgement. Empty for a code this page does not know. */
export function causeText(c: PostmatchCause, sides: Sides): string {
  const team = c.side === "home" ? sides.home : c.side === "away" ? sides.away : "";
  const vars = { team, minute: c.minute ?? "" };
  switch (c.code) {
    case "red_card":
    case "penalty_scored":
    case "penalty_missed":
    case "early_goal":
      return team && c.minute !== null ? t(`match.postmatch.why.cause.${c.code}`, vars) : "";
    case "early_substitution":
      return c.n ? t("match.postmatch.why.cause.early_substitution", { count: c.n }) : "";
    case "cards_above_referee":
    case "cards_below_referee":
      return c.cards !== null && c.referee_avg !== null
        ? t(`match.postmatch.why.cause.${c.code}`, {
            cards: c.cards,
            avg: localFixed(c.referee_avg, 1),
          })
        : "";
    case "xg_supported":
    case "xg_against":
      return c.xg_home !== null && c.xg_away !== null
        ? t(`match.postmatch.why.cause.${c.code}`, {
            home: sides.home,
            away: sides.away,
            xh: localFixed(c.xg_home, 2),
            xa: localFixed(c.xg_away, 2),
          })
        : "";
    default:
      return "";
  }
}

/** The facts of a pick that the page can word, with whether each played for it or against it. */
export function causeLines(
  p: PostmatchPick,
  sides: Sides,
): Array<{ text: string; effect: PostmatchCause["effect"] }> {
  return p.causes.flatMap((c) => {
    const text = causeText(c, sides);
    return text ? [{ text, effect: c.effect }] : [];
  });
}

/** What the page says when a settled pick has no facts to show: nothing out of the ordinary, or the analysis not written yet. */
export function causesEmptyText(p: PostmatchPick): string | null {
  if (p.result === null || p.result === "pending") return null;
  return p.analysed ? t("match.postmatch.why.nothing") : t("match.postmatch.why.notYet");
}

/**
 * The news first published after the kick-off: an exact time later than it. A day-only date, or none, could be either side
 * of the whistle, and is left to the Noticias tab.
 */
export function newsAfterKickoff(items: readonly NewsItem[], kickoffAt: string): NewsItem[] {
  const kickoff = Date.parse(kickoffAt);
  if (Number.isNaN(kickoff)) return [];
  return items.filter((n) => {
    if (!n.published_at || n.published_day_only) return false;
    const at = Date.parse(n.published_at);
    return !Number.isNaN(at) && at > kickoff;
  });
}
