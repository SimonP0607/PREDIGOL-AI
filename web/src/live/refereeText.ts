/** Referees as people (plan F3): the small pure rules the pages share (labels, which side a pair keeps, what can be undone). */
import { translateOr } from "@/lib/i18n";
import type { RefereeCounts, RefereeEvent, RefereeSide } from "@/lib/api/v1/types_referees";

/** The reasons a pair is doubted, in the order the filter offers them. */
export const REASONS = [
  "same_name_other_scope",
  "longer_name",
  "initial_and_full",
  "spelling_variant",
] as const;

export function reasonLabel(code: string): string {
  return translateOr(`referees.reasons.${code}`, code);
}

export function basisLabel(code: string): string {
  return translateOr(`referees.basis.${code}`, code);
}

/** One way to settle a pair as "the same person": `keepId` stays, `mergeId` is merged into it. */
export interface KeepOption {
  keepId: number;
  mergeId: number;
  name: string;
}

/** The two ways, the busier name first: the person keeps the name the provider used most. */
export function keepOptions(a: RefereeSide, b: RefereeSide): [KeepOption, KeepOption] {
  const first = a.matches >= b.matches ? a : b;
  const second = first === a ? b : a;
  return [
    { keepId: first.id, mergeId: second.id, name: first.name },
    { keepId: second.id, mergeId: first.id, name: second.name },
  ];
}

/** The API refuses a merge of two men who have matches at the same time with a 409 (`force` overrides it). */
export function isConflict(error: unknown): boolean {
  return (
    typeof error === "object" && error !== null && (error as { status?: unknown }).status === 409
  );
}

/** Only a merge that nothing has taken back can be undone. */
export function canUndo(event: Pick<RefereeEvent, "action" | "undone_by">): boolean {
  return event.action === "merge" && event.undone_by === null;
}

/** The share of matches without a doubt waiting, as a fraction (the API gives 0..1). */
export function settledShare(counts: Pick<RefereeCounts, "settled_share">): number {
  const v = counts.settled_share;
  return Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0;
}

/** The ids ticked in the list of spellings, in the order of the list (what a split sends). */
export function pickedAliases(ids: readonly number[], ticked: ReadonlySet<number>): number[] {
  return ids.filter((id) => ticked.has(id));
}
