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
