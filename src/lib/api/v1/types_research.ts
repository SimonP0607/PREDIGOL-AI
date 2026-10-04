/** GET /admin/research/v2 - mirrors fbi.api.contracts.research. */
import type { Iso } from "./types";

export type ResearchRole = "CHAMPION" | "CHALLENGER" | "RESEARCH" | "REJECTED";

export interface ResearchEntry {
  experiment_id: number;
  name: string;
  kind: "backtest" | "market" | "prospective" | "audit" | string;
  model_family: string;
  role: ResearchRole | null;
  role_reason: string | null;
  segment: string | null;
  finished_at: Iso | null;
  data_as_of: Iso | null;
  metrics: Record<string, unknown>;
}

export interface LegacyRun {
  experiment_id: number;
  name: string;
  model_family: string;
  research_status: string;
  finished_at: Iso | null;
  vs_primary: [number, number, number] | null;
}

export interface ResearchOverview {
  run: string | null;
  finished_at: Iso | null;
  data_as_of: Iso | null;
  feature_version: string | null;
  champion: string | null;
  qualified_models: number;
  challengers: number;
  models: ResearchEntry[];
  markets: ResearchEntry[];
  prospective: ResearchEntry[];
  audit: ResearchEntry | null;
  legacy: LegacyRun[];
  label: "RESEARCH_V2";
}

export interface BlendSummary {
  w_test: number;
  w_test_ci: [number, number];
  n_test: number;
  blend_minus_market: [number, number, number] | null;
  adds_information: boolean;
  blend_beats_market: boolean;
}

export interface AuditGroup {
  n: number;
  mean_odds: number | null;
  profit_units: number;
  roi: number | null;
  roi_se: number | null;
  claimed_ev: number | null;
  n_with_close: number;
  ev_at_close: number | null;
  ev_at_close_se: number | null;
  luck: number | null;
  luck_se: number | null;
}

export interface ProspectiveRow {
  segment: string;
  model: string;
  played: number;
  forecast: number;
  with_market: number;
  judged: boolean;
  model_logloss: number | null;
  market_logloss: number | null;
  diff: [number, number, number] | null;
  verdict: string | null;
  blend_w: [number, number, number] | null;
}
