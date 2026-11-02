/**
 * The agents of PrediGol Intelligence (plan IA, phase 1), as the Admin Console reads them. Mirrors fbi.api.contracts.ai_agents.
 * Reading only: the registry as the code has it, the engine each family of markets reads, what the job that writes the state of each match did,
 * the Orchestrator's queue (empty until phase 3), the audit of what an agent may know, and the file of one match. Nothing here calls a model,
 * creates a task or changes a pick. Money travels as text (`Dec`), a moment as ISO text (`Iso`), a day as `YYYY-MM-DD`.
 */
import type { Dec, Iso } from "./types";
import type { AiCycleRow } from "./types_ai_layer";

/** `built`: the code has it. `planned`: a phase of the plan builds it. `postponed`: it has no code until its gate. */
export type AgentStatus = "built" | "planned" | "postponed";

export interface AgentTaskView {
  task: string;
  prompt_version: string;
  schema_version: string | null;
  /** The model the task is registered with (the agents of the plan pin one); null on the old route, which runs on the deployment's setting. */
  model: string | null;
  tier: string | null;
  effort: string;
}

/** One line of the registry. Only a built agent has a version in force, a fingerprint and `in_sync`. */
export interface AgentView {
  agent: string;
  status: AgentStatus;
  purpose: string;
  contract: string | null;
  reads: string | null;
  version: string | null;
  fingerprint: string | null;
  born_as: string | null;
  baseline: boolean | null;
  registered_at: Iso | null;
  /** The fingerprint of the code that runs equals the one the ledger holds. */
  in_sync: boolean | null;
  retire_phase: number | null;
  next_version: string | null;
  next_phase: number | null;
  phase: number | null;
  replaces: string | null;
  gate: string | null;
  history: string[];
  tasks: AgentTaskView[];
}

/** A way the registry disagrees with the code or with itself (or `unreadable`, when it could not be read at all). */
export interface RegistryProblem {
  code: string;
  subject: string;
  text: string;
}

/** Which engine a family of markets reads: the newest `agent` promotion of the family decides; none means the language model of today. */
export interface FamilyEngine {
  family: string;
  engine: "llm" | "agent";
  /** The `model_name` of the champion row: agent@version[+upstream version...]. */
  promotion: string | null;
  agent: string | null;
  version: string | null;
  upstream: string[];
  since: Iso | null;
  promotion_id: number | null;
}

export interface PromotionRow {
  id: number;
  at: Iso;
  family: string | null;
  promotion: string | null;
  from_role: string | null;
  to_role: string;
  decided_by: "owner" | "system";
  gate_version: string;
  reason: string;
}

/** The size of one slice of `mcp-v1` over the window, in real tokens, against its cap. */
export interface SliceStat {
  name: string;
  states: number;
  tokens_p50: number;
  tokens_p95: number;
  tokens_max: number;
  cap: number;
  /** States where something was cut to fit the cap. */
  trimmed: number;
  /** States that still do not fit: a slice an agent would refuse. */
  over_cap: number;
}

export interface Timing {
  p50: number | null;
  p95: number | null;
  max: number | null;
}

export interface PackageDay {
  /** A Bogotá day. */
  day: string;
  states: number;
  matches: number;
  blocked: number;
  flagged: number;
}

/** The runs of the package job in the window. A pass that refuses is tried again at every run: the refusals shown are the last run's, never a sum. */
export interface PackageCycles {
  total: number;
  ok: number;
  partial: number;
  failed: number;
  running: number;
  last: AiCycleRow | null;
}

/** The constants of the job that writes the states. */
export interface PackageRule {
  state_version: string;
  package_version: string;
  window_days: number;
  limit: number;
  max_seconds: number;
}

export interface PackageStats {
  days: number;
  since: Iso;
  states: number;
  matches: number;
  by_pass: Record<string, number>;
  /** States whose package carries something that blocks an agent (a class of competition or a quarantined validation). */
  blocked: number;
  /** States where provider text read like an instruction and was marked. */
  flagged: number;
  slices: SliceStat[];
  build_ms: Timing;
  per_day: PackageDay[];
  cycles: PackageCycles;
  rule: PackageRule;
}

/** The Orchestrator's tables. Empty in phase 1: nothing creates a task yet. */
export interface QueueStats {
  days: number;
  /** Tasks created in the window, by state (every state is present). */
  tasks: Record<string, number>;
  /** Attempts started in the window, by status (every status is present). */
  runs: Record<string, number>;
  /** Tasks planned, queued or running now, whatever their age. */
  open: number;
  /** What the tasks queued or running have reserved of the budget. */
  reserved_usd: Dec;
}

export interface AuditDay {
  day: string;
  checked_at: Iso;
  version: string;
  n_checked: number;
  n_violations: number;
  examples: unknown[];
}

/** One rule of the nightly leakage audit that concerns the agents: its latest verdict per day. A rule never run has no days. */
export interface AuditRule {
  rule: string;
  days: AuditDay[];
  days_audited: number;
  checked: number;
  violations: number;
}

export interface AgentsSettings {
  mode: string;
  /** The switch of the job that writes the states (`FBI_AI_PACKAGE`). */
  package: boolean;
}

export interface AgentsOverview {
  registry: AgentView[];
  problems: RegistryProblem[];
  families: FamilyEngine[];
  decisions: PromotionRow[];
  package: PackageStats;
  queue: QueueStats;
  audit: AuditRule[];
  settings: AgentsSettings;
}

/** A slice of a state as it was measured: the measures, never the content. */
export interface StateSlice {
  name: string;
  hash: string;
  tokens: number;
  cap: number;
  fits: boolean;
  trimmed: string[];
  blocks: string[];
}

export interface MatchStateRow {
  id: number;
  fixture_id: number;
  run_kind: string;
  pass_kind: string;
  known_at: Iso;
  created_at: Iso;
  state_version: string;
  package_version: string | null;
  package_hash: string | null;
  packet_id: number | null;
  elapsed_ms: number | null;
  slices: StateSlice[];
  blocking: string[];
  flags: string[];
  /** The fingerprint of the model code the package was derived with. */
  code: string | null;
  /** Agents foreseen, run, failed or waiting for this state. */
  agents: number;
  contradictions: number;
  candidates: number;
  risks: number;
  /** A verdict of the Council was written into the state. */
  final: boolean;
}

export interface AgentTaskRow {
  id: number;
  agent: string;
  agent_version: string;
  task_kind: string;
  pass_kind: string;
  state: string;
  run_kind: string;
  priority: number;
  est_cost_usd: Dec;
  attempts: number;
  reason: string;
  created_at: Iso;
  deadline_at: Iso;
}

export interface AgentRunRow {
  id: number;
  agent: string;
  agent_version: string;
  task_kind: string;
  pass_kind: string;
  run_kind: string;
  status: string;
  model: string | null;
  verdict: string | null;
  started_at: Iso;
  finished_at: Iso;
  cost_usd: Dec;
  reason: string;
}

/** The file of a match: its current live state, every state it went through (newest first), and the tasks and attempts of the agents on it. */
export interface MatchState {
  fixture_id: number;
  /** The newest live state: what `ai.match_state` says. */
  current: MatchStateRow | null;
  history: MatchStateRow[];
  tasks: AgentTaskRow[];
  runs: AgentRunRow[];
}
