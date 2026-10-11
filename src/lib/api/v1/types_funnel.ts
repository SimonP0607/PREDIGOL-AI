/** The day's selection funnel (GET /admin/picks/funnel, REVIEW PREDIGOL B1). */
import type { Dec, Iso } from "./types";
import type { CompetitionBadge, TeamBadge } from "./types_product";

export type FunnelStageKey =
  "data" | "market" | "model" | "calibration" | "value" | "risk" | "context" | "selection";

export interface FunnelStage {
  key: FunnelStageKey;
  entered: number;
  passed: number;
  /** Why the ones that stopped here stopped, by reason code. */
  reasons: Record<string, number>;
}

export interface FunnelItem {
  day: string | null;
  stage: FunnelStageKey | null;
  reason: string | null;
  pick_id: number;
  fixture_id: number;
  kickoff_at: Iso;
  competition: CompetitionBadge;
  home: TeamBadge;
  away: TeamBadge;
  market_key: string;
  selection: string;
  line: Dec;
  odds: Dec;
  bookmaker: string | null;
  p_model: Dec;
  p_low: Dec;
  p_market: Dec;
  ev: Dec;
  growth: Dec;
  ai_decision: string | null;
  /** Outside evidence about the match, by status (CONFIRMED, PROBABLE, RUMOR, CONTRADICTORY, OUTDATED). */
  evidence: Record<string, number>;
}

export interface SelectionFunnel {
  at: Iso;
  source: "qualified" | "evaluation";
  rule_version: string;
  risk_version: string;
  max_odds: Dec | null;
  context_version: string;
  ai_mode: string;
  ai_enforced: boolean;
  candidates: number;
  selections: number;
  stages: FunnelStage[];
  chosen: FunnelItem[];
  near: FunnelItem[];
  in_set: Record<string, number>;
}
