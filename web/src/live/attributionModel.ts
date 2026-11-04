/**
 * The attribution page (plan IA, phase 5) without a server: where the coverage stands against the plan's bar, the order of the classes, how the ids a
 * hypothesis cites are written. Counts and shares of counts; never a verdict - Gate B is decided by the owner, not by this page.
 */
import type { AttributionCoverage, AttributionOutcome } from "@/lib/api/v1/types_ai_attribution";

/** The classes of a miss, in the order they are listed (the post-mortem's words). */
export const ERROR_CLASSES = [
  "MODEL_ERROR",
  "CONTEXT_ERROR",
  "DATA_ERROR",
  "MARKET_ERROR",
  "EXECUTION_ERROR",
  "NORMAL_VARIANCE",
  "UNKNOWN",
] as const;

export type CoverageState = "none" | "below" | "reached";

/** `none` when there is nothing to judge (zero matches is not 100 %), then below or at-or-over the bar. Says nothing about the gate. */
export function coverageState(c: Pick<AttributionCoverage, "match_share" | "bar">): CoverageState {
  if (c.match_share === null) return "none";
  return c.match_share >= c.bar ? "reached" : "below";
}

export function outcomeTone(o: AttributionOutcome): "positive" | "negative" | "neutral" {
  return o === "HIT" ? "positive" : o === "MISS" ? "negative" : "neutral";
}

/** `#12, #15, #31`: the attributions a hypothesis cites. */
export function citedIds(ids: readonly number[]): string {
  return ids.map((i) => `#${i}`).join(", ");
}

/** The classes in the plan's order, then any the server sent that this page does not know, alphabetically. */
export function sortedClasses<T extends { error_class: string }>(rows: readonly T[]): T[] {
  const rank = (c: string) => {
    const i = (ERROR_CLASSES as readonly string[]).indexOf(c);
    return i === -1 ? ERROR_CLASSES.length : i;
  };
  return [...rows].sort(
    (a, b) =>
      rank(a.error_class) - rank(b.error_class) || a.error_class.localeCompare(b.error_class),
  );
}
