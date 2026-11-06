/**
 * The consents as the profile shows them (plan UX, A4 and B8): which purposes the Privacy block lists, and the weekly
 * summary by e-mail as Notificaciones shows it - only while the API offers it to the reader, or to leave it.
 */
import type { ConsentPurpose, ConsentRecord, ConsentState } from "@/lib/api/v1/types_customer";

export const DIGEST_PURPOSE = "marketing_email";
/** The usage statistics under a pseudonym (plan de cierre UX, 1.2): an optional box of its own, never the gate's. */
export const ANALYTICS_PURPOSE = "analytics";

export function latestOf(
  history: readonly ConsentRecord[],
  kind: string,
): ConsentRecord | undefined {
  return history.find((r) => r.kind === kind);
}

/**
 * What the Privacy block lists as rows: every purpose the gate asks for, and an optional one (B8) once the reader
 * decided. The usage statistics have a switch of their own in that block, so they are not a row.
 */
export function shownPurposes(state: Pick<ConsentState, "purposes" | "history">): ConsentPurpose[] {
  return state.purposes.filter(
    (p) => p.kind !== ANALYTICS_PURPOSE && (p.required || latestOf(state.history, p.kind)),
  );
}

export interface OptionalState {
  purpose: ConsentPurpose;
  /** The reader's latest decision on it, if any: on only while it is a grant. */
  latest: ConsentRecord | undefined;
}
export type DigestState = OptionalState;

/** The usage statistics as the consents say it, or null when the API does not list the purpose. */
export function analyticsOf(state: ConsentState | undefined): OptionalState | null {
  const purpose = state?.purposes.find((p) => p.kind === ANALYTICS_PURPOSE);
  if (!state || !purpose) return null;
  return { purpose, latest: latestOf(state.history, ANALYTICS_PURPOSE) };
}

/**
 * The box the gate offers beside the ones it asks for: the usage statistics, unticked, only to a reader who never
 * answered it (a reader who did decides in their profile). It never counts for completing the gate.
 */
export function gateOptional(state: ConsentState | undefined): ConsentPurpose | null {
  const analytics = analyticsOf(state);
  return analytics && !analytics.latest ? analytics.purpose : null;
}

/** The weekly summary as the consents say it, or null when the API does not offer it to this reader. */
export function digestOf(state: ConsentState | undefined): DigestState | null {
  const purpose = state?.purposes.find((p) => p.kind === DIGEST_PURPOSE);
  if (!state || !purpose) return null;
  return { purpose, latest: latestOf(state.history, DIGEST_PURPOSE) };
}
