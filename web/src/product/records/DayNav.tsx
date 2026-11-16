/**
 * The day of the picks, clear at a glance (REVIEW PREDIGOL, point 12): which day it is - Hoy, Ayer or its
 * date - with the arrows to the day before and after, the last seven days one tap away, and what the day's
 * set came to once its matches are played.
 */
import { useRef } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useScrollCue } from "@/lib/scrollCue";
import { t } from "@/lib/i18n";
import { fmtSignedPct, localFixed } from "@/lib/i18n/format";
import {
  currentLocaleTag,
  formatDateLong,
  getTimeZone,
  offsetMinutes,
  shiftDay,
  zoneName,
} from "@/lib/time";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { daySummary, recentDays, summaryText } from "./days";

const ZONE = "America/Bogota";

function at(day: string): string {
  return `${day}T12:00:00Z`;
}

/**
 * «5 picks · 2 ganados · 2 perdidos · 1 nulo · 0 por jugar (1 a medias)»: every pick counts once, so the parts add up to
 * the total (plan PICKS, D3); voids and half results are said only when there are some.
 */

/** «vie», «Sat»: the weekday of a picks' day, in Bogotá. */
function weekday(day: string): string {
  return new Intl.DateTimeFormat(currentLocaleTag(), { weekday: "short", timeZone: ZONE })
    .format(new Date(at(day)))
    .replace(".", "");
}

function word(day: string, today: string): string | null {
  if (day === today) return t("records.dayNav.today");
  if (day === shiftDay(today, -1)) return t("records.dayNav.yesterday");
  return null;
}

export function DayNav({
  day,
  today,
  onDay,
  items,
}: {
  day: string;
  today: string;
  onDay: (day: string) => void;
  items: readonly DailyItem[];
}) {
  const relative = word(day, today);
  const sum = daySummary(items);
  const strip = useRef<HTMLUListElement>(null);
  useScrollCue(strip);
  const arrow =
    "tap relative inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-border-strong transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-30";
  // The last seven days as tiles, oldest first and today at the end (sheets K01 and K08): the word or the weekday over the
  // day's number. The whole date stays on each tile's name and under the row, never cut.
  const days = recentDays(today).slice().reverse();
  return (
    <nav aria-label={t("records.dayNav.label")} className="space-y-2" data-testid="daily-nav">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          className={arrow}
          aria-label={t("records.dayNav.previous")}
          onClick={() => onDay(shiftDay(day, -1))}
          data-testid="daily-prev"
        >
          <ChevronLeft aria-hidden className="h-5 w-5" />
        </button>
        <ul
          ref={strip}
          aria-label={t("records.dayNav.jump")}
          className="scroll-strip flex min-w-0 flex-1 gap-1.5 px-0.5 py-1"
        >
          {days.map((d) => {
            const selected = d === day;
            return (
              <li key={d} className="min-w-[3.75rem] flex-1">
                <button
                  type="button"
                  aria-pressed={selected}
                  aria-label={formatDateLong(at(d), ZONE)}
                  onClick={() => onDay(d)}
                  data-testid="daily-day"
                  className={cn(
                    "tap-y relative flex w-full flex-col items-center rounded-card border px-2 py-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected
                      ? "border-primary/60 bg-primary/12 text-primary"
                      : "border-border bg-card text-foreground hover:border-border-strong",
                  )}
                >
                  <span
                    className={cn(
                      "text-micro font-semibold first-letter:uppercase",
                      selected ? "text-primary" : "text-muted-foreground",
                    )}
                  >
                    {word(d, today) ?? weekday(d)}
                  </span>
                  <span className="numeric font-display text-lg font-bold leading-tight">
                    {Number(d.slice(8, 10))}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <button
          type="button"
          className={arrow}
          aria-label={t("records.dayNav.next")}
          onClick={() => onDay(shiftDay(day, 1))}
          disabled={day >= today}
          data-testid="daily-next"
        >
          <ChevronRight aria-hidden className="h-5 w-5" />
        </button>
      </div>
      <p className="text-center text-caption text-muted-foreground" aria-live="polite">
        <span className="font-semibold text-foreground first-letter:uppercase">
          {relative ? `${relative} · ` : ""}
          {formatDateLong(at(day), ZONE)}
        </span>
        {/* The picks' day is Bogotá's (plan UX, A1, F09): said so to a reader whose clock is not on its time. */}
        {offsetMinutes(Date.now(), getTimeZone()) !== offsetMinutes(Date.now(), ZONE) ? (
          <span className="block" data-testid="daily-zone">
            {t("records.dayNav.zone", { zone: zoneName(ZONE) })}
          </span>
        ) : null}
      </p>
      {sum.count > 0 ? (
        <p
          className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs tabular-nums text-muted-foreground"
          data-testid="daily-summary"
        >
          <span>{summaryText(sum)}</span>
          {sum.units !== null ? (
            <span
              className={cn(
                "rounded-md px-1.5 py-0.5 font-semibold",
                sum.units > 0
                  ? "bg-positive-soft text-positive"
                  : sum.units < 0
                    ? "bg-negative-soft text-negative"
                    : "bg-elevated text-foreground",
              )}
            >
              {t("records.dayNav.units", {
                units: `${sum.units > 0 ? "+" : ""}${localFixed(sum.units, 2)}`,
              })}
            </span>
          ) : null}
        </p>
      ) : null}
    </nav>
  );
}
