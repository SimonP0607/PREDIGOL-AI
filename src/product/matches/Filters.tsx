/**
 * The controls of the Matches page: the reader's day (Hoy, Mañana, arrows, a date
 * picker), the state chips, a competition picker and a small text search.
 */
import {
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Search,
  Trophy,
  X,
} from "lucide-react";
import { useRef, type ReactNode } from "react";
import { intlTag, t } from "@/lib/i18n";
import { useScrollCue } from "@/lib/scrollCue";
import { formatDate, getTimeZone, shiftDay, zonedInstant } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { CompetitionOption, StatusFilter } from "./model";

const DAY = /^\d{4}-\d{2}-\d{2}$/;

const SHORT_DATES = new Map<string, Intl.DateTimeFormat>();

/** "3 oct" / "3 Oct": the narrow chip on a phone (the subtitle carries the weekday). */
function shortDate(day: string): string {
  const tag = intlTag();
  const zone = getTimeZone();
  const key = `${tag}|${zone}`;
  let f = SHORT_DATES.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(tag, { timeZone: zone, day: "numeric", month: "short" });
    SHORT_DATES.set(key, f);
  }
  return f.format(new Date(zonedInstant(day, 12)));
}

function chipClass(active: boolean): string {
  return cn(
    "tap-y relative inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-full border px-3 text-[0.8125rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
    active
      ? "border-primary/45 bg-primary/12 text-primary"
      : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
  );
}

function ArrowButton({
  direction,
  label,
  onClick,
}: {
  direction: "prev" | "next";
  label: string;
  onClick: () => void;
}) {
  const Icon = direction === "prev" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="tap relative inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <Icon aria-hidden className="h-4 w-4" />
    </button>
  );
}

/** A chip showing the chosen date; the native picker (calendar or wheel) opens on tap. */
function DatePicker({
  day,
  active,
  onChange,
}: {
  day: string;
  active: boolean;
  onChange: (day: string) => void;
}) {
  return (
    <label
      className={cn(
        chipClass(active),
        "min-w-0 cursor-pointer focus-within:ring-1 focus-within:ring-ring sm:flex-none pointer-coarse:min-w-11",
      )}
    >
      <CalendarDays aria-hidden className="h-3.5 w-3.5 shrink-0" />
      {active ? (
        <>
          <span aria-hidden className="truncate sm:hidden">
            {shortDate(day)}
          </span>
          <span aria-hidden className="hidden truncate first-letter:uppercase sm:block">
            {formatDate(zonedInstant(day, 12))}
          </span>
        </>
      ) : (
        // On a phone the calendar alone (the picker keeps its label): Hoy, Mañana and the date after fit beside it.
        <span aria-hidden className="hidden truncate sm:inline">
          {t("matches.day.other")}
        </span>
      )}
      <input
        type="date"
        required
        value={day}
        aria-label={t("matches.day.pick")}
        onChange={(e) => {
          if (DAY.test(e.target.value)) onChange(e.target.value);
        }}
        onClick={(e) => {
          try {
            e.currentTarget.showPicker();
          } catch {
            /* the browser opens its own picker */
          }
        }}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </label>
  );
}

export function DayNav({
  day,
  today,
  onChange,
}: {
  day: string;
  today: string;
  onChange: (day: string) => void;
}) {
  const tomorrow = shiftDay(today, 1);
  // REVIEW point 3: Hoy, Mañana, then the day after as its date ("lun, 12 oct") - never today's date again.
  const after = shiftDay(today, 2);
  const quick = day === today || day === tomorrow || day === after;
  const strip = useRef<HTMLDivElement>(null);
  useScrollCue(strip);
  return (
    <div
      role="group"
      aria-label={t("matches.day.label")}
      className="flex min-w-0 items-center gap-1.5"
      data-testid="day-nav"
    >
      <ArrowButton
        direction="prev"
        label={t("matches.day.prev")}
        onClick={() => onChange(shiftDay(day, -1))}
      />
      {/* The chips scroll inside the row on a narrow phone, between the two arrows; the page never does. Its
          edge fades where a chip waits beyond it; py-1 leaves room for the chips' 44 px reach on a touch screen. */}
      <div
        ref={strip}
        className="scroll-strip -my-1 flex min-w-0 flex-1 items-center gap-1.5 py-1 sm:flex-none"
      >
        <button
          type="button"
          aria-pressed={day === today}
          onClick={() => onChange(today)}
          className={chipClass(day === today)}
        >
          {t("common.day.today")}
        </button>
        <button
          type="button"
          aria-pressed={day === tomorrow}
          onClick={() => onChange(tomorrow)}
          className={chipClass(day === tomorrow)}
        >
          {t("common.day.tomorrow")}
        </button>
        <button
          type="button"
          aria-pressed={day === after}
          onClick={() => onChange(after)}
          className={cn(chipClass(day === after), "first-letter:uppercase")}
          data-testid="day-after-tomorrow"
        >
          {formatDate(zonedInstant(after, 12))}
        </button>
        <DatePicker day={day} active={!quick} onChange={onChange} />
      </div>
      <ArrowButton
        direction="next"
        label={t("matches.day.next")}
        onClick={() => onChange(shiftDay(day, 1))}
      />
    </div>
  );
}

function statusLabel(filter: StatusFilter): string {
  switch (filter) {
    case "all":
      return t("matches.status.all");
    case "live":
      return t("matches.status.live");
    case "upcoming":
      return t("matches.status.upcoming");
    case "finished":
      return t("matches.status.finished");
  }
}

