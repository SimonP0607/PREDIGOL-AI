/** The day navigation of the day's picks (REVIEW PREDIGOL, point 12), pure. */
import type { DailyItem } from "@/lib/api/v1/types_records";
import { toNumber } from "@/lib/i18n/format";
import { shiftDay } from "@/lib/time";

/** Today and the six days before it, newest first: the days a reader jumps to. */
export function recentDays(today: string, count = 7): string[] {
  return Array.from({ length: count }, (_, i) => shiftDay(today, -i));
}

export interface DaySummary {
  count: number;
  won: number;
  lost: number;
  open: number;
  /** Profit in units over the settled picks; null while none is settled. */
  units: number | null;
}

/** What a day's set came to: half results count with their side, a push or void is neither. */
export function daySummary(
  items: readonly Pick<DailyItem, "status" | "profit_units">[],
): DaySummary {
  let won = 0;
  let lost = 0;
  let open = 0;
  let units: number | null = null;
  for (const i of items) {
    if (i.status === "WIN" || i.status === "HALF_WIN") won += 1;
    else if (i.status === "LOSS" || i.status === "HALF_LOSS") lost += 1;
    else if (i.status === "PENDING") open += 1;
    const p = toNumber(i.profit_units);
    if (i.status !== "PENDING" && p !== null) units = (units ?? 0) + p;
  }
  return { count: items.length, won, lost, open, units };
}
