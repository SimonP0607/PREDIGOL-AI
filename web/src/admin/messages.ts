/** The queue of messages to readers (plan UX, A5): its statuses and the words of its templates. */
import type { MessageStatus } from "@/lib/api/v1/types_messaging";
import { translateOr } from "@/lib/i18n";

export const STATUSES: readonly MessageStatus[] = [
  "queued",
  "sent",
  "failed",
  "bounced",
  "complained",
  "suppressed",
];

/** A template's name in the console's language; a template the catalog does not know yet shows its own name. */
export function templateName(template: string): string {
  return translateOr(`admin.messages.template.${template}`, template);
}

/** The templates the console can preview (AP-M02), as the backend's catalogue names them (fbi.messaging.templates.TEMPLATES). */
export const PREVIEW_TEMPLATES: readonly string[] = [
  "welcome",
  "invitation",
  "activation_reminder",
  "email_verification",
  "account_exists",
  "password_reset",
  "account_unlock",
  "new_sign_in",
  "security_change",
  "trial_started",
  "payment_request_received",
  "payment_request_rejected",
  "payment_request_annulled",
  "payment_recorded",
  "membership_expiring",
  "membership_grace",
  "support_ticket_received",
  "support_ticket_answered",
  "privacy_request_received",
  "privacy_request_answered",
  "legal_change",
  "maintenance_scheduled",
  "incident_resolved",
  "important_change",
  "critical_notice",
  "weekly_digest",
];
