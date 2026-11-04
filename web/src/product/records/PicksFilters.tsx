/**
 * The filter of «Picks guardados» (plan UX, B5, section 30): a search always in view, and - in a row of their own at a desk,
 * in the «Filtros» sheet from the bottom on a phone and a tablet (A15) - the result, the kind of bet, the league, the odds
 * range, who chose it and the days of the match. The choices of kind of bet and league are the reader's own (the
 * server's `options`): nothing another reader holds. A change applies at once.
 */
import { useId, type ReactNode } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { CompetitionBadge } from "@/lib/api/v1/types_product";
import {
  ODDS_BANDS,
  type OddsBand,
  type PickOrigin,
  type PickResult,
} from "@/lib/api/v1/types_mypicks";
import { ChipGroup, type ChipOption } from "@/product/picks/Controls";
import { FilterSheet } from "@/product/shared/FilterSheet";
import { marketName } from "@/product/shared/markets";
import {
  ORIGINS,
  RESULTS,
  activeCount,
  dayOrNull,
  NO_FILTER,
  type PicksFilterState,
} from "./myPicksFilter";
import { bandLabel } from "./picksText";

const ALL = "all";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <span aria-hidden className="text-label text-subtle-foreground">
        {label}
      </span>
      {children}
    </div>
  );
}

function SelectField({
  label,
  value,
  allLabel,
  options,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  allLabel: string;
  options: ReadonlyArray<{ value: string; label: string }>;
  onChange: (value: string) => void;
  testId: string;
}) {
  // its own id in each copy (the desk's row and the phone's sheet): a label always names the field beside it
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor={id} className="text-label text-subtle-foreground">
        {label}
      </label>
      <div className="relative">
        <select
          id={id}
          value={value}
          data-testid={testId}
          onChange={(e) => onChange(e.target.value)}
          className="h-10 w-full appearance-none truncate rounded-lg border border-border bg-background pl-3 pr-9 text-base text-foreground transition-colors hover:border-border-strong focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm pointer-coarse:h-11"
        >
          <option value={ALL}>{allLabel}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
      </div>
    </div>
  );
}

function DayField({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: string | null;
  onChange: (day: string | null) => void;
  testId: string;
}) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor={id} className="text-label text-subtle-foreground">
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value ?? ""}
        data-testid={testId}
        onChange={(e) => onChange(dayOrNull(e.target.value))}
        className="numeric h-10 w-full rounded-lg border border-border bg-background px-3 text-base text-foreground transition-colors hover:border-border-strong focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm pointer-coarse:h-11"
      />
    </div>
  );
}

function competitionName(c: CompetitionBadge): string {
  return c.country ? `${c.name} · ${c.country}` : c.name;
}

function FilterFields({
  value,
  onChange,
  markets,
  competitions,
}: {
  value: PicksFilterState;
  onChange: (next: PicksFilterState) => void;
  markets: readonly string[];
  competitions: readonly CompetitionBadge[];
}) {
  const set = (patch: Partial<PicksFilterState>) => onChange({ ...value, ...patch });
  const results: ChipOption<string>[] = [
    { value: ALL, label: t("common.all") },
    ...RESULTS.map((r) => ({ value: r, label: t(`records.mine.filters.result.${r}`) })),
  ];
  const origins: ChipOption<string>[] = [
    { value: ALL, label: t("common.all") },
    ...ORIGINS.map((o) => ({ value: o, label: t(`records.mine.filters.origin.${o}`) })),
  ];
  const bands: ChipOption<string>[] = [
    { value: ALL, label: t("common.all") },
    ...ODDS_BANDS.map((b) => ({
      value: b,
      label: <span className="numeric">{bandLabel(b)}</span>,
    })),
  ];
  return (
    <>
      <Field label={t("records.mine.filters.resultLabel")}>
        <ChipGroup
          label={t("records.mine.filters.resultLabel")}
          value={value.result ?? ALL}
          options={results}
          onChange={(r) => set({ result: r === ALL ? null : (r as PickResult) })}
          testId="mypicks-filter-result"
        />
      </Field>
      <SelectField
        label={t("records.mine.filters.marketLabel")}
        value={value.market ?? ALL}
        allLabel={t("records.mine.filters.allMarkets")}
        options={markets.map((m) => ({ value: m, label: marketName(m) }))}
        onChange={(m) => set({ market: m === ALL ? null : m })}
        testId="mypicks-filter-market"
      />
      <SelectField
        label={t("records.mine.filters.competitionLabel")}
        value={value.competition === null ? ALL : String(value.competition)}
        allLabel={t("records.mine.filters.allCompetitions")}
        options={competitions.map((c) => ({ value: String(c.id), label: competitionName(c) }))}
        onChange={(c) => set({ competition: c === ALL ? null : Number(c) })}
        testId="mypicks-filter-competition"
      />
      <Field label={t("records.mine.filters.bandLabel")}>
        <ChipGroup
          label={t("records.mine.filters.bandLabel")}
          value={value.band ?? ALL}
          options={bands}
          onChange={(b) => set({ band: b === ALL ? null : (b as OddsBand) })}
          testId="mypicks-filter-band"
        />
      </Field>
      <Field label={t("records.mine.filters.originLabel")}>
        <ChipGroup
          label={t("records.mine.filters.originLabel")}
          value={value.origin ?? ALL}
          options={origins}
          onChange={(o) => set({ origin: o === ALL ? null : (o as PickOrigin) })}
          testId="mypicks-filter-origin"
        />
      </Field>
      <div className="grid min-w-0 grid-cols-2 gap-3">
        <DayField
          label={t("records.mine.filters.since")}
          value={value.since}
          onChange={(since) => set({ since })}
          testId="mypicks-filter-since"
        />
        <DayField
          label={t("records.mine.filters.until")}
          value={value.until}
          onChange={(until) => set({ until })}
          testId="mypicks-filter-until"
        />
      </div>
    </>
  );
}

