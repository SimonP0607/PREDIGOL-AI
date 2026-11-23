/**
 * `GET /admin/evaluation/board` (plan PM, PM-12-01 and PM-12-06; IA-153, backend `fbi.api.contracts.evaluation_board`): the newest
 * weekly board (PrediGol's forecast, the market and the provider on the same matches; the Brier split into reliability and
 * resolution) and the newest report by competition and coverage level. Private; 404 while `FBI_EVALUATION_BOARD` is off.
 */
export interface EvalInterval {
  value: number | null;
  low: number | null;
  high: number | null;
}

export type EvalSource = "modelo" | "mercado" | "proveedor";

export interface EvalSourceScore {
  source: EvalSource;
  n: number;
  days: number;
  log_loss: EvalInterval;
  brier: EvalInterval;
  reliability: EvalInterval;
  resolution: EvalInterval;
  uncertainty: number;
  residual: number;
}

export interface EvalPairedDifference {
  a: string;
  b: string;
  metric: "log_loss" | "brier";
  n: number;
  value: number | null;
  low: number | null;
  high: number | null;
  verdict: "modelo_mejor" | "modelo_peor" | "indistinguible" | "insuficiente";
}

export interface EvalWindow {
  from: string;
  to: string;
  matches: number;
  with_each: Record<string, number>;
  common: number;
  sources: EvalSourceScore[];
  pairs: EvalPairedDifference[];
}

export interface EvalMarketBoard {
  market: "1X2" | "OU" | "BTTS";
  line: number;
  week: EvalWindow;
  cumulative: EvalWindow;
}

export interface EvalWeeklyBoard {
  report_id: number;
  version: string;
  period_from: string;
  period_to: string;
  cumulative_from: string;
  computed_at: string;
  markets: EvalMarketBoard[];
}

export type EvalVerdict = "apta" | "sin_habilidad" | "insuficiente";

export interface EvalCompetitionVerdict {
  competition_id: number;
  name: string | null;
  model: string;
  market: string;
  n: number;
  days: number;
  log_loss: number;
  log_loss_low: number | null;
  log_loss_high: number | null;
  skill: number;
  skill_low: number | null;
  skill_high: number | null;
  verdict: EvalVerdict;
}

export interface EvalSegmentsSummary {
  report_id: number;
  version: string;
  period_from: string;
  period_to: string;
  computed_at: string;
  needed: number;
  reproduced: boolean;
  counts: Array<{ source: string; kind: string; verdict: EvalVerdict; segments: number }>;
  competitions: EvalCompetitionVerdict[];
}

export interface EvaluationBoard {
  weekly: EvalWeeklyBoard | null;
  segments: EvalSegmentsSummary | null;
  notice_es: string;
}
