/**
 * The pure parts of the model-code panel (plan F12): what a fingerprint produced in the order the plan reads it, the
 * words of a status, and the fingerprints newest first. Kept out of the component so the page and its tests share them.
 */
import { translateOr } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import type { CodeFingerprint } from "@/lib/api/v1/types_ai";

/** What a fingerprint produced, in the order the plan reads it; any other source follows by name. */
export const SOURCE_ORDER = ["predictions", "forecasts", "decisions"];
/** The other kinds of promotion, in the order shown; any other follows by name. */
export const OTHER_ORDER = ["calibrator", "goal_spec", "market_edge", "neutral_rule"];

/** Known names first, in their order, then the rest alphabetically. */
export function ordered(keys: string[], first: string[]): string[] {
  return [
    ...first.filter((k) => keys.includes(k)),
    ...keys.filter((k) => !first.includes(k)).sort(),
  ];
}

export function statusText(status: string): string {
  return translateOr(`ai.evolution.code.status.${status}`, status);
}

export function statusHelp(status: string): string {
  return translateOr(`ai.evolution.code.statusHelp.${status}`, "");
}

/** "predicciones 298 597 · pronósticos 4 895 · decisiones 4 867". */
export function producedText(rows: Record<string, number>): string {
  return ordered(Object.keys(rows), SOURCE_ORDER)
    .map((k) => `${translateOr(`ai.evolution.code.source.${k}`, k)} ${localInt(rows[k] ?? 0)}`)
    .join(" · ");
}

/** The newest first: what changed last is what the owner opens the panel to see. */
export function newestFirst(list: CodeFingerprint[]): CodeFingerprint[] {
  return [...list].sort((a, b) => Date.parse(b.appeared_at) - Date.parse(a.appeared_at));
}
