/**
 * Picks: the day's picks as PrediGol recorded them (up to five, frozen when chosen, kept
 * after kick-off with their results), then every qualified selection in the window,
 * re-priced at the best price available now - each one can be saved or added to a parlay.
 * A USER only ever sees qualified picks; when none qualifies the page says so plainly - it
 * never fills the list.
 *
 * REVIEW PREDIGOL: the day reads clearly, with its navigation (point 12); the list opens on
 * the next 24 hours and comes in pages of 15 (point 13); "Ya empezaron hoy" has its own
 * filters and pages (point 14); a price is chosen the Cuotas way (point 18).
 */
import { useMemo, useState, type ReactNode } from "react";
import { keepPreviousData, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { ChevronDown, Clock, History, ListFilter, RotateCcw } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { todayKey } from "@/lib/time";
import type { Envelope } from "@/lib/api/v1/types";
import type { CompetitionBadge, PicksBoard, StartedPick } from "@/lib/api/v1/types_product";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { fmtOdds } from "@/lib/i18n/format";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ShadowBadge } from "@/product/shared/Bits";
import { PickCard } from "@/product/shared/PickCard";
import { StartedPickCard } from "@/product/shared/StartedPickCard";
import {
  Card,
  EmptyState,
  ErrorState,
  PageTitle,
  SectionHeader,
  SkeletonBlock,
} from "@/product/shared/States";
import { MARKETS, emptyReason, marketShort } from "@/product/shared/markets";
import { DailySetBlock } from "@/product/records/DailySetBlock";
import { pickableOfCard, type Pickable } from "@/product/records/pickable";
import { SelectablePriceRow } from "@/product/odds/SelectablePrice";
import { Pager } from "@/product/shared/Pager";
import { usePaged } from "@/product/shared/paging";
import { startedState, type StartedState } from "./started";
import { ChipGroup, ShadowToggle, type ChipOption } from "./Controls";
import {
  DEFAULT_FILTERS,
  ODDS_RANGES,
  ODDS_RANGE_KEYS,
  WINDOWS,
  isDefault,
  toQuery,
  type OddsRange,
  type PickFilters,
} from "./filters";

const DAY_ZONE = "America/Bogota";

type BoardQuery = UseQueryResult<Envelope<PicksBoard>>;

export function PicksPage() {
  const auth = useAuth();
  const preview = usePreviewParam();
  const [filters, setFilters] = useState<PickFilters>(DEFAULT_FILTERS);
  const q = useMemo(() => toQuery(filters), [filters]);
  // The product day is Bogotá's; the previous days' sets stay one click away.
  const today = todayKey(DAY_ZONE);
  const [day, setDay] = useState(today);
  const daily = useQuery(live.daily(preview, day === today ? undefined : day));
  const list = useQuery({ ...live.productPicks(q, preview), placeholderData: keepPreviousData });

  return (
    <div className="space-y-8">
      <PageTitle
        title={t("nav.picks")}
        subtitle={t("picks.subtitle")}
        right={auth.showAdmin ? <ShadowToggle /> : undefined}
      />
      <DailySetBlock query={daily} nav={{ day, today, onDay: setDay }} />
      <AllPicks query={list} filters={filters} onChange={setFilters} />
      <StartedPicks />
    </div>
  );
}

const STATES: readonly StartedState[] = ["all", "live", "won", "lost", "other"];

/**
 * Today's pre-match picks whose match already kicked off: they do not disappear at kick-off.
 * Each stays as it was taken, with what the match is doing now and, at the end, its result.
 * Its own list, filters and pages (REVIEW point 14) - apart from the matches still to come.
 */
