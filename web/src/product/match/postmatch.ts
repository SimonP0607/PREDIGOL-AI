/** The Postpartido's words (plan UX, A9): what PrediGol's result forecast said against what happened. */
import { t } from "@/lib/i18n";
import { fmtPct, toNumber } from "@/lib/i18n/format";
import type { ForecastMarket } from "@/lib/api/v1/types_forecast";
import { outcomeLabel } from "./forecast";

export type Goals = { home: number; away: number };

/** The 1X2 selection the score says: Home, Draw or Away. */
export function resultSelection(score: Goals): "Home" | "Draw" | "Away" {
  return score.home > score.away ? "Home" : score.home === score.away ? "Draw" : "Away";
}

export function forecastVsResult(
  market: ForecastMarket,
  score: Goals,
  sides: { home: string; away: string },
): { line: string; hit: boolean } | null {
  const likely = market.outcomes.find((o) => o.likely);
  const p = toNumber(likely?.probability ?? null);
  if (!likely || p === null) return null;
  const actual = resultSelection(score);
  const line = t("match.postmatch.line", {
    outcome: outcomeLabel(market, likely, sides),
    pct: fmtPct(p, 0),
    uncal: market.calibration === "UNCALIBRATED" ? t("match.postmatch.uncalibrated") : "",
    score: `${score.home}-${score.away}`,
    actual: outcomeLabel(market, { selection: actual }, sides),
  });
  return { line, hit: likely.selection === actual };
}
