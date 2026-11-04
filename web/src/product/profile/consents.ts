/**
 * The consents as the profile shows them (plan UX, A4 and B8): which purposes the Privacy block lists, and the weekly
 * summary by e-mail as Notificaciones shows it - only while the API offers it to the reader, or to leave it.
 */
import type { ConsentPurpose, ConsentRecord, ConsentState } from "@/lib/api/v1/types_customer";

export const DIGEST_PURPOSE = "marketing_email";

export function latestOf(
  history: readonly ConsentRecord[],
  kind: string,
): ConsentRecord | undefined {
  return history.find((r) => r.kind === kind);
}

/** What the Privacy block lists: every purpose the gate asks for, and an optional one (B8) once the reader decided. */
export function shownPurposes(state: Pick<ConsentState, "purposes" | "history">): ConsentPurpose[] {
  return state.purposes.filter((p) => p.required || latestOf(state.history, p.kind));
}

export interface DigestState {
  purpose: ConsentPurpose;
  /** The reader's latest decision on it, if any: on only while it is a grant. */
  latest: ConsentRecord | undefined;
}

/** The weekly summary as the consents say it, or null when the API does not offer it to this reader. */
export function digestOf(state: ConsentState | undefined): DigestState | null {
  const purpose = state?.purposes.find((p) => p.kind === DIGEST_PURPOSE);
  if (!state || !purpose) return null;
  return { purpose, latest: latestOf(state.history, DIGEST_PURPOSE) };
}
