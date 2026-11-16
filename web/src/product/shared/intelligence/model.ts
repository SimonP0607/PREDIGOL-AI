/**
 * The words of PrediGol Intelligence that the screens share (plan maestro unificado UX/UI e Intelligence 2026, UX-140).
 * Every value comes in the backend's contract as a closed word: the interface translates it and never deduces it. Nothing
 * here computes a probability, a price or a state.
 */

/** The life of a selection (contract rule 4): from detected to evaluated. */
export const LIFECYCLE = [
  "detected",
  "researching",
  "evaluating",
  "awaiting_lineups",
  "shadow_confirmed",
  "withdrawn",
  "discarded",
  "in_play",
  "settled",
  "evaluated",
] as const;
export type Lifecycle = (typeof LIFECYCLE)[number];

/** The states a reader may see, on what is published; the rest live only in the owner's private views. */
export const PUBLIC_LIFECYCLE: ReadonlySet<Lifecycle> = new Set<Lifecycle>(["in_play", "settled"]);

export function isLifecycle(value: unknown): value is Lifecycle {
  return typeof value === "string" && (LIFECYCLE as readonly string[]).includes(value);
}

/**
 * How sure a fact is (maqueta 16; decision D-04: no separate «Rumores» tab, every item carries its level). A rumour is
 * never told as a fact: the level says it.
 */
export const CONFIRMATION = [
  "official",
  "confirmed",
  "statement",
  "single_source",
  "contradictory",
  "unconfirmed",
] as const;
export type Confirmation = (typeof CONFIRMATION)[number];

export function isConfirmation(value: unknown): value is Confirmation {
  return typeof value === "string" && (CONFIRMATION as readonly string[]).includes(value);
}

/** The four readings of a match (E1 first reading, E2 on news, E3 official line-up, E4 close). */
export const EVALUATIONS = ["E1", "E2", "E3", "E4"] as const;
export type Evaluation = (typeof EVALUATIONS)[number];
export type StepState = "done" | "current" | "pending" | "skipped";

/** The seal of a figure (contract rule 3): calibrated or not, as the backend says. */
export type Calibration = "calibrated" | "uncalibrated";

export type Confidence = "high" | "medium" | "low";

/** Half-open bounds kept apart from formatting: a probability on show is the contract's, rounded only to print it. */
export function clampShare(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}
