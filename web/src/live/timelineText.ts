/**
 * The fixture's Cronología in the reader's language. The API sends each event with a
 * `code` and `vars` (REVIEW 11 Oct 2026, point 10); an event without a code, or with a
 * code this build does not know, keeps the API's own label and detail.
 */
import type { MatchSummary, TimelineEvent } from "@/lib/api/v1/types";
import { hasKey, t } from "@/lib/i18n";

function known(key: string): boolean {
  return hasKey(key) || hasKey(key, "en");
}

/** A capture window as the label shows it: 1440 → "24h", 30 → "30m". */
export function windowLabel(minutes: string | undefined): string {
  const w = Number(minutes);
  if (!minutes || !Number.isFinite(w)) return minutes ?? "";
  return w % 60 === 0 ? `${w / 60}h` : `${w}m`;
}

/** Which label an event key takes: odds_1440 → window, extra_35 / extra_more → extra. */
function labelKey(key: string): string {
  if (key.startsWith("odds_")) return "window";
  if (key.startsWith("extra")) return "extra";
  return key;
}

export function timelineLabel(e: Pick<TimelineEvent, "key" | "label" | "code" | "vars">): string {
  if (!e.code) return e.label;
  const key = `center.timeline.label.${labelKey(e.key)}`;
  return known(key) ? t(key, { window: windowLabel(e.vars?.["window"]) }) : e.label;
}

export function timelineDetail(e: Pick<TimelineEvent, "detail" | "code" | "vars">): string {
  if (!e.code) return e.detail;
  const key = `center.timeline.code.${e.code}`;
  if (!known(key)) return e.detail;
  const vars: Record<string, string> = { ...(e.vars ?? {}) };
  const outcome = vars["outcome"];
  if (outcome && known(`center.timeline.outcome.${outcome}`)) {
    vars["outcome"] = t(`center.timeline.outcome.${outcome}`);
  }
  return t(key, vars);
}

/**
 * Who owns a missing result, for the admin (common.resultWait.long): the provider, or us.
 * `when` is the provider's last read, already formatted by the caller.
 */
export function resultWaitText(
  m: Pick<MatchSummary, "result_wait" | "status_short">,
  when: string,
): string | null {
  if (!m.result_wait) return null;
  const key = `common.resultWait.long.${m.result_wait}`;
  return known(key) ? t(key, { status: m.status_short, when }) : m.result_wait;
}

/** The provider is late (warning) or the fault is ours / the data contradicts itself (negative). */
export function resultWaitTone(code: MatchSummary["result_wait"]): "warning" | "negative" | null {
  if (!code) return null;
  return code === "provider_pending" || code === "provider_silent" ? "warning" : "negative";
}
