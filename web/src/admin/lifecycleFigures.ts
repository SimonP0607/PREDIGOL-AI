import type { LifecycleState } from "@/lib/api/v1/types_customers";
import type { LifecycleRate } from "@/lib/api/v1/types_events";
import { t, translateOr } from "@/lib/i18n";
import { localPct } from "@/lib/i18n/format";

/** The seven states, in the order the owner reads them. */
export const CUSTOMER_STATES: readonly LifecycleState[] = [
  "invited",
  "activated",
  "habitual",
  "at_risk",
  "expiring",
  "renewed",
  "expired",
];

/** The reason codes the page writes; the backend's closed list (``fbi.customer.lifecycle.REASONS``) must equal it. */
export const LIFECYCLE_REASONS: readonly string[] = [
  "membership_expired",
  "membership_grace",
  "membership_expiring",
  "membership_renewed",
  "silent_7d",
  "low_survey",
  "ticket_waiting_72h",
  "used_3_of_7_days",
  "some_use",
  "never_used",
  "account_invited",
  "account_activated",
];

/** The words for a reason code of the lifecycle; a code this page does not know is left out, never shown raw. */
export function lifecycleReasons(reasons: readonly string[]): string[] {
  return reasons.flatMap((code) => {
    const text = translateOr(`admin.customers.lifecycle.reason.${code}`, "");
    return text ? [text] : [];
  });
}

/** A calendar day (``2026-11-03``) as a date, whatever the zone: read at noon UTC so no zone moves it. */
export function calendarDay(day: string): string {
  return `${day}T12:00:00Z`;
}

/** A share of a cohort under this many readers is not shown. */
export const COHORT_MIN = 30;

/** A rate as the owner reads it: the share, or why there is none. */
export function rateText(r: LifecycleRate): string {
  return r.value === null
    ? t("admin.product.lifecycle.insufficient", { n: r.of, min: COHORT_MIN })
    : `${localPct(r.value, 1)} (${r.n}/${r.of})`;
}
