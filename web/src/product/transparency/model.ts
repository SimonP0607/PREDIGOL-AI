/**
 * «Cómo le va a PrediGol» (plan UX, A12), the words and numbers of the page - pure, so a test reads them without a page.
 * Every figure comes from the API with its sample; nothing here computes a return, it only says what the server counted.
 */
import { t } from "@/lib/i18n";
import { DASH, localFixed, localInt, localPct, toNumber } from "@/lib/i18n/format";
import { formatDateYear } from "@/lib/time";
import type {
  DecisionStop,
  NoPickDayReason,
  NoPickDays,
  PublishedPickResult,
  TransparencyDefinition,
  TransparencyTally,
} from "@/lib/api/v1/types_transparency";
import { UPDATES, type UpdateEntry } from "@/product/updates/updates";

/** The decision layer's filters in their order (a tie of commonest stops goes to the earlier one, as on the server). */
export const STOP_ORDER: readonly DecisionStop[] = [
  "data",
  "model",
  "market",
  "calibration",
  "ev",
  "context",
  "risk",
  "correlation",
  "price",
  "final",
];
export const REASON_ORDER: readonly NoPickDayReason[] = [
  "no_qualified_candidates",
  "not_chosen",
  "no_matches",
];
/** The outcomes of a tally, in the order the page shows them (pending last). */
export const COUNT_ORDER = [
  "won",
  "lost",
  "half_won",
  "half_lost",
  "push",
  "void",
  "pending",
] as const;
export type CountKey = (typeof COUNT_ORDER)[number];

/** A day (YYYY-MM-DD, no hour) as «4 oct 2026», never moved by the reader's time zone. */
export function dayText(day: string | null | undefined): string {
  if (!day) return DASH;
  return formatDateYear(`${day}T12:00:00Z`, "UTC");
}

/** The outcomes with at least one pick, in order. */
export function countsOf(tally: TransparencyTally): Array<[CountKey, number]> {
  return COUNT_ORDER.map((k) => [k, tally[k]] as [CountKey, number]).filter(([, n]) => n > 0);
}

/** «+2,4 %» - the return of the settled stakes; a dash below the sample. */
export function roiText(tally: TransparencyTally): string {
  const roi = toNumber(tally.roi);
  return roi === null ? DASH : localPct(roi, 1, true);
}

/** «18» - one standard error of the return, in points. */
export function marginPoints(tally: TransparencyTally): string {
  const margin = toNumber(tally.margin);
  return margin === null ? DASH : localFixed(margin * 100, 0);
}

/** What the reader is told about a tally's sample: nothing to count, counts only (with its n), or a return that does not
 * allow a conclusion yet. Null when the sample is big enough to say nothing more. */
export function sampleNote(
  tally: TransparencyTally,
  minSample: number,
  conclusive: number,
  scope: "published" | "parlays" = "published",
): string | null {
  if (tally.published === 0) return t(`transparency.${scope}.none`);
  if (tally.units === null) {
    return tally.settled > 0 ? t(`transparency.${scope}.small`, { count: tally.settled }) : null;
  }
  return tally.conclusive
    ? null
    : t(`transparency.${scope}.inconclusive`, { count: conclusive || minSample });
}

/** The commonest stop of the days without picks (a tie goes to the earlier filter). */
export function topStop(stops: NoPickDays["stops"]): DecisionStop | null {
  let best: DecisionStop | null = null;
  let most = 0;
  for (const key of STOP_ORDER) {
    const n = stops[key] ?? 0;
    if (n > most) {
      best = key;
      most = n;
    }
  }
  return best;
}

/** The reasons of the days without picks, the most telling first, with how many days each. */
export function reasonsOf(days: NoPickDays): Array<[NoPickDayReason, number]> {
  return REASON_ORDER.map((r) => [r, days.reasons[r] ?? 0] as [NoPickDayReason, number]).filter(
    ([, n]) => n > 0,
  );
}

/** A share as a percentage in the reader's language («80 %» / «80%»), signed when asked («+2,6 %»). */
export function pctText(
  share: string | number | null | undefined,
  digits = 0,
  signed = false,
): string {
  const n = toNumber(share);
  return n === null ? DASH : localPct(n, digits, signed);
}

/** A share as a whole percentage («35»). */
export function percentOf(share: string | number | null | undefined): string {
  const n = toNumber(share);
  return n === null ? DASH : localFixed(n * 100, 0);
}

export function intText(n: number | null | undefined): string {
  return n === null || n === undefined ? DASH : localInt(n);
}

/** How a published pick ended, as the tone its badge takes: the ones that paid, the ones that did not, the rest. */
export function resultTone(result: PublishedPickResult): "positive" | "negative" | "neutral" {
  if (result === "WIN" || result === "HALF_WIN") return "positive";
  if (result === "LOSS" || result === "HALF_LOSS") return "negative";
  return "neutral";
}

/** The score of a finished match, «2–1»; null before it has one. */
export function scoreText(home: number | null, away: number | null): string | null {
  return home === null || away === null ? null : `${home}–${away}`;
}

/** A line of the history of changes: a Novedad of the readers' page, or the day a definition of this page came into force. */
export type Change =
  | { kind: "novelty"; day: string; id: string; key: string }
  | { kind: "definition"; day: string; id: string; key: string; version: string };

/**
 * The history of changes of this page (plan de cierre UX, 1.5): Novedades and the dated definitions together, the newest
 * first; on the same day a Novedad comes before a definition. Nothing is invented: each line is an entry of Novedades or a
 * definition the server states, with the day it came in.
 */
export function changesOf(
  definitions: readonly TransparencyDefinition[],
  updates: readonly UpdateEntry[] = UPDATES,
): Change[] {
  const out: Change[] = [
    ...updates.map((u): Change => ({
      kind: "novelty",
      day: u.id.slice(0, 10),
      id: u.id,
      key: u.key,
    })),
    ...definitions.map((d): Change => ({
      kind: "definition",
      day: d.since,
      id: `definition-${d.key}`,
      key: d.key,
      version: d.version,
    })),
  ];
  const rank = (c: Change) => (c.kind === "novelty" ? 0 : 1);
  return out.sort(
    (a, b) => b.day.localeCompare(a.day) || rank(a) - rank(b) || a.id.localeCompare(b.id),
  );
}