export function StatusChips({
  value,
  counts,
  onChange,
}: {
  value: StatusFilter;
  /** Null while the day is loading (or failed): no count beats a wrong 0. */
  counts: Record<StatusFilter, number> | null;
  onChange: (value: StatusFilter) => void;
}) {
  const filters: StatusFilter[] = ["all", "live", "upcoming", "finished"];
  const strip = useRef<HTMLDivElement>(null);
  useScrollCue(strip);
  return (
    <div
      ref={strip}
      role="group"
      aria-label={t("matches.status.label")}
      className="scroll-strip -mx-4 -my-1 flex gap-2 px-4 py-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0"
      data-testid="status-chips"
    >
      {filters.map((f) => (
        <button
          key={f}
          type="button"
          aria-pressed={value === f}
          onClick={() => onChange(f)}
          className={chipClass(value === f)}
        >
          {f === "live" && counts && counts.live > 0 ? (
            <span aria-hidden className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
            </span>
          ) : null}
          {statusLabel(f)}
          {counts ? (
            <span
              className={cn(
                "numeric rounded-full px-1.5 text-[0.6875rem] tabular-nums",
                value === f ? "bg-primary/15" : "bg-elevated text-subtle-foreground",
              )}
            >
              {counts[f]}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

/* 16 px text on phones: iOS zooms into any smaller form field it focuses. */
const fieldClass =
  "h-10 w-full rounded-lg border border-border bg-card text-base text-foreground transition-colors placeholder:text-subtle-foreground hover:border-border-strong focus:border-border-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:h-9 sm:text-[0.8125rem] pointer-coarse:h-11";

/**
 * The native list (a wheel on phones) to pick from, under a label that stays readable
 * when narrow: "Competición" when none is picked, else the competition's name.
 */
export function CompetitionPicker({
  value,
  options,
  onChange,
  className,
}: {
  value: number | null;
  options: readonly CompetitionOption[];
  onChange: (value: number | null) => void;
  className?: string | undefined;
}) {
  const selected = options.find((o) => o.id === value) ?? null;
  return (
    <div
      className={cn(
        className,
        "relative flex h-10 min-w-0 flex-1 items-center gap-2 rounded-lg border bg-card pl-3 pr-8 text-sm transition-colors focus-within:ring-1 focus-within:ring-ring hover:border-border-strong sm:h-9 lg:w-64 lg:flex-none sm:text-[0.8125rem] pointer-coarse:h-11",
        selected ? "border-primary/45 text-foreground" : "border-border text-muted-foreground",
      )}
    >
      <Trophy aria-hidden className="h-3.5 w-3.5 shrink-0 text-subtle-foreground" />
      <span aria-hidden className="truncate">
        {selected ? selected.name : t("matches.filters.competitionAny")}
      </span>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
      />
      <select
        value={value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        aria-label={t("matches.filters.competition")}
        data-testid="competition-select"
        className="absolute inset-0 h-full w-full cursor-pointer appearance-none bg-card text-base text-foreground opacity-0"
      >
        <option value="">{t("matches.filters.allCompetitions")}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.country ? `${o.name} · ${o.country}` : o.name}
          </option>
        ))}
      </select>
    </div>
  );
}

export function SearchBox({
  value,
  onChange,
  placeholder,
  label,
  testId = "match-search",
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  /** Another page's words (Cuotas: a team or a competition). */
  placeholder?: string | undefined;
  label?: string | undefined;
  testId?: string | undefined;
  className?: string | undefined;
}) {
  return (
    <div className={cn("relative min-w-0 flex-1 lg:w-72 lg:flex-none", className)}>
      <Search
        aria-hidden
        className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
      />
      <input
        type="search"
        value={value}
        maxLength={80}
        enterKeyHint="search"
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? t("matches.filters.searchPlaceholder")}
        aria-label={label ?? t("matches.filters.search")}
        data-testid={testId}
        className={cn(
          fieldClass,
          "pl-8 [&::-webkit-search-cancel-button]:appearance-none",
          value ? "pr-9" : "pr-2",
        )}
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label={t("matches.filters.clearSearch")}
          className="tap absolute right-1 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-subtle-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          <X aria-hidden className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

/** A native list under a short label: the reader's country, or a category of competition (REVIEW point 3). */
export function FacetPicker<T extends string>({
  label,
  anyLabel,
  value,
  options,
  onChange,
  icon,
  testId,
}: {
  label: string;
  anyLabel: string;
  value: T | null;
  options: ReadonlyArray<{ key: T; label: string; count?: number }>;
  onChange: (value: T | null) => void;
  icon: ReactNode;
  testId: string;
}) {
  const selected = options.find((o) => o.key === value) ?? null;
  return (
    <div
      className={cn(
        "relative flex h-10 min-w-0 flex-1 items-center gap-2 rounded-lg border bg-card pl-3 pr-8 text-sm transition-colors focus-within:ring-1 focus-within:ring-ring hover:border-border-strong sm:h-9 lg:w-48 lg:flex-none sm:text-[0.8125rem] pointer-coarse:h-11",
        selected ? "border-primary/45 text-foreground" : "border-border text-muted-foreground",
      )}
    >
      <span aria-hidden className="shrink-0 text-subtle-foreground [&>svg]:h-3.5 [&>svg]:w-3.5">
        {icon}
      </span>
      <span aria-hidden className="truncate">
        {selected ? selected.label : label}
      </span>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
      />
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? (e.target.value as T) : null)}
        aria-label={label}
        data-testid={testId}
        className="absolute inset-0 h-full w-full cursor-pointer appearance-none bg-card text-base text-foreground opacity-0"
      >
        <option value="">{anyLabel}</option>
        {options.map((o) => (
          <option key={o.key} value={o.key}>
            {o.count !== undefined ? `${o.label} (${o.count})` : o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
