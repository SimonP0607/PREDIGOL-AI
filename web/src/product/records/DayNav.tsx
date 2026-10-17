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
import { formatDate, formatDateLong, shiftDay } from "@/lib/time";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { daySummary, recentDays } from "./days";

const ZONE = "America/Bogota";

function at(day: string): string {
  return `${day}T12:00:00Z`;
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
  return (
    <nav
      aria-label={t("records.dayNav.label")}
      className="rounded-xl border border-border bg-card p-3 sm:p-4"
      data-testid="daily-nav"
    >
      <div className="flex items-center gap-3">
        <button
          type="button"
          className={arrow}
          aria-label={t("records.dayNav.previous")}
          onClick={() => onDay(shiftDay(day, -1))}
          data-testid="daily-prev"
        >
          <ChevronLeft aria-hidden className="h-5 w-5" />
        </button>
        <div className="min-w-0 flex-1 text-center" aria-live="polite">
          <p className="text-label text-primary">{relative ?? formatDate(at(day), ZONE)}</p>
          {/* The whole date, on two lines on a narrow phone - never "Domingo, 11 de o…". */}
          <p className="break-words font-display text-lg font-semibold leading-tight first-letter:uppercase sm:text-xl">
            {formatDateLong(at(day), ZONE)}
          </p>
        </div>
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
      <ul
        ref={strip}
        aria-label={t("records.dayNav.jump")}
        className="scroll-strip -mx-1 mt-2 flex gap-1.5 px-1 py-1"
      >
        {recentDays(today).map((d) => {
          const selected = d === day;
          return (
            <li key={d} className="shrink-0">
              <button
                type="button"
                aria-pressed={selected}
                onClick={() => onDay(d)}
                className={cn(
                  "tap-y relative min-h-9 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selected
                    ? "border-primary/60 bg-primary/12 text-primary"
                    : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
                )}
              >
                {word(d, today) ?? formatDate(at(d), ZONE)}
              </button>
            </li>
          );
        })}
      </ul>
      {sum.count > 0 ? (
        <p
          className="mt-3 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs tabular-nums text-muted-foreground"
          data-testid="daily-summary"
        >
          <span>
            {t("records.dayNav.summary", {
              count: sum.count,
              won: sum.won,
              lost: sum.lost,
              open: sum.open,
            })}
          </span>
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
