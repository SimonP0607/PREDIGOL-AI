/** Names and icons of PrediGol's two parlays. */
import { CalendarRange, Layers, type LucideIcon } from "lucide-react";
import { t } from "@/lib/i18n";
import type { ParlayKind } from "@/lib/api/v1/types_product";

export function parlayTitle(kind: ParlayKind): string {
  return kind === "daily" ? t("parlays.kind.daily") : t("parlays.kind.multiday");
}

export const PARLAY_ICON: Record<ParlayKind, LucideIcon> = {
  daily: Layers,
  multiday: CalendarRange,
};
