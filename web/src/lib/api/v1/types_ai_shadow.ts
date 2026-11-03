/**
 * The shadow of phase 3 as the Admin Console reads it (plan IA, sections 22-24 and 33). Mirrors fbi.api.contracts.ai_shadow.
 * Reading only: the seven arms side by side, the contradictions `contra-v1` found, the runs of the agents and the file of one match. What these shapes
 * carry is what the orchestrator wrote - counts, codes, the server's numbers and ids; never a model's free text, never an address. The "enough data"
 * flags are counts and days against the plan's thresholds, NEVER a verdict of a gate. Money travels as text (`Dec`), a moment as ISO text (`Iso`).
 */
import type { Dec, Iso } from "./types";
import type { AiCycleRow } from "./types_ai_layer";

export type ShadowDecision = "APPROVE" | "DOWNGRADE" | "REJECT" | "ABSTAIN";
/** What an engine's Council did with a candidate a contradiction touches: `none` means the engine has no verdict for it. */
export type Treatment = "kept" | "lowered" | "abstained" | "none";

export interface SwitchWord {
  /** The owner's word as it is written in app.env: FBI_AI_ENGINES, FBI_AI_SHADOW_SAMPLE, FBI_AI_AGENTS. */
  name: string;
  value: string;
  /** This word, by itself, lets the shadow run. */
  on: boolean;
}

export interface ShadowSwitches {
  mode: string;
  orchestrate: boolean;
  words: SwitchWord[];
  engines: string[];
  shadow_engines: string[];
  shadow_sample: string;
  agents: string[];
}

export interface Decisions {
  approved: number;
  downgraded: number;
  rejected: number;
  abstained: number;
}

export interface ArmSettled {
  report_at: Iso;
  window_from: Iso | null;
  window_to: Iso | null;
  selections: number;
  kept: number;
  rejected: number;
  clv_kept: number | null;
  clv_rejected: number | null;
  roi_kept: number | null;
  roi_rejected: number | null;
}

export type ArmId = "model" | "rules" | "gap" | "llm" | "council_solo" | "ma-v1" | "ma-v1-h";

export interface ArmRow {
  arm: ArmId;
  engine: string | null;
  /** `derived`: computed from the rules reviewer's rows by the plan's definition; `production`: today's reviewer; `shadow`: an engine of the Orchestrator. */
  kind: "derived" | "production" | "shadow";
  scope: "lab" | "production" | null;
  reviews: number;
  selections: number;
  decisions: Decisions | null;
  statuses: Record<string, number>;
  invalid: number;
  on_sample: number;
  selections_on_sample: number;
  decisions_on_sample: Decisions | null;
  cost_usd: Dec | null;
  ledger_usd: Dec | null;
  calls: number;
  latency_p95_ms: number | null;
  latency_n: number;
  paused: Record<string, number>;
  not_answered: Record<string, number>;
  settled: ArmSettled | null;
}

export interface ShareCount {
  share: string;
  assigned: number;
  sampled: number;
  council_solo: number;
}

export interface Assignments {
  experiment: string;
  arms_version: string;
  assigned: number;
  sampled: number;
  unsampled: number;
  council_solo: number;
  sampled_share: number | null;
  by_share: ShareCount[];
  first_assigned_at: Iso | null;
  last_assigned_at: Iso | null;
}

export interface Enough {
  days: number;
  days_need: number;
  days_reached: boolean;
  since: Iso | null;
  days_running: number;
  selections: number;
  selections_need: number;
  selections_reached: boolean;
}

export interface LabSpend {
  window_usd: Dec;
  shadow_usd: Dec;
  calls: number;
}

export interface ShadowArms {
  days: number;
  since: Iso;
  switches: ShadowSwitches;
  assignments: Assignments;
  arms: ArmRow[];
  enough: Enough;
  lab: LabSpend;
  last_cycle: AiCycleRow | null;
}

// ── the contradictions ───────────────────────────────────────────────────────

export type ContraCode = "C01" | "C02" | "C03" | "C04" | "C05" | "C06" | "C07" | "C08";

export interface ContraCount {
  code: string;
  n: number;
  passes: number;
  matches: number;
  confirmed: number;
  /** Per engine: (contradiction, candidate) pairs ended kept, lowered, abstained or none. */
  treatment: Record<string, Record<string, number>>;
}

export interface ContraCandidate {
  key: string;
  market: string | null;
  selection: string | null;
  line: string | null;
}

