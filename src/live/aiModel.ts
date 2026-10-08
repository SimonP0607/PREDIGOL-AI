/**
 * Pure rules of the AI decision layer's screens: which tone a decision or a status gets, which answers the
 * owner may give a hypothesis at each stage, and when a promotion is possible. Kept apart from the
 * components so they can be tested without rendering.
 */
import type { BadgeTone } from "@/components/primitives/StatusBadge";
import type { HypothesisDecision, HypothesisStatus, Hypothesis } from "@/lib/api/v1/types_ai";
import type { AiDecision, CardVerdict, EvidenceStatus } from "@/lib/api/v1/types_ai_layer";
import type { ParlayProgress } from "@/lib/api/v1/types_records";

export const DECISION_TONE: Record<AiDecision, BadgeTone> = {
  APPROVE: "positive",
  DOWNGRADE: "warning",
  REJECT: "negative",
  ABSTAIN: "neutral",
};

export const VERDICT_TONE: Record<CardVerdict, BadgeTone> = {
  recommended: "positive",
  caution: "warning",
  not_recommended: "negative",
  no_market: "info",
};

export const EVIDENCE_TONE: Record<EvidenceStatus, BadgeTone> = {
  CONFIRMED: "positive",
  PROBABLE: "info",
  RUMOR: "warning",
  CONTRADICTORY: "negative",
  OUTDATED: "neutral",
};

export const PROGRESS_TONE: Record<ParlayProgress, BadgeTone> = {
  OPEN: "info",
  PARTIAL_WON: "positive",
  PARTIAL_LOST: "negative",
  WON: "positive",
  LOST: "negative",
  VOID: "neutral",
};

export const HYPOTHESIS_TONE: Record<HypothesisStatus, BadgeTone> = {
  PROPOSED: "info",
  INVESTIGATING: "warning",
  ACCEPTED: "brand",
  REJECTED: "neutral",
  RUNNING: "brand",
  SHADOW: "brand",
  DONE: "positive",
  PROMOTED: "positive",
};

/** The owner's answers at each stage. Nothing here is automatic and none of them changes production. */
export function decisionsFor(status: HypothesisStatus): HypothesisDecision[] {
  if (status === "PROPOSED") return ["reject", "investigate", "approve_experiment"];
  if (status === "INVESTIGATING") return ["reject", "approve_experiment"];
  return [];
}

/** Only a DONE experiment whose gate passed can be promoted - by the owner, explicitly. */
export function canPromote(h: Pick<Hypothesis, "status" | "outcome">): boolean {
  return h.status === "DONE" && h.outcome?.["gate_passed"] === true;
}

export type HypothesisGroup = "pending" | "experiment" | "promotable" | "closed";

export function groupOf(h: Pick<Hypothesis, "status" | "outcome">): HypothesisGroup {
  if (h.status === "PROPOSED" || h.status === "INVESTIGATING") return "pending";
  if (h.status === "ACCEPTED" || h.status === "RUNNING" || h.status === "SHADOW")
    return "experiment";
  if (canPromote(h)) return "promotable";
  return "closed";
}

/** The typed word that unlocks a promotion (the button stays disabled until it matches). */
export const PROMOTE_WORD = "PROMOVER";

export function promoteUnlocked(typed: string): boolean {
  return typed.trim().toUpperCase() === PROMOTE_WORD;
}

/** A decimal probability ("0.4512") as a whole percentage with one decimal, or null. */
export function pct(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? Math.round(n * 1000) / 10 : null;
}

/** "Analizado por PrediGol AI" only when a language model took part; the rules alone say so. */
export function analysisLabel(byLlm: boolean): "ai" | "rules" {
  return byLlm ? "ai" : "rules";
}
