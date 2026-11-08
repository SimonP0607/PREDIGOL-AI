/** The day navigation of the day's picks (REVIEW PREDIGOL, point 12), pure. */
import type { DailyItem } from "@/lib/api/v1/types_records";
import { toNumber } from "@/lib/i18n/format";
import { shiftDay } from "@/lib/time";
import { t } from "@/lib/i18n";

/** Today and the six days before it, newest first: the days a reader jumps to. */
export function recentDays(today: string, count = 7): string[] {
  return Array.from({ length: count }, (_, i) => shiftDay(today, -i));
}

export interface DaySummary {
  count: number;
  /** Won, half wins included (they are also counted in ``halfWon``). */
  won: number;
  /** Lost, half losses included (they are also counted in ``halfLost``). */
  lost: number;
  /** Pushes and voids: the stake came back. */
  voids: number;
  open: number;
  /** Half wins (a quarter line): already inside ``won``. */
  halfWon: number;
  /** Half losses (a quarter line): already inside ``lost``. */
  halfLost: number;
  /** Profit in units over the settled picks; null while none is settled. */
  units: number | null;
}

/** What a day's set came to: half results count with their side, a push or void is neither. */
export function daySummary(
  items: readonly Pick<DailyItem, "status" | "profit_units">[],
): DaySummary {
  let won = 0;
  let lost = 0;
  let voids = 0;
  let open = 0;
  let halfWon = 0;
  let halfLost = 0;
  let units: number | null = null;
  for (const i of items) {
    if (i.status === "WIN" || i.status === "HALF_WIN") won += 1;
    else if (i.status === "LOSS" || i.status === "HALF_LOSS") lost += 1;
    else if (i.status === "PUSH" || i.status === "VOID") voids += 1;
    else open += 1;
    if (i.status === "HALF_WIN") halfWon += 1;
    if (i.status === "HALF_LOSS") halfLost += 1;
    const p = toNumber(i.profit_units);
    if (i.status !== "PENDING" && p !== null) units = (units ?? 0) + p;
  }
  // Every pick counts once: won + lost + voids + open = count (plan PICKS, D3).
  return { count: items.length, won, lost, voids, open, halfWon, halfLost, units };
}

/** «1 ganado (1 a medias)»: a half result is said beside its own side, never at the end of the sentence. */
function withHalves(part: string, halves: number): string {
  return halves > 0 ? `${part} ${t("records.dayNav.parts.halves", { count: halves })}` : part;
}

/** The day in words: every pick once, nulls and voids apart, half results beside their side (plan PICKS, D3). */
export function summaryText(sum: DaySummary): string {
  return [
    t("records.dayNav.parts.picks", { count: sum.count }),
    withHalves(t("records.dayNav.parts.won", { count: sum.won }), sum.halfWon),
    withHalves(t("records.dayNav.parts.lost", { count: sum.lost }), sum.halfLost),
    ...(sum.voids > 0 ? [t("records.dayNav.parts.voids", { count: sum.voids })] : []),
    t("records.dayNav.parts.open", { count: sum.open }),
  ].join(" · ");
}