export interface ContraItem {
  code: string;
  fixture_id: number;
  match: string | null;
  kickoff_at: Iso | null;
  pass_kind: string;
  known_at: Iso;
  created_at: Iso;
  subject: string;
  candidates: ContraCandidate[];
  refs: string[];
  confirmed: boolean;
  official_lineup: boolean;
  starters_out: number;
  gap: string | null;
  requires: string | null;
  /** Per engine, per touched candidate. */
  treatment: Record<string, Record<string, Treatment>>;
}

export interface Contradictions {
  days: number;
  since: Iso;
  switches: ShadowSwitches;
  passes: number;
  with_contradictions: number;
  total: number;
  counts: ContraCount[];
  recent: ContraItem[];
}

// ── the runs of the agents ───────────────────────────────────────────────────

export interface AgentRunItem {
  id: number;
  run_kind: string;
  started_at: Iso;
  fixture_id: number | null;
  match: string | null;
  pass_kind: string;
  agent: string;
  agent_version: string;
  task_kind: string;
  model: string | null;
  effort: string | null;
  status: string;
  verdict: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  cost_usd: Dec;
  latency_ms: number | null;
  /** The rule of router-v1 (E1-E7) that sent the task to Opus. */
  escalation: string | null;
  fired: string[];
  error: string | null;
  idem: string;
  workspace: string | null;
  parent_run_id: number | null;
}

export interface OpusDay {
  day: string;
  calls: number;
  cap: number;
  remaining: number;
  skipped: number;
  cost_usd: Dec;
}

export interface AgentRuns {
  day: string;
  switches: ShadowSwitches;
  opus: OpusDay;
  total: number;
  cost_usd: Dec;
  by_status: Record<string, number>;
  runs: AgentRunItem[];
}

export interface AgentRunsQuery {
  day?: string | undefined;
  agent?: string | undefined;
  task_kind?: string | undefined;
  status?: string | undefined;
  model?: string | undefined;
  run_kind?: string | undefined;
  fixture_id?: number | undefined;
  limit?: number | undefined;
}

// ── the file of a match ──────────────────────────────────────────────────────

export interface FileAssignment {
  experiment: string;
  bucket: number;
  sampled: boolean;
  council_solo: boolean;
  share: string;
  assigned_at: Iso;
  engines: string[];
}

export interface FilePass {
  id: number;
  pass_kind: string;
  known_at: Iso;
  created_at: Iso;
  packet_id: number | null;
  /** `ran`, or `not_run` when no model could be asked at all. */
  status: string;
  reason: string | null;
  elapsed_ms: number | null;
}

export interface FileCandidate {
  key: string | null;
  family: string | null;
  market: string;
  selection: string;
  line: string;
  odds: string | null;
  p_model: string | null;
  p_market: string | null;
  edge: string | null;
  ev: string | null;
  left_out: string | null;
}

export interface Cell {
  engine: string;
  decision: ShadowDecision | null;
  confidence: string | null;
  level: string | null;
  status: string | null;
  model: string | null;
  drivers: string[];
  risks: string[];
  refs: string[];
  contradictions: string[];
  stances: Record<string, string>;
  escalation: {
    rule: string | null;
    replaced: boolean;
    skipped: string | null;
    model: string | null;
  } | null;
  reason: string | null;
  cost_usd: Dec | null;
  review_id: number | null;
}

export interface FileVerdicts {
  candidate: string;
  cells: Cell[];
}

export interface FileArm {
  engine: string;
  status: string | null;
  reason: string | null;
  paused: string[];
  escalated: Record<string, string>;
  escalation_skipped: Record<string, string>;
  view: Record<string, string | number | boolean | string[]> | null;
}

export interface FileSignal {
  code: string;
  direction: string;
  strength: string;
  refs: string[];
}

export interface FileStance {
  candidate: string;
  stance: string;
  drivers: string[];
  risks: string[];
  refs: string[];
}

export interface FileAssessment {
  label: string;
  mode: string;
  model: string | null;
  status: string;
  quality: string | null;
  signals: FileSignal[];
  candidates: FileStance[];
}

export interface FileContradiction {
  code: string;
  subject: string;
  candidates: string[];
  refs: string[];
  confirmed: boolean;
  detail: Record<string, string>;
}

export interface ShadowFile {
  fixture_id: number;
  match: string | null;
  kickoff_at: Iso | null;
  competition: string | null;
  switches: ShadowSwitches;
  assignment: FileAssignment | null;
  passes: FilePass[];
  selected: FilePass | null;
  candidates: FileCandidate[];
  assessments: FileAssessment[];
  contradictions: FileContradiction[];
  arms: FileArm[];
  verdicts: FileVerdicts[];
  evidence_ids: number[];
  calls: AgentRunItem[];
  cost_usd: Dec;
}
