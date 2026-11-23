/**
 * «Hoy · Mañana · Pasado mañana» (plan de correcciones UX, AP-C01; audit C1): the day of Cuotas, with the matches each has.
 * The server cuts the day on the Bogota calendar, so each tab shows a different list; before, the buttons only changed how many
 * hours were asked and the first twenty rows were the same in the three. Shared by «Por mercado» and «Por partido».
 */
import { Segmented } from "@/components/ui/segmented";
import { t } from "@/lib/i18n";
import type { DayKey, OddsDay } from "./model";
import { DAY_KEYS } from "./state";

export function isDayKey(value: unknown): value is DayKey {
  return value === "today" || value === "tomorrow" || value === "day_after";
}

export function dayLabel(day: DayKey): string {
  return day === "today"
    ? t("explorer.filters.today")
    : day === "tomorrow"
      ? t("explorer.filters.tomorrow")
      : t("explorer.filters.dayAfter");
}

/** The first day after `from` that has prices, for «Ver mañana (12)» where today has none; null when none has. */
export function nextDayWithPrices(
  from: DayKey | number,
  days: readonly OddsDay[] | undefined,
): OddsDay | null {
  if (!days) return null;
  const at = typeof from === "number" ? -1 : DAY_KEYS.indexOf(from);
  return days.find((d) => DAY_KEYS.indexOf(d.key) > at && d.fixtures > 0) ?? null;
}

export function DayTabs({
  value,
  days,
  onChange,
  testId = "odds-day",
}: {
  /** The day chosen; none (an old link's 48 or 72 hours) leaves every tab off. */
  value: DayKey | null;
  /** The matches of each day; none while they load: the names alone. */
  days: readonly OddsDay[] | undefined;
  onChange: (day: DayKey) => void;
  testId?: string;
}) {
  const count = (day: DayKey) => days?.find((d) => d.key === day)?.fixtures;
  return (
    <Segmented<DayKey | "">
      label={t("explorer.filters.window")}
      value={value ?? ""}
      testId={testId}
      onChange={(next) => {
        if (next !== "") onChange(next);
      }}
      options={DAY_KEYS.map((day) => {
        const n = count(day);
        return {
          value: day,
          label: (
            <>
              {dayLabel(day)}
              {n === undefined ? null : (
                <span aria-hidden className="numeric text-caption font-medium opacity-80">
                  {n}
                </span>
              )}
            </>
          ),
          // read as «Hoy, 12 partidos»: the number alone would be a number without a noun
          ...(n === undefined ? {} : { name: t("explorer.filters.dayCount", { count: n }) }),
        };
      })}
    />
  );
}
