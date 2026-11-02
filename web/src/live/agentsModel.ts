/**
 * The Agentes tab of Operación (plan IA, phase 1): what the page concludes from the figures it is given. Pure functions - the words come from the
 * catalogs, the verdicts from the numbers - so each verdict can be tested without a screen. Nothing here asks the server for anything.
 */
import type { BadgeTone } from "@/components/primitives/StatusBadge";
import type {
  AgentTaskView,
  AgentView,
  AgentsOverview,
  AuditRule,
  FamilyEngine,
  MatchStateRow,
  PromotionRow,
  SliceStat,
} from "@/lib/api/v1/types_ai_agents";

/** The states of a task, in the order of its life (the vocabulary of ai.agent_tasks). */
export const TASK_STATES = [
  "planned",
  "queued",
  "running",
  "done",
  "failed",
  "skipped",
  "expired",
] as const;
/** The statuses of an attempt (the vocabulary of ai.agent_runs). */
export const RUN_STATUSES = [
  "ok",
  "invalid",
  "timeout",
  "abstain",
  "skipped",
  "expired",
  "budget_skip",
] as const;
/** The passes of a match: the three of its day in the order they happen, then the one the owner asks for by hand. */
export const PASSES = ["first", "pre", "final", "request"] as const;

/** A slice whose 95th percentile has reached this share of its cap is called near it. */
export const NEAR_CAP = 0.8;

/**
 * The counts of a vocabulary in the order of the vocabulary, then any word the server sent that this page does not know (never hidden).
 * With `fill`, a word of the vocabulary the server did not send shows as zero.
 */
export function orderedCounts(
  counts: Readonly<Record<string, number>>,
  order: readonly string[],
  fill = false,
): Array<[string, number]> {
  const rows: Array<[string, number]> = [];
  for (const key of order) {
    const n = counts[key];
    if (n !== undefined) rows.push([key, n]);
    else if (fill) rows.push([key, 0]);
  }
  for (const key of Object.keys(counts).sort()) {
    if (!order.includes(key)) rows.push([key, counts[key] ?? 0]);
  }
  return rows;
}

export type SliceLevel = "over" | "cut" | "near" | "ok";

/** The 95th percentile of a slice as a share of its cap; null when the cap is not a positive number. */
export function capShare(s: Pick<SliceStat, "tokens_p95" | "cap">): number | null {
  return s.cap > 0 ? s.tokens_p95 / s.cap : null;
}

/**
 * How a slice stands against its cap. `over`: in some state it does not fit (an agent would refuse it). `cut`: something was taken out of
 * it to fit - if that is the usual case the cap is biting. `near`: the 95th percentile is close to the cap. `ok`: room to spare.
 */
export function sliceLevel(s: SliceStat): SliceLevel {
  if (s.over_cap > 0) return "over";
  if (s.trimmed > 0) return "cut";
  const share = capShare(s);
  return share !== null && share >= NEAR_CAP ? "near" : "ok";
}

export const SLICE_TONE: Record<SliceLevel, BadgeTone> = {
  over: "negative",
  cut: "warning",
  near: "info",
  ok: "positive",
};

export type AuditVerdict = "never" | "clean" | "violations";

/** A rule with no audited day has not been run: that is not a clean record. */
export function auditVerdict(r: Pick<AuditRule, "days_audited" | "violations">): AuditVerdict {
  if (r.days_audited === 0) return "never";
  return r.violations > 0 ? "violations" : "clean";
}

export const AUDIT_TONE: Record<AuditVerdict, BadgeTone> = {
  never: "neutral",
  clean: "positive",
  violations: "negative",
};

export type SyncState = "in_sync" | "drift" | "none";

/** Whether the code that runs is the one the ledger holds. Only a built agent has code to compare. */
export function syncState(a: Pick<AgentView, "status" | "in_sync">): SyncState {
  if (a.status !== "built" || a.in_sync === null) return "none";
  return a.in_sync ? "in_sync" : "drift";
}

export const SYNC_TONE: Record<SyncState, BadgeTone> = {
  in_sync: "positive",
  drift: "negative",
  none: "neutral",
};

export const STATUS_TONE: Record<AgentView["status"], BadgeTone> = {
  built: "positive",
  planned: "info",
  postponed: "neutral",
};

