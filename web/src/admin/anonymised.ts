/** What the console says about an anonymised account (plan UX, A7). */
import type { AdminAnonymised } from "@/lib/api/v1/types_auth";
import { t } from "@/lib/i18n";

/** The address an anonymised account keeps (``deleted-<id>@deleted.invalid``): nothing is ever sent to it. */
export function isAnonymised(email: string): boolean {
  return email.endsWith("@deleted.invalid");
}

/** The counts of an anonymisation, in one sentence. */
export function anonymisedSummary(r: AdminAnonymised): string {
  return t("admin.users.anonymiseDone", {
    picks: r.picks,
    parlays: r.parlays,
    sessions: r.sessions,
    messages: r.messages_dropped,
    trail: r.trail_rows,
  });
}
