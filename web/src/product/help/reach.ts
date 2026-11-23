/**
 * Which channels of the help are published (plan AP-H01, finding H3): the answers of the help and of its assistant
 * name only a channel the owner published (FBI_SUPPORT_CHANNELS and the number / address behind it), never one that is
 * not there. Without a WhatsApp number the answer points inside the app: «Ayuda → Hablar con una persona».
 */
import type { ContactChannel, SupportContact } from "@/lib/api/v1/types_support";
import { t } from "@/lib/i18n";

export interface Reach {
  whatsapp: boolean;
  email: boolean;
}

/** Nothing known yet (loading, or the contact did not arrive): no channel is named. */
export const NO_REACH: Reach = { whatsapp: false, email: false };

/**
 * The channels that are on: the number or address exists AND the owner's list (when the server sends one) keeps it.
 * An older answer without the list keeps every channel that has its data.
 */
export function reachOf(contact: SupportContact | null | undefined): Reach {
  if (!contact) return NO_REACH;
  const listed: readonly ContactChannel[] | null = contact.channels?.length
    ? contact.channels
    : null;
  const on = (channel: ContactChannel) => listed === null || listed.includes(channel);
  return {
    whatsapp: Boolean(contact.whatsapp) && on("whatsapp"),
    email: Boolean(contact.email) && on("email"),
  };
}

export type ReachKey = "both" | "whatsapp" | "email" | "none";

export function reachKey(reach: Reach): ReachKey {
  if (reach.whatsapp && reach.email) return "both";
  if (reach.whatsapp) return "whatsapp";
  if (reach.email) return "email";
  return "none";
}

/** «escríbenos por WhatsApp o por correo» - lower case, to sit inside a sentence; only the published channels. */
export function reachPhrase(reach: Reach): string {
  return t(`support.reach.${reachKey(reach)}`);
}