/** The search of the teams and the league: always in view, above the list. */
export function PicksSearch({ value, onChange }: { value: string; onChange: (q: string) => void }) {
  const id = useId();
  return (
    <div className="relative min-w-0 flex-1">
      <label htmlFor={id} className="sr-only">
        {t("records.mine.filters.search")}
      </label>
      <Search
        aria-hidden
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
      />
      <input
        id={id}
        type="search"
        value={value}
        maxLength={60}
        placeholder={t("records.mine.filters.search")}
        onChange={(e) => onChange(e.target.value)}
        data-testid="mypicks-search"
        className="h-10 w-full rounded-full border border-border bg-background pl-9 pr-9 text-base text-foreground transition-colors hover:border-border-strong focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm pointer-coarse:h-11"
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label={t("records.mine.filters.clearSearch")}
          className="tap-y absolute right-1.5 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full text-muted-foreground hover:bg-elevated hover:text-foreground"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}

export function PicksFilters({
  value,
  onChange,
  markets,
  competitions,
  showLabel,
  className,
}: {
  value: PicksFilterState;
  onChange: (next: PicksFilterState) => void;
  markets: readonly string[];
  competitions: readonly CompetitionBadge[];
  /** «Ver N picks»: the sheet's main action; the list is already filtered. */
  showLabel?: string | undefined;
  className?: string | undefined;
}) {
  const fields = { value, onChange, markets, competitions };
  const reset = () => onChange({ ...NO_FILTER, q: value.q });
  const active = activeCount({ ...value, q: "" });
  return (
    <div className={cn("space-y-3", className)} data-testid="mypicks-filters">
      {/* At a desk the fields are the section's own panel (plan UX, section 37). */}
      <div
        className="hidden grid-cols-2 gap-4 rounded-xl border border-border bg-card p-4 lg:grid xl:grid-cols-3"
        data-testid="mypicks-filters-panel"
      >
        <FilterFields {...fields} />
        {active > 0 ? (
          <div className="flex items-end">
            <button
              type="button"
              onClick={reset}
              data-testid="mypicks-filters-reset"
              className="tap-y relative h-9 rounded-full border border-border-strong px-4 text-xs font-semibold text-muted-foreground hover:bg-elevated hover:text-foreground"
            >
              {t("common.filters.reset")}
            </button>
          </div>
        ) : null}
      </div>
      {/* Below 1024 px the same fields in the «Filtros» sheet (plan UX, A15). */}
      <div className="flex lg:hidden">
        <FilterSheet
          testId="mypicks-filters-sheet"
          title={t("records.mine.filters.title")}
          active={active}
          onReset={reset}
          showLabel={showLabel}
        >
          <FilterFields {...fields} />
        </FilterSheet>
      </div>
    </div>
  );
}
