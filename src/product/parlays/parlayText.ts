/** Names, icons and the one-line scope of a parlay ("5 selecciones · próximas 24 h"). */
import { CalendarRange, Layers, type LucideIcon } from "lucide-react";
import { t } from "@/lib/i18n";
import type { Parlay, ParlayKind } from "@/lib/api/v1/types_product";

export function parlayTitle(kind: ParlayKind): string {
  return kind === "daily" ? t("parlays.kind.daily") : t("parlays.kind.multiday");
}

export const PARLAY_ICON: Record<ParlayKind, LucideIcon> = {
  daily: Layers,
  multiday: CalendarRange,
};

/** The window the parlay looks at, from its own bounds: "próximas 24 h", "próximos 2 días". */
function windowLabel(from: string, to: string): string {
  const ms = Date.parse(to) - Date.parse(from);
  if (!Number.isFinite(ms) || ms <= 0) return "";
  const hours = Math.round(ms / 3_600_000);
  if (hours <= 36) return t("parlays.window.hours", { count: hours });
  return t("parlays.window.days", { count: Math.round(hours / 24) });
}

/**
 * The legs it has (when there is a parlay) or the legs it needs (when there is none),
 * then its window.
 */
export function parlayScope(
  p: Pick<Parlay, "status" | "legs" | "required_legs" | "max_legs" | "window_from" | "window_to">,
): string {
  const legs =
    p.status === "ok" && p.legs.length > 0
      ? t("parlays.legs", { count: p.legs.length })
      : p.max_legs > p.required_legs
        ? t("parlays.legsRange", { min: p.required_legs, max: p.max_legs })
        : t("parlays.legs", { count: p.required_legs });
  const span = windowLabel(p.window_from, p.window_to);
  return span ? `${legs} · ${span}` : legs;
}
