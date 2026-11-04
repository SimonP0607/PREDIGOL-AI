/**
 * PRONÓSTICO PREDIGOL in words (plan F5): what the block shows for a given answer of the API, a market's title,
 * an outcome's label, its interval and its bar. Pure: no React, no fetching.
 *
 * A forecast is a probability and the interval around it. Nothing here turns one into a price, a value or a pick:
 * a user is never handed a number that reads as odds to take, and the fair odds, the decision layer's value and the
 * frozen picks exist only in the Admin Console's preview.
 */
import { t, translateOr } from "@/lib/i18n";
import { fmtPct, toNumber } from "@/lib/i18n/format";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  FamilyLine,
  FamilyMarket,
  ForecastBasis,
  ForecastCalibration,
  ForecastMarket,
  ForecastOutcome,
  MatchForecast,
} from "@/lib/api/v1/types_forecast";
import { pickText } from "@/live/familiesText";
import { marketTitle, selectionPhrase, type Sides } from "./intelligence";

/** The block's anchor. */
export const FORECAST_ID = "predigol-forecast";

/** The query as the block receives it, apart from React Query so that the block can be rendered from a fixture. */
export type ForecastLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry?: (() => void) | undefined }
  | { status: "success"; envelope: Envelope<MatchForecast | null> };

export type ForecastScreen =
  /** The owner turned it off for readers (`FBI_FORECAST_USERS=0`): nothing to show. */
  | { kind: "nothing" }
  | { kind: "loading" }
  | { kind: "error"; error: unknown; retry?: (() => void) | undefined }
  /** The API answered, and PrediGol has no forecast for this match. `data` carries what the preview adds. */
  | { kind: "none"; code: string | null; data: MatchForecast | null }
  | { kind: "forecast"; data: MatchForecast; markets: ForecastMarket[] };

/**
 * What the block shows. Readers see it since plan UX A9 (`FBI_FORECAST_USERS` on unless the owner turns it off), with every
 * state - loading, an error with its retry, why there is no forecast; only an answer that says readers may not see it
 * (the owner turned it off) shows nothing. The Admin Console's preview sees every state.
 */
export function forecastScreen(load: ForecastLoad, preview: boolean): ForecastScreen {
  // Shown to readers since A9 (the owner approved it): a reader sees it load and sees it fail, never a silent gap.
  if (load.status === "pending") return { kind: "loading" };
  if (load.status === "error") return { kind: "error", error: load.error, retry: load.retry };
  const { envelope } = load;
  const data = envelope.data;
  if (envelope.status !== "ok" || !data) {
    return preview ? { kind: "none", code: null, data: null } : { kind: "nothing" };
  }
  const markets = data.forecast.status === "ok" ? data.forecast.data : [];
  if (markets.length === 0) return { kind: "none", code: data.forecast.code ?? null, data };
  return { kind: "forecast", data, markets };
}

// ── the words ───────────────────────────────────────────────────────────────

/** "Resultado final (1X2)", "Goles: más/menos de 2,5", "Ambos marcan". */
export function forecastMarketTitle(market: Pick<ForecastMarket, "market" | "line">): string {
  return marketTitle(market.market, market.line);
}

/** The outcome once the market is named: "Gana Millonarios", "Empate", "Más de 2,5", "Sí". */
export function outcomeLabel(
  market: Pick<ForecastMarket, "market" | "line">,
  outcome: Pick<ForecastOutcome, "selection">,
  sides: Sides,
): string {
  return selectionPhrase(
    { market: market.market, selection: outcome.selection, line: market.line },
    sides,
  );
}

/** "entre 41 % y 59 %", or that none was measured: a missing interval is said, not drawn as a point. */
export function intervalText(outcome: Pick<ForecastOutcome, "low" | "high">): string {
  const low = toNumber(outcome.low);
  const high = toNumber(outcome.high);
  if (low === null || high === null) return t("match.forecast.rangeNone");
  return t("match.forecast.range", { low: fmtPct(low, 0), high: fmtPct(high, 0) });
}

export function calibrationLabel(calibration: ForecastCalibration): string {
  return calibration === "CALIBRATED"
    ? t("match.forecast.calibrated")
    : t("match.forecast.uncalibrated");
}

/** Why a number is calibrated or not, in a sentence. Empty for a basis this page does not know. */
export function basisNote(basis: ForecastBasis | string): string {
  return translateOr(`match.forecast.basis.${basis}`, "");
}

/** The three models that forecast today have a name a reader can say; a model that joins later is shown as named. */
export function modelLabel(model: string): string {
  return translateOr(`match.forecast.models.${model}`, model);
}

/** Why a match has no forecast, in the reader's language (the API's own reason is English and technical). */
export function noForecastText(code: string | null | undefined): string {
  return code
    ? translateOr(`match.forecast.reason.${code}`, t("match.note.notAvailable"))
    : t("match.note.notAvailable");
}

// ── what the families forecast (the preview's own section) ──────────────────

export interface FamilyGroup {
  /** GOALS_HALF, CORNERS, CARDS or YELLOW, as the API names it. */
  family: string;
  /** The markets it forecasts for the match, in the order the API sent them. */
  markets: FamilyMarket[];
}

/** The markets of the families grouped by family, the families and their markets in the order the API sent them. */
export function groupFamilies(markets: readonly FamilyMarket[]): FamilyGroup[] {
  const groups: FamilyGroup[] = [];
  for (const market of markets) {
    const found = groups.find((g) => g.family === market.family);
    if (found) found.markets.push(market);
    else groups.push({ family: market.family, markets: [market] });
  }
  return groups;
}

/** An outcome of a market of a family in words: "Más de 9,5", "Gana Nashville SC o empate", "Nashville SC / Empate" (half-time/full-time). */
export function familyOutcomeText(
  market: Pick<FamilyMarket, "market">,
  line: Pick<FamilyLine, "line">,
  outcome: Pick<ForecastOutcome, "selection">,
  sides: Sides,
): string {
  return pickText(market.market, outcome.selection, line.line, sides);
}

/**
 * A family's probability: whole percentages, and one decimal below 10 % so that the long tail of a market with many outcomes (half-time/full-time)
 * does not read as a row of "2 %" and "1 %".
 */
export function familyPercent(value: string | number | null | undefined): string {
  const n = toNumber(value);
  if (n === null || Number.isNaN(n)) return fmtPct(null);
  return fmtPct(n, n > 0 && n < 0.1 ? 1 : 0);
}

// ── the bar ─────────────────────────────────────────────────────────────────

/** A probability as the share (0-100) of a bar's track: clamped, so that no bar leaves its track. */
export function barPercent(value: string | number | null | undefined): number {
  const n = toNumber(value);
  if (n === null || Number.isNaN(n)) return 0;
  return Math.min(100, Math.max(0, Math.round(n * 1000) / 10));
}

/** Where the interval's two ends sit on the track, or null when none was measured (or it is not an interval). */
export function intervalSpan(
  outcome: Pick<ForecastOutcome, "low" | "high">,
): { left: number; right: number } | null {
  if (toNumber(outcome.low) === null || toNumber(outcome.high) === null) return null;
  const left = barPercent(outcome.low);
  const right = barPercent(outcome.high);
  return right < left ? null : { left, right };
}
