/** The figures of the owner's card «Opinión de los lectores» (plan UX, B6) that need no screen. */
import type { FeedbackOverview } from "@/lib/api/v1/types_feedback";

/** Below this many answers the figures carry «muestra pequeña». */
export const SMALL_SAMPLE = 30;
export const PERIODS = [30, 90, 365] as const;

/** The CSAT: the share of answers of 4 or 5; null without answers. */
export function csat(o: FeedbackOverview): number | null {
  const n = o.survey.n;
  if (n <= 0) return null;
  return ((o.survey.scores["4"] ?? 0) + (o.survey.scores["5"] ?? 0)) / n;
}
