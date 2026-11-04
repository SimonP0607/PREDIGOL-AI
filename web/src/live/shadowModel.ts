/**
 * Pure rules of the screens of the shadow (plan IA, phase 3): the seven arms, the contradictions, the runs of the agents and the file of a match.
 * Kept apart from the components so they can be tested without rendering. Nothing here computes a metric the server did not send: a share is a count
 * over a count, the plan's thresholds are shown as counts against their numbers, and no function answers "did it pass".
 */
import type { BadgeTone } from "@/components/primitives/StatusBadge";
import { translateOr } from "@/lib/i18n";
import type {
  ArmId,
  ArmRow,
  Decisions,
  Enough,
  OpusDay,
  ShadowDecision,
  Treatment,
} from "@/lib/api/v1/types_ai_shadow";

/** The seven arms in the order of the plan's table (section 22). */
export const ARMS: readonly ArmId[] = [
  "model",
  "rules",
  "gap",
  "llm",
  "council_solo",
  "ma-v1",
  "ma-v1-h",
];
export const CONTRA_CODES = ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08"] as const;
export const TREATMENTS: readonly Treatment[] = ["kept", "lowered", "abstained", "none"];
/** The columns of the match file: today's three reviewers, then the shadow's three engines. */
export const FILE_ENGINES = ["rules", "llm", "combined", "ma-v1", "ma-v1-h", "cs-v1"] as const;
/** The engines of the shadow, in the order the file lists them. */
export const SHADOW_ENGINES = ["ma-v1", "ma-v1-h", "cs-v1"] as const;
export const AGENTS = ["match", "council"] as const;
export const TASK_KINDS = ["context", "evaluation", "council", "escalation"] as const;
export const RUN_STATUS_FILTER = [
  "ok",
  "invalid",
  "timeout",
  "abstain",
  "skipped",
  "expired",
  "budget_skip",
] as const;
export const PASS_FILTER = ["first", "pre", "final"] as const;

export const DECISION_KEYS: ReadonlyArray<readonly [keyof Decisions, ShadowDecision]> = [
  ["approved", "APPROVE"],
  ["downgraded", "DOWNGRADE"],
  ["rejected", "REJECT"],
  ["abstained", "ABSTAIN"],
];

/** part / total as a fraction; null without a positive total (a share of nothing is not zero). */
export function share(part: number, total: number): number | null {
  return total > 0 ? part / total : null;
}

/** The share of each decision of an arm over a count of reviews; null for a decision of an arm that has none (a rule). */
export function decisionShares(
  d: Decisions | null,
  total: number,
): Record<keyof Decisions, number | null> | null {
  if (d === null) return null;
  return {
    approved: share(d.approved, total),
    downgraded: share(d.downgraded, total),
    rejected: share(d.rejected, total),
    abstained: share(d.abstained, total),
  };
}

/** Invalid outputs over the reviews of the arm; null when the arm wrote none, and for an arm that is a rule (it has no output to be invalid). */
export function invalidRate(a: Pick<ArmRow, "kind" | "invalid" | "reviews">): number | null {
  return a.kind === "derived" ? null : share(a.invalid, a.reviews);
}

/** The plan's pause line for an arm: more than 3 % invalid in a day pauses it (runtime.INVALID_LIMIT_PERCENT). */
export const INVALID_LIMIT = 0.03;

export function invalidTone(rate: number | null): BadgeTone {
  if (rate === null) return "neutral";
  return rate > INVALID_LIMIT ? "warning" : "positive";
}

/** Pause reasons or silence codes of an arm, in order of count, then name. */
export function sortedCounts(counts: Readonly<Record<string, number>>): Array<[string, number]> {
  return Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function sumCounts(counts: Readonly<Record<string, number>>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}

/** The words of an arm: its plan name, looked up when called (the language changes at runtime). */
export function armLabel(arm: string): string {
  return translateOr(`ai.arms.arm.${arm}`, arm);
}

/** A contradiction code in words: the name of the rule of `contra-v1`, or the code itself when it has none. */
export function contraLabel(code: string): string {
  return translateOr(`ai.contra.code.${code}`, code);
}

export function reasonLabel(code: string): string {
  return translateOr(`ai.arms.reason.${code}`, code);
}

/**
 * Where the counts stand against the plan's thresholds (`ai-gate-v2`: 30 days, 300 selections reviewed by both engines). `both` only when both
 * counts are reached - which says there is enough to look, never that anything passed.
 */
export type EnoughState = "none" | "days" | "selections" | "both";
export function enoughState(e: Pick<Enough, "days_reached" | "selections_reached">): EnoughState {
  if (e.days_reached && e.selections_reached) return "both";
  if (e.days_reached) return "days";
  if (e.selections_reached) return "selections";
  return "none";
}

/** A count against its need, capped at 100 for a bar. */
export function progress(value: number, need: number): number {
  return need > 0 ? Math.min(100, Math.round((value / need) * 100)) : 0;
}

export type OpusLevel = "free" | "last" | "spent";
/** The day's Opus calls against the cap: `spent` at the cap (the next escalation keeps the first-round verdict), `last` one before it. */
export function opusLevel(o: Pick<OpusDay, "calls" | "cap">): OpusLevel {
  if (o.calls >= o.cap) return "spent";
  return o.calls === o.cap - 1 ? "last" : "free";
}
export const OPUS_TONE: Record<OpusLevel, BadgeTone> = {
  free: "positive",
  last: "warning",
  spent: "negative",
};

export const TREATMENT_TONE: Record<Treatment, BadgeTone> = {
  kept: "positive",
  lowered: "warning",
  abstained: "neutral",
  none: "neutral",
};

/** The shadow engines' cells that carry a verdict versus those that do not: the count the match file shows under a column. */
export function answered(cells: ReadonlyArray<{ decision: string | null }>): number {
  return cells.filter((c) => c.decision !== null).length;
}

/** `E7`-style rules sorted; anything else the server sent is kept as given. */
export function ruleLine(escalation: string | null, fired: readonly string[]): string | null {
  const all = [...new Set([...(escalation ? [escalation] : []), ...fired])];
  return all.length > 0 ? all.join(" · ") : null;
}

/** Two verdicts differ: both are present and not the same word. Used to mark a disagreement beside today's reviewers. */
export function disagrees(a: string | null, b: string | null): boolean {
  return a !== null && b !== null && a !== b;
}

/** How a run of ``ai.agent_runs`` ended, as a tone: a paid answer is fine, an answer that did not stand or a call that did not happen is not. */
export const RUN_TONE: Record<string, BadgeTone> = {
  ok: "positive",
  abstain: "neutral",
  invalid: "warning",
  timeout: "negative",
  skipped: "neutral",
  expired: "negative",
  budget_skip: "warning",
};

/** How a review of an engine ended (``ai.pick_reviews.status``). */
export const REVIEW_TONE: Record<string, BadgeTone> = {
  ok: "positive",
  fallback: "neutral",
  invalid_output: "warning",
  failed: "negative",
  over_budget: "warning",
};
