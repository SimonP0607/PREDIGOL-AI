/**
 * PrediGol's forecast of a match, apart from its value and from any pick (plan F5), as the API returns it.
 * Mirrors fbi.api.contracts.forecast. A forecast is a probability and the interval around it; it carries no
 * price, no edge and no recommendation. Only the Admin Console's preview also gets the fair odds and, beside
 * the forecast, the decision layer's value and the frozen picks.
 */
import type { Dec, Iso, Section } from "./types";

export type ForecastCalibration = "CALIBRATED" | "UNCALIBRATED";
export type ForecastBasis = "champion" | "no_champion" | "needs_price" | "not_applicable";

export interface ForecastOutcome {
  selection: string;
  probability: Dec;
  low: Dec | null;
  high: Dec | null;
  /** The most probable outcome of its market. */
  likely: boolean;
  /** 1 / probability. Admin preview only: null for a user. */
  fair_odds?: Dec | null;
  /** The model's own number before calibration. Admin preview only. */
  model_probability?: Dec | null;
}

export interface ForecastMarket {
  market: string;
  line: Dec;
  family: string;
  /** The model that priced it. Admin preview only: null for a reader (an internal name is not a reader's word, plan UX A9). */
  model: string | null;
  calibration: ForecastCalibration;
  basis: ForecastBasis;
  known_at: Iso;
  data_cutoff_at: Iso;
  outcomes: ForecastOutcome[];
}

/** The decision layer's newest evaluation of a selection (needs a price). Admin preview only. */
export interface ForecastValueRow {
  market: string;
  selection: string;
  line: Dec;
  state: string;
  odds: Dec | null;
  probability: Dec | null;
  market_probability: Dec | null;
  edge: Dec | null;
  ev: Dec | null;
  reasons: string[];
  known_at: Iso;
}

/** A pick frozen for the match (shadow or qualified). Admin preview only. */
export interface ForecastPickRow {
  id: number;
  market: string;
  selection: string;
  line: Dec;
  status: string;
  mode: string;
  odds: Dec;
  probability: Dec | null;
}

export interface MatchForecast {
  fixture_id: number;
  kickoff_at: Iso;
  status_group: string;
  forecast: Section<ForecastMarket[]>;
  /** Null for a user: the forecast is not a value. */
  value?: Section<ForecastValueRow[]> | null;
  /** Null for a user: neither a forecast nor a value is a pick. */
  picks?: Section<ForecastPickRow[]> | null;
}
