/** The monthly survey's scale and limits (plan UX, B6; section 40). */

export const SCORES = [1, 2, 3, 4, 5] as const;
/** The comment's limit (fbi.customer.feedback.COMMENT_MAX). */
export const COMMENT_MAX = 1000;

/** The optional question a score leads to: what was missing (1-3) or what was most useful (4-5). */
export function commentQuestion(score: number): "missing" | "best" {
  return score <= 3 ? "missing" : "best";
}