export const ENGINE_TONE: Record<FamilyEngine["engine"], BadgeTone> = {
  llm: "neutral",
  agent: "brand",
};

/**
 * What tells one row of the registry from another. An agent can be on it twice - built (the version in force) and planned (the one that grows
 * out of it: the extractor, the Post-Match Reviewer and the Learning Analyst are) - so the name alone is not a key; the name and the status are.
 */
export function registryKey(a: Pick<AgentView, "agent" | "status">): string {
  return `${a.agent}:${a.status}`;
}

export interface RegistryCounts {
  built: number;
  planned: number;
  postponed: number;
  /** Built agents whose code is not the one registered. */
  drift: number;
}

export function registryCounts(registry: readonly AgentView[]): RegistryCounts {
  const count = (status: AgentView["status"]) => registry.filter((a) => a.status === status).length;
  return {
    built: count("built"),
    planned: count("planned"),
    postponed: count("postponed"),
    drift: registry.filter((a) => syncState(a) === "drift").length,
  };
}

export type AttentionCode =
  | "audit_violations"
  | "drift"
  | "registry_problems"
  | "slices_over_cap"
  | "job_failed"
  | "job_partial"
  | "job_off";

export interface Attention {
  code: AttentionCode;
  /** How many: findings, agents, violations, slices. 1 for the state of the job. */
  n: number;
}

/**
 * What the owner should look at, most serious first: a state that knew more than its moment, code that is not the one registered, the
 * registry disagreeing with itself, a slice that does not fit, the state job failing or stopped. Empty when there is nothing.
 */
export function attention(o: AgentsOverview): Attention[] {
  const found: Attention[] = [];
  const violations = o.audit.reduce((sum, r) => sum + r.violations, 0);
  if (violations > 0) found.push({ code: "audit_violations", n: violations });
  const drift = registryCounts(o.registry).drift;
  if (drift > 0) found.push({ code: "drift", n: drift });
  if (o.problems.length > 0) found.push({ code: "registry_problems", n: o.problems.length });
  const over = o.package.slices.filter((s) => s.over_cap > 0).length;
  if (over > 0) found.push({ code: "slices_over_cap", n: over });
  const last = o.package.cycles.last?.status;
  if (last === "failed") found.push({ code: "job_failed", n: 1 });
  if (last === "partial") found.push({ code: "job_partial", n: 1 });
  // With the whole layer off, a stopped job is what was asked for.
  if (o.settings.mode !== "off" && !o.settings.package) found.push({ code: "job_off", n: 1 });
  return found;
}

/** What a decision changed: "CHAMPION → RETIRED"; a first role has no origin. */
export function decisionChange(d: Pick<PromotionRow, "from_role" | "to_role">): string {
  return `${d.from_role ?? "—"} → ${d.to_role}`;
}

/** The tokens of every slice of a state, added up. */
export function totalTokens(row: Pick<MatchStateRow, "slices">): number {
  return row.slices.reduce((sum, s) => sum + s.tokens, 0);
}

/** The slices of a state that do not fit their cap. */
export function slicesOver(row: Pick<MatchStateRow, "slices">): string[] {
  return row.slices.filter((s) => !s.fits).map((s) => s.name);
}

/**
 * A task of an agent on one line: its name, the prompt it runs, what it runs on (the model it pins, else the tier of the old route) and its effort.
 * A part the registry does not have is left out, not shown as a dash.
 */
export function taskLine(
  t: Pick<AgentTaskView, "task" | "prompt_version" | "model" | "tier" | "effort">,
): string {
  return [t.task, t.prompt_version, t.model ?? t.tier, t.effort].filter((x) => x).join(" · ");
}

/**
 * The agent a family reads, as the promotion row names it: `council@council-v1+match-v1`, whole - it is the exact name the owner signed. A name
 * this code does not read has no agent and no version: it is shown as it is, and the page says it is not understood.
 */
export function promotionLine(f: Pick<FamilyEngine, "engine" | "promotion" | "agent">): {
  name: string | null;
  understood: boolean;
} {
  if (f.engine !== "agent") return { name: null, understood: true };
  return { name: f.promotion, understood: f.agent !== null };
}
