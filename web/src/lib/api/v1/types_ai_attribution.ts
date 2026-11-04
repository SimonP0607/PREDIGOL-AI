/**
 * The attribution of the shadow and the Learning Analyst's hypotheses as the Admin Console reads them (plan IA, phase 5). Mirrors
 * fbi.api.contracts.ai_attribution. Reading only: what the server computed from codes (the outcome of each agent's stance, the class of a miss, the
 * closing line, the calibration), the share of matches with attributions against the plan's bar for Gate B (a count, never a verdict), and the
 * hypotheses with the agent and version they are about and the ids of the attributions they cite. The only prose is the AI's: the reviewer's
 * narrative and the analyst's text - shown, never measured.
 */
import type { Iso } from "./types";

export type AttributionOutcome = "HIT" | "MISS" | "VOID";

export interface AttributionSwitches {
  /** FBI_AI_PM_REVIEWER: the daily attribution and the Post-Match Reviewer. */
  pm_reviewer: boolean;
  /** FBI_AI_LEARNING_ANALYST: the Learning Analyst, on Mondays. */
  learning_analyst: boolean;
  reviewer_version: string;
  analyst_version: string;
  attribution_version: string;
}

export interface AttributionCoverage {
  since: string;
  until: string;
  matches: number;
  attributed_matches: number;
  /** Null when there is no match to judge: zero of zero is not 100 %. */
  match_share: number | null;
  selections: number;
  attributed_selections: number;
  selection_share: number | null;
  /** The plan's bar for Gate B (0.95). */
  bar: number;
}

export interface AttributionScoreRow {
  agent: string;
  agent_version: string;
  engine: string;
  hits: number;
  misses: number;
  voids: number;
  hit_rate: number | null;
}

export interface AttributionClassCount {
  agent: string;
  agent_version: string;
  error_class: string;
  n: number;
  refined: number;
}

export interface AttributionLine {
  engine: string;
  agent: string;
  agent_version: string;
  signal: string;
  stance: string;
  outcome: AttributionOutcome;
  error_class: string;
  refined_class: string | null;
  toward_close: boolean | null;
}

export interface PostmortemAttribution {
  postmortem_id: number;
  fixture_id: number;
  match: string;
  kickoff_at: Iso;
  market_key: string;
  selection: string;
  line: number;
  settled: string;
  calibration: string | null;
  clv: number | null;
  narrative: string | null;
  lines: AttributionLine[];
}

export interface AttributedHypothesis {
  id: number;
  agent: string;
  agent_version: string;
  title: string;
  hypothesis: string;
  rationale: string;
  status: string;
  created_at: Iso;
  decided_at: Iso | null;
  attribution_ids: number[];
  experiment: Record<string, unknown> | null;
  week_from: string | null;
}

export interface HypothesisCount {
  agent: string;
  agent_version: string;
  proposed: number;
  accepted: number;
  rejected: number;
  other: number;
}

export interface AttributionOverview {
  switches: AttributionSwitches;
  coverage: AttributionCoverage;
  scoreboard: AttributionScoreRow[];
  classes: AttributionClassCount[];
  postmortems: PostmortemAttribution[];
  hypotheses: AttributedHypothesis[];
  hypothesis_counts: HypothesisCount[];
  days: number;
}
