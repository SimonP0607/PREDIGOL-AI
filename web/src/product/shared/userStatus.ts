/**
 * The words and tones of the four visible states of a pick (plan UX, B3; the one table, backend fbi/picks/user_status.py). The
 * badge is UserStatusBadge.tsx.
 */
import type { BadgeTone } from "@/components/primitives/StatusBadge";
import { t } from "@/lib/i18n";
import type { StatusReason, UserStatus } from "@/lib/api/v1/types_product";

export const USER_STATUSES: readonly UserStatus[] = [
  "RECOMMENDED",
  "CAUTION",
  "NOT_RECOMMENDED",
  "EVALUATION",
];

export const STATUS_TONE: Record<UserStatus, BadgeTone> = {
  // gold is what PrediGol recommends («Noche de partido»); green stays for a result won
  RECOMMENDED: "gold",
  CAUTION: "warning",
  NOT_RECOMMENDED: "negative",
  EVALUATION: "info",
};

/** «Recomendado», «Cautela»...: the state in words. */
export function statusText(status: UserStatus): string {
  return t(`picks.status.${status}`);
}

/** Why the state is the one it is, in one sentence. */
export function reasonText(reason: StatusReason): string {
  return t(`picks.status.reason.${reason}`);
}
