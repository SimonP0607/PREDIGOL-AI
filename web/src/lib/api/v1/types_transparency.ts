/**
 * «Cómo le va a PrediGol» (plan UX, A12), as the API returns it. Mirrors fbi.api.contracts.transparency: the published picks
 * by fixed period with their sample, the days without picks and why, by kind of bet, the line value, the forecast's
 * calibration and what is still in evaluation (counts only). Null data with `not_available`: readers do not see it yet.
 */
import type { Dec, Iso } from "./types";

export type TransparencyPeriod = "7d" | "30d" | "all";
export type NoPickDayReason = "no_matches" | "no_qualified_candidates" | "not_chosen";
export type DecisionStop =
  | "data"
  | "model"
  | "market"
  | "calibration"
  | "ev"
  | "context"
  | "risk"
  | "correlation"
  | "price"
  | "final";

/** Published picks counted the way Mis picks counts PrediGol's: a flat stake of one unit per settled pick. */
export interface TransparencyTally {
  published: number;
  pending: number;
  won: number;
  lost: number;
  half_won: number;
  half_lost: number;
  push: number;
  void: number;
  /** Settled with a stake (won, lost, the halves and the pushes): the n of the sample. */
  settled: number;
  /** Null below `min_sample` settled picks: counts only. */
  units: Dec | null;
  roi: Dec | null;
  /** ± one standard error of the ROI, a share. */
  margin: Dec | null;
  conclusive: boolean;
}

export interface TransparencyPeriodTally extends TransparencyTally {
  period: TransparencyPeriod;
  /** First day counted (reader's time zone); null for the whole history. */
  since: string | null;
  until: string;
}

export interface TransparencyMarketTally extends TransparencyTally {
  /** 1X2, OU, BTTS, AH, DC... or `other` (the kinds with fewer than min_sample settled picks, together). */
  market: string;
}

export interface NoPickDay {
  day: string;
  reason: NoPickDayReason;
  matches: number;
  /** Selections PrediGol Intelligence measured, in evaluation: a count. */
  measured: number;
  /** Reconstructed from the decisions saved: the commonest first filter that stopped the day's selections. */
  stop: DecisionStop | null;
}

export interface NoPickDays {
  since: string;
  until: string;
  days: number;
  with_picks: number;
  without: number;
  reasons: Partial<Record<NoPickDayReason, number>>;
  measured: number;
  stops: Partial<Record<DecisionStop, number>>;
  /** Newest first. */
  items: NoPickDay[];
}

export interface LineValue {
  version: string;
  since: string;
  n: number;
  /** Null below min_sample. */
  mean: Dec | null;
  positive: Dec | null;
  /** Median minutes before kick-off of the reference. */
  minutes: number | null;
}

export interface CalibrationBin {
  low: Dec;
  high: Dec;
  predicted: Dec;
  observed: Dec;
  n: number;
}

export interface ForecastCalibration {
  market: "1X2" | "OU" | "BTTS";
  line: Dec;
  state: "CALIBRATED" | "UNCALIBRATED";
  matches: number;
  calibrated: number;
  /** The outcome the bins measure (Over, Yes); null for 1X2 (every outcome). */
  selection: string | null;
  /** Only for a calibrated market with min_calibration matches. */
  bins: CalibrationBin[];
  omitted: number;
}

export interface TransparencyEvaluation {
  markets: number;
  pairs: number;
  passed_markets: number;
  passed_pairs: number;
  since: string | null;
  /** Forecasts of qualified models in the window of the days without picks. */
  qualified: number;
}

export type DefinitionKey =
  "roi" | "sample" | "no_pick_day" | "line_value" | "calibration" | "evaluation";

export interface TransparencyDefinition {
  key: DefinitionKey;
  version: string;
  since: string;
}

export interface Transparency {
  timezone: string;
  min_sample: number;
  conclusive: number;
  min_calibration: number;
  min_bin: number;
  calibration_days: number;
  periods: TransparencyPeriodTally[];
  days: NoPickDays;
  markets: TransparencyMarketTally[];
  line_value: LineValue;
  forecasts: ForecastCalibration[];
  evaluation: TransparencyEvaluation;
  definitions: TransparencyDefinition[];
  data_as_of: Iso | null;
}
