/** The automatic parlay builder's controls (REVIEW point 15): markets, competitions, legs and odds. */
import { useMemo, useState, type ReactNode } from "react";
import { Check, ChevronDown, Search, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { BuilderOption } from "@/lib/api/v1/types_builder";
import type { MarketKey } from "@/lib/api/v1/types_records";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { MARKETS, marketName } from "@/product/shared/markets";
import { BUILDER_MAX_LEGS, BUILDER_MIN_LEGS, toggled } from "./builderForm";

const LEG_COUNTS = Array.from(
  { length: BUILDER_MAX_LEGS - BUILDER_MIN_LEGS + 1 },
  (_, i) => BUILDER_MIN_LEGS + i,
);
const FIELD =
  "h-10 rounded-lg border border-border bg-card px-3 text-base text-foreground transition-colors placeholder:text-subtle-foreground hover:border-border-strong focus:border-border-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:h-9 sm:text-[0.8125rem] pointer-coarse:h-11";
const LABEL = "text-label text-subtle-foreground";

export function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className={LABEL}>{label}</div>
      {children}
    </div>
  );
}

/** "Todos" plus one chip per market; none chosen means every market. */
export function MarketChips({
  value,
  onChange,
}: {
  value: MarketKey[];
  onChange: (value: MarketKey[]) => void;
}) {
  const chip = (on: boolean) =>
    cn(
      "tap-y relative inline-flex h-9 items-center gap-1 whitespace-nowrap rounded-full border px-3.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      on
        ? "border-primary/50 bg-primary/12 text-primary"
        : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
    );
  return (
    <div
      role="group"
      aria-label={t("parlays.builder.markets")}
      className="flex flex-wrap gap-1.5 pointer-coarse:gap-y-2"
      data-testid="builder-markets"
    >
      <button
        type="button"
        aria-pressed={value.length === 0}
        onClick={() => onChange([])}
        className={chip(value.length === 0)}
      >
        {t("parlays.builder.allMarkets")}
      </button>
      {MARKETS.map((m) => {
        const on = value.includes(m);
        return (
          <button
            key={m}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(toggled(value, m))}
            className={chip(on)}
          >
            {on ? <Check aria-hidden className="h-3 w-3" /> : null}
            {marketName(m)}
          </button>
        );
      })}
    </div>
  );
}

/** Several competitions, searched by name; only those with selections that pass the rules are offered. */
export function CompetitionsPicker({
  value,
  options,
  onChange,
}: {
  value: number[];
  options: BuilderOption[];
  onChange: (value: number[]) => void;
}) {
  const [term, setTerm] = useState("");
  const shown = useMemo(() => {
    const q = term.trim().toLocaleLowerCase();
    return q
      ? options.filter((o) =>
          `${o.competition.name} ${o.competition.country ?? ""}`.toLocaleLowerCase().includes(q),
        )
      : options;
  }, [options, term]);
  const label =
    value.length === 0
      ? t("parlays.builder.allCompetitions")
      : value.length === 1
        ? (options.find((o) => o.competition.id === value[0])?.competition.name ??
          t("parlays.builder.someCompetitions", { count: 1 }))
        : t("parlays.builder.someCompetitions", { count: value.length });
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="builder-competitions"
          className={cn(
            FIELD,
            "flex w-full items-center gap-2 text-left sm:w-72",
            value.length ? "border-primary/45" : "text-muted-foreground",
          )}
        >
          <Trophy aria-hidden className="h-3.5 w-3.5 shrink-0 text-subtle-foreground" />
          <span className="min-w-0 flex-1 truncate">{label}</span>
          <ChevronDown aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-0">
        <div className="border-b border-border p-2">
          <div className="relative">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
            />
            <input
              type="search"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder={t("parlays.builder.searchCompetition")}
              aria-label={t("parlays.builder.searchCompetition")}
              className={cn(FIELD, "w-full pl-8")}
            />
          </div>
        </div>
        {options.length === 0 ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">
            {t("parlays.builder.noCompetitions")}
          </p>
        ) : (
          <ul
            className="max-h-72 overflow-y-auto py-1"
            aria-label={t("parlays.builder.competitions")}
          >
            {shown.map((o) => {
              const on = value.includes(o.competition.id);
              return (
                <li key={o.competition.id}>
                  <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm hover:bg-elevated/60">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => onChange(toggled(value, o.competition.id))}
                      className="h-4 w-4 accent-primary"
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {o.competition.name}
                      {o.competition.country ? (
                        <span className="text-muted-foreground"> · {o.competition.country}</span>
                      ) : null}
                    </span>
                    <span className="numeric shrink-0 text-caption text-subtle-foreground">
                      {o.selections}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
        {value.length ? (
          <div className="border-t border-border p-2 text-right">
            <button
              type="button"
              onClick={() => onChange([])}
              className="text-xs font-medium text-primary hover:underline"
            >
              {t("parlays.builder.clearCompetitions")}
            </button>
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

export function LegsSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className={cn(FIELD, "w-[4.5rem] cursor-pointer")}
    >
      {LEG_COUNTS.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
    </select>
  );
}

export function OddsInput({
  label,
  value,
  onChange,
  invalid,
  placeholder,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  invalid: boolean;
  placeholder: string;
  testId: string;
}) {
  return (
    <input
      type="text"
      inputMode="decimal"
      autoComplete="off"
      aria-label={label}
      aria-invalid={invalid || undefined}
      value={value}
      maxLength={8}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testId}
      className={cn(FIELD, "w-24", invalid && "border-negative/60")}
    />
  );
}