function StartedPicks() {
  const preview = usePreviewParam();
  const q = useQuery(live.startedPicks(preview));
  const all = useMemo(() => q.data?.data ?? [], [q.data]);
  const shadow = preview === "shadow";
  const [competition, setCompetition] = useState<number | null>(null);
  const [market, setMarket] = useState<string | null>(null);
  const [state, setState] = useState<StartedState>("all");
  const competitions = useMemo(() => {
    const seen = new Map<number, CompetitionBadge>();
    for (const p of all) seen.set(p.competition.id, p.competition);
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [all]);
  const markets = [...new Set(all.map((p) => p.market_key))];
  const shown = all.filter(
    (p: StartedPick) =>
      (competition === null || p.competition.id === competition) &&
      (market === null || p.market_key === market) &&
      (state === "all" || startedState(p) === state),
  );
  const paged = usePaged(shown, `${competition}|${market}|${state}|${all.length}`);
  if (q.isSuccess && all.length === 0) return null;
  const filtered = competition !== null || market !== null || state !== "all";
  return (
    <section className="space-y-3" data-testid="picks-started">
      <BlockHeader
        title={t("picks.started.title")}
        subtitle={t("picks.started.subtitle")}
        icon={<History aria-hidden className="h-4 w-4 text-gold" />}
        shadow={shadow}
      />
      {q.isPending ? (
        <CardsSkeleton count={3} tall />
      ) : q.isError ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      ) : (
        <>
          <div
            className="grid gap-x-6 gap-y-4 rounded-xl border border-border bg-card p-3 sm:p-4 md:grid-cols-3"
            data-testid="started-filters"
          >
            <div className="flex min-w-0 flex-col gap-2">
              <label htmlFor="started-competition" className="text-label text-subtle-foreground">
                {t("picks.filters.competition")}
              </label>
              <div className="relative">
                <select
                  id="started-competition"
                  value={competition === null ? "" : String(competition)}
                  onChange={(e) => setCompetition(e.target.value ? Number(e.target.value) : null)}
                  className="h-10 w-full appearance-none truncate rounded-lg border border-border bg-background pl-3 pr-9 text-sm text-foreground transition-colors hover:border-border-strong focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="">{t("picks.filters.allCompetitions")}</option>
                  {competitions.map((c) => (
                    <option key={c.id} value={String(c.id)}>
                      {competitionLabel(c)}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  aria-hidden
                  className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                />
              </div>
            </div>
            <Field label={t("picks.filters.market")}>
              <ChipGroup
                label={t("picks.filters.market")}
                value={market ?? "all"}
                options={[
                  { value: "all", label: t("common.all") },
                  ...MARKETS.filter((m) => markets.includes(m)).map((m) => ({
                    value: m,
                    label: marketShort(m),
                  })),
                ]}
                onChange={(m) => setMarket(m === "all" ? null : m)}
                testId="started-market"
              />
            </Field>
            <Field label={t("picks.started.state")}>
              <ChipGroup
                label={t("picks.started.state")}
                value={state}
                options={STATES.map((s) => ({ value: s, label: t(`picks.started.states.${s}`) }))}
                onChange={setState}
                testId="started-state"
              />
            </Field>
          </div>
          <p className="text-sm font-semibold" data-testid="started-count" aria-live="polite">
            {t("picks.started.count", { count: shown.length })}
          </p>
          {shown.length === 0 ? (
            <Card>
              <EmptyState
                compact
                icon={<History aria-hidden className="h-5 w-5" />}
                title={filtered ? t("picks.started.emptyFiltered") : t("picks.started.empty")}
              />
            </Card>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {paged.items.map((p) => (
                <StartedPickCard key={p.pick_id} pick={p} shadow={shadow} />
              ))}
            </div>
          )}
          <Pager paged={paged} />
        </>
      )}
    </section>
  );
}

function BlockHeader({
  title,
  subtitle,
  icon,
  shadow,
}: {
  title: string;
  subtitle?: string | undefined;
  icon: ReactNode;
  shadow: boolean;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <SectionHeader className="min-w-0" title={title} subtitle={subtitle} icon={icon} />
      {shadow ? <ShadowBadge className="mb-0.5" /> : null}
    </div>
  );
}

function CardsSkeleton({ count, tall = false }: { count: number; tall?: boolean }) {
  return (
    <div
      aria-busy="true"
      aria-label={t("common.loading")}
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
    >
      {Array.from({ length: count }, (_, i) => (
        <SkeletonBlock key={i} className={tall ? "h-64" : "h-44"} />
      ))}
    </div>
  );
}

function AllPicks({
  query,
  filters,
  onChange,
}: {
  query: BoardQuery;
  filters: PickFilters;
  onChange: (next: PickFilters) => void;
}) {
  const board = query.data?.data;
  const shadow = board?.source === "shadow_preview";
  const picks = board?.picks ?? [];
  // Pages of 15 (REVIEW point 13); back to the first whenever the filters change.
  const paged = usePaged(picks, JSON.stringify(toQuery(filters)));
  const refreshing = query.isPlaceholderData;
  const asOf = query.data?.meta.data_as_of ?? null;
  const filtered = !isDefault(filters);
  const loaded = !!board && !query.isError;
  // Nothing at all in the window and no filter set: a filter panel would only be noise.
  // The empty state offers the one choice that can still help - looking further ahead.
  const bare = loaded && !filtered && picks.length === 0;
  const widest = WINDOWS[WINDOWS.length - 1] ?? DEFAULT_FILTERS.hours;

  const reset = (
    <button
      type="button"
      onClick={() => onChange(DEFAULT_FILTERS)}
      data-testid="filters-reset"
      className="inline-flex h-9 items-center gap-1.5 rounded-full border border-border-strong px-3 text-xs font-medium text-foreground transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <RotateCcw aria-hidden className="h-3.5 w-3.5" />
      {t("picks.filters.reset")}
    </button>
  );

  let body: ReactNode;
  if (query.isPending) {
    body = <CardsSkeleton count={6} />;
  } else if (query.isError) {
    body = (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  } else if (picks.length === 0) {
    const widen =
      filters.hours < widest ? (
        <button
          type="button"
          onClick={() => onChange({ ...filters, hours: widest })}
          data-testid="picks-widen"
          className="inline-flex h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("picks.all.widen", { days: Math.round(widest / 24) })}
        </button>
      ) : undefined;
    body = (
      <Card>
        <EmptyState
          compact
          icon={<ListFilter aria-hidden className="h-5 w-5" />}
          title={emptyReason(board?.reason ?? "no_qualified_picks")}
          body={filtered ? undefined : t("picks.all.emptyBody")}
          action={filtered ? reset : widen}
        />
      </Card>
    );
  } else {
    body = (
      <>
        <div
          aria-busy={refreshing}
          data-testid="picks-list"
          className={cn(
            "grid grid-cols-1 gap-3 transition-opacity sm:grid-cols-2 xl:grid-cols-3",
            refreshing && "opacity-60",
          )}
        >
          {paged.items.map((pick) => (
            <PickCard
              key={pick.pick_id}
              pick={pick}
              compact
              shadow={shadow}
              actions={<SelectablePriceRow sel={pickableOfCard(pick)} />}
            />
          ))}
        </div>
        <Pager
          paged={paged}
          className="pt-1"
          onChange={() =>
            document.getElementById("picks-all")?.scrollIntoView({ behavior: "smooth" })
          }
        />
      </>
    );
  }

  return (
    <section className="scroll-mt-20 space-y-3" id="picks-all" data-testid="picks-all">
      <BlockHeader
        title={t("picks.all.title")}
        subtitle={bare ? undefined : t("picks.all.subtitle")}
        icon={<ListFilter aria-hidden className="h-4 w-4 text-primary" />}
        shadow={shadow}
      />
      {filtered || (loaded && !bare) ? (
        <PicksFilters
          filters={filters}
          onChange={onChange}
          competitions={board?.competitions ?? []}
        />
      ) : null}
      <div aria-live="polite">
        {loaded && picks.length > 0 ? (
          <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <p className="text-sm font-semibold" data-testid="picks-count">
              {t("picks.count", { count: picks.length })}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {asOf ? (
                <span className="inline-flex items-center gap-1 text-caption text-muted-foreground">
                  <Clock aria-hidden className="h-3 w-3" />
                  {t("picks.pricesUpdated", { when: formatRelative(asOf) })}
                </span>
              ) : null}
              {filtered ? reset : null}
            </div>
          </div>
        ) : null}
      </div>
      {body}
    </section>
  );
}

function oddsLabel(key: OddsRange): string {
  const range = ODDS_RANGES[key];
  if (range.min === undefined) return t("picks.filters.oddsAll");
  if (range.max === undefined) return t("picks.filters.oddsFrom", { min: fmtOdds(range.min) });
  return t("picks.filters.oddsRange", { min: fmtOdds(range.min), max: fmtOdds(range.max) });
}

function windowLabel(hours: number): string {
  return hours > 72
    ? t("picks.filters.days", { count: Math.round(hours / 24) })
    : t("picks.filters.hours", { count: hours });
}

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

function PicksFilters({
  filters,
  onChange,
  competitions,
}: {
  filters: PickFilters;
  onChange: (next: PickFilters) => void;
  competitions: CompetitionBadge[];
}) {
  const set = (patch: Partial<PickFilters>) => onChange({ ...filters, ...patch });
  const markets: ChipOption<string>[] = [
    { value: "all", label: t("common.all") },
    ...MARKETS.map((m) => ({ value: m, label: marketShort(m) })),
  ];
  const odds: ChipOption<OddsRange>[] = ODDS_RANGE_KEYS.map((k) => ({
    value: k,
    label: <span className="numeric">{oddsLabel(k)}</span>,
  }));
  const windows: ChipOption<number>[] = WINDOWS.map((h) => ({ value: h, label: windowLabel(h) }));

  return (
    <div className="rounded-xl border border-border bg-card p-3 sm:p-4" data-testid="picks-filters">
      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
        <CompetitionSelect
          value={filters.competition}
          competitions={competitions}
          onChange={(competition) => set({ competition })}
        />
        <Field label={t("picks.filters.window")}>
          <ChipGroup
            label={t("picks.filters.window")}
            value={filters.hours}
            options={windows}
            onChange={(hours) => set({ hours })}
            testId="filter-window"
          />
        </Field>
        <Field label={t("picks.filters.market")}>
          <ChipGroup
            label={t("picks.filters.market")}
            value={filters.market ?? "all"}
            options={markets}
            onChange={(m) => set({ market: m === "all" ? null : m })}
            testId="filter-market"
          />
        </Field>
        <Field label={t("picks.filters.odds")}>
          <ChipGroup
            label={t("picks.filters.odds")}
            value={filters.odds}
            options={odds}
            onChange={(range) => set({ odds: range })}
            testId="filter-odds"
          />
        </Field>
      </div>
    </div>
  );
}

/** "Serie B · Brazil": the country tells apart competitions that share a name. */
function competitionLabel(c: CompetitionBadge): string {
  return c.country && c.country !== "World" ? `${c.name} · ${c.country}` : c.name;
}

function CompetitionSelect({
  value,
  competitions,
  onChange,
}: {
  value: PickFilters["competition"];
  competitions: CompetitionBadge[];
  onChange: (next: PickFilters["competition"]) => void;
}) {
  const options = useMemo(() => {
    const list = competitions.map((c) => ({ id: c.id, name: competitionLabel(c) }));
    // A choice the current window no longer has stays listed, so the select never lies.
    if (value && !list.some((c) => c.id === value.id)) list.unshift(value);
    return list;
  }, [competitions, value]);

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <label htmlFor="picks-competition" className="text-label text-subtle-foreground">
        {t("picks.filters.competition")}
      </label>
      <div className="relative">
        <select
          id="picks-competition"
          value={value ? String(value.id) : ""}
          onChange={(e) => {
            const id = Number(e.target.value);
            onChange(options.find((c) => c.id === id) ?? null);
          }}
          data-testid="filter-competition"
          className="h-10 w-full appearance-none truncate rounded-lg border border-border bg-background pl-3 pr-9 text-sm text-foreground transition-colors hover:border-border-strong focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="">{t("picks.filters.allCompetitions")}</option>
          {options.map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.name}
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
