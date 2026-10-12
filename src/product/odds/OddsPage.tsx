/**
 * Cuotas: the best price of every selection for the upcoming fixtures, next to its fair (de-vigged) price - and
 * nothing else (REVIEW PREDIGOL, point 17: the module exists for that comparison, whatever the picks; the picks
 * have their own page). It opens on the next 24 hours; the reader narrows it by a team or a competition's name, a
 * country, a competition, only the prices above fair, and orders it by kick-off or by the widest margin over fair.
 */
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, Clock, Globe2, Scale, SearchX, Trophy } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import { t, useI18n } from "@/lib/i18n";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, EmptyState, ErrorState, PageTitle, SkeletonBlock } from "@/product/shared/States";
import { MARKETS, marketShort, type MarketKey } from "@/product/shared/markets";
import { Pager } from "@/product/shared/Pager";
import { usePaged } from "@/product/shared/paging";
import { ChipGroup, ShadowToggle, type ChipOption } from "@/product/picks/Controls";
import { FacetPicker, SearchBox } from "@/product/matches/Filters";
import { Highlights } from "./Highlights";
import { OddsBoard } from "./OddsBoard";
import {
  NO_ODDS_FILTERS,
  competitionOptions,
  countryOptions,
  inOddsFilters,
  sortFixtures,
  type OddsFilters,
  type OddsSort,
} from "./filters";

/** REVIEW point 17: the board opens on the next 24 h. */
const DEFAULT_HOURS = 24;
const WIDEST = 72;
const WINDOWS: readonly number[] = [24, 48, WIDEST];

function tabLabel(market: MarketKey): string {
  switch (market) {
    case "1X2":
      return t("odds.tabs.1X2");
    case "OU":
      return t("odds.tabs.OU");
    case "BTTS":
      return t("odds.tabs.BTTS");
    case "AH":
      return t("odds.tabs.AH");
    case "DC":
      return t("odds.tabs.DC");
  }
}

function FairExplainer() {
  return (
    <>
      {/* A phone: one line that opens the explanation - seven lines of it pushed the prices off the first screen. */}
      <details
        className="group rounded-xl border border-border bg-card text-xs text-muted-foreground md:hidden"
        data-testid="odds-fair-explainer-toggle"
      >
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-4 py-2 font-medium text-foreground [&::-webkit-details-marker]:hidden">
          <Scale aria-hidden className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 flex-1">{t("odds.fairExplainerToggle")}</span>
          <ChevronDown
            aria-hidden
            className="h-4 w-4 shrink-0 text-subtle-foreground transition-transform group-open:rotate-180"
          />
        </summary>
        <p className="px-4 pb-3 pl-10">{t("odds.fairExplainer")}</p>
      </details>
      <p
        className="hidden items-start gap-2 rounded-xl border border-border bg-card px-4 py-3 text-xs text-muted-foreground md:flex"
        data-testid="odds-fair-explainer"
      >
        <Scale aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <span>{t("odds.fairExplainer")}</span>
      </p>
    </>
  );
}

export function OddsPage() {
  const auth = useAuth();
  const preview = usePreviewParam();
  const { locale } = useI18n();
  const [market, setMarket] = useState<MarketKey>("1X2");
  const [hours, setHours] = useState<number>(DEFAULT_HOURS);
  const [filters, setFilters] = useState<OddsFilters>(NO_ODDS_FILTERS);
  const query = useQuery({
    ...live.bestOdds({ market, hours, picks: false }, preview),
    placeholderData: keepPreviousData,
  });
  const board = query.data?.data;
  // While another tab loads, the previous board stays on screen (dimmed), drawn with the
  // market it was fetched for: a board asked for one market lists exactly that one.
  const shownMarket = board?.markets.length === 1 && board.markets[0] ? board.markets[0] : market;
  const refreshing = query.isPlaceholderData;
  const asOf = query.data?.meta.data_as_of ?? null;
  const update = (patch: Partial<OddsFilters>) => setFilters((f) => ({ ...f, ...patch }));

  const fixtures = useMemo(() => board?.fixtures ?? [], [board]);
  const countries = useMemo(
    () => countryOptions(fixtures, shownMarket, locale, t("odds.filters.international")),
    [fixtures, shownMarket, locale],
  );
  // A country or competition picked in another window or market may not be on this board: then all of them.
  const country =
    filters.country !== null && countries.some((c) => c.key === filters.country)
      ? filters.country
      : null;
  const competitions = useMemo(
    () => competitionOptions(fixtures, shownMarket, country, locale),
    [fixtures, shownMarket, country, locale],
  );
  const competition =
    filters.competition !== null && competitions.some((c) => c.key === filters.competition)
      ? filters.competition
      : null;
  const effective = useMemo<OddsFilters>(
    () => ({ ...filters, country, competition }),
    [filters, country, competition],
  );
  const kept = useMemo(
    () =>
      sortFixtures(
        fixtures.filter((f) => inOddsFilters(f, shownMarket, effective)),
        shownMarket,
        effective.sort,
      ),
    [fixtures, shownMarket, effective],
  );
  const keptIds = useMemo(() => new Set(kept.map((f) => f.fixture_id)), [kept]);
  const paged = usePaged(kept, `${shownMarket}|${hours}|${JSON.stringify(effective)}`);
  const filtered =
    effective.query.trim() !== "" ||
    country !== null ||
    competition !== null ||
    effective.aboveFair;

  const windows: ChipOption<number>[] = WINDOWS.map((h) => ({
    value: h,
    label: t("odds.window.hours", { count: h }),
  }));
  const sorts: ChipOption<OddsSort>[] = [
    { value: "time", label: t("odds.filters.sortTime") },
    { value: "edge", label: t("odds.filters.sortEdge") },
  ];

  let content;
  if (query.isPending) {
    content = <OddsSkeleton />;
  } else if (query.isError) {
    content = (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  } else if (board) {
    const nothing = board.fixtures.length === 0 && board.highlights.length === 0;
    const highlights = filtered
      ? board.highlights.filter((h) => keptIds.has(h.fixture_id))
      : board.highlights;
    content = (
      <>
        {nothing ? null : <Highlights items={highlights} />}
        {filtered && kept.length === 0 && !nothing ? (
          <Card>
            <EmptyState
              icon={<SearchX aria-hidden className="h-6 w-6" />}
              title={t("odds.filters.emptyTitle")}
              body={t("odds.filters.emptyBody")}
              action={
                <button
                  type="button"
                  onClick={() => setFilters({ ...NO_ODDS_FILTERS, sort: filters.sort })}
                  className="rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium hover:bg-elevated"
                >
                  {t("odds.filters.clear")}
                </button>
              }
            />
          </Card>
        ) : (
          <OddsBoard
            fixtures={paged.items}
            total={kept.length}
            market={shownMarket}
            hours={board.window_hours}
            grouped={effective.sort === "time"}
            onWiden={board.window_hours < WIDEST ? () => setHours(WIDEST) : undefined}
            footer={
              <Pager
                paged={paged}
                onChange={() =>
                  document
                    .getElementById("odds-panel")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
              />
            }
          />
        )}
      </>
    );
  }

  return (
    <div className="space-y-6">
      <PageTitle
        title={t("nav.odds")}
        subtitle={t("odds.subtitle")}
        right={auth.showAdmin ? <ShadowToggle /> : undefined}
      />
      <FairExplainer />

      <div className="space-y-3">
        <MarketTabs value={market} onChange={setMarket} />
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <span aria-hidden className="text-label text-subtle-foreground">
              {t("odds.window.label")}
            </span>
            <ChipGroup
              label={t("odds.window.label")}
              value={hours}
              options={windows}
              onChange={setHours}
              testId="odds-window"
            />
          </div>
          {asOf ? (
            <span className="inline-flex items-center gap-1 text-caption text-muted-foreground">
              <Clock aria-hidden className="h-3 w-3" />
              {t("odds.pricesUpdated", { when: formatRelative(asOf) })}
            </span>
          ) : null}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center">
          <div className="col-span-2 sm:col-span-1">
            <SearchBox
              value={filters.query}
              onChange={(q) => update({ query: q })}
              placeholder={t("odds.filters.searchPlaceholder")}
              label={t("odds.filters.search")}
              testId="odds-search"
            />
          </div>
          <FacetPicker<string>
            label={t("odds.filters.country")}
            anyLabel={t("odds.filters.allCountries")}
            value={country}
            options={countries}
            onChange={(c) => update({ country: c, competition: null })}
            icon={<Globe2 />}
            testId="odds-country"
          />
          <FacetPicker<string>
            className="max-[359px]:col-span-2"
            label={t("odds.filters.competition")}
            anyLabel={t("odds.filters.allCompetitions")}
            value={competition === null ? null : String(competition)}
            options={competitions.map((c) => ({ ...c, key: String(c.key) }))}
            onChange={(c) => update({ competition: c === null ? null : Number(c) })}
            icon={<Trophy />}
            testId="odds-competition"
          />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <button
            type="button"
            aria-pressed={filters.aboveFair}
            onClick={() => update({ aboveFair: !filters.aboveFair })}
            data-testid="odds-above-fair"
            className={cn(
              "tap-y relative inline-flex h-9 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              filters.aboveFair
                ? "border-positive/50 bg-positive-soft text-positive"
                : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
            )}
          >
            {t("odds.filters.aboveFair")}
          </button>
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <span aria-hidden className="text-label text-subtle-foreground">
              {t("odds.filters.sort")}
            </span>
            <ChipGroup
              label={t("odds.filters.sort")}
              value={filters.sort}
              options={sorts}
              onChange={(sort) => update({ sort })}
              testId="odds-sort"
            />
          </div>
          {filtered ? (
            <button
              type="button"
              onClick={() => setFilters({ ...NO_ODDS_FILTERS, sort: filters.sort })}
              className="tap relative ml-auto inline-flex min-h-9 items-center text-xs font-medium text-primary hover:underline"
            >
              {t("odds.filters.clear")}
            </button>
          ) : null}
        </div>
      </div>

      <div
        id="odds-panel"
        role="tabpanel"
        aria-labelledby={`odds-tab-${market}`}
        aria-busy={refreshing}
        className={cn("scroll-mt-20 space-y-8 transition-opacity", refreshing && "opacity-60")}
      >
        {content}
      </div>
    </div>
  );
}

/** A tab bar that scrolls sideways on a phone; arrow keys move between markets. */
function MarketTabs({
  value,
  onChange,
}: {
  value: MarketKey;
  onChange: (market: MarketKey) => void;
}) {
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const bar = useRef<HTMLDivElement>(null);
  // True while some tab is hidden past the right edge: the bar fades there to say so.
  const [more, setMore] = useState(false);

  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const update = () => setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(el);
    return () => {
      el.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, []);

  function choose(index: number, focus: boolean) {
    const m = MARKETS[index];
    const el = tabs.current[index];
    if (!m) return;
    onChange(m);
    if (focus) el?.focus();
    el?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = MARKETS.indexOf(value);
    const last = MARKETS.length - 1;
    const next =
      e.key === "ArrowRight"
        ? i === last
          ? 0
          : i + 1
        : e.key === "ArrowLeft"
          ? i === 0
            ? last
            : i - 1
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? last
              : null;
    if (next === null) return;
    e.preventDefault();
    choose(next, true);
  }

  return (
    <div
      ref={bar}
      role="tablist"
      aria-label={t("odds.marketsLabel")}
      onKeyDown={onKeyDown}
      data-testid="odds-market-tabs"
      className={cn(
        "flex gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        more && "[mask-image:linear-gradient(to_right,#000_calc(100%_-_3rem),transparent)]",
      )}
    >
      {MARKETS.map((m, i) => {
        const on = m === value;
        return (
          <button
            key={m}
            ref={(el) => {
              tabs.current[i] = el;
            }}
            id={`odds-tab-${m}`}
            type="button"
            role="tab"
            aria-selected={on}
            aria-controls="odds-panel"
            tabIndex={on ? 0 : -1}
            onClick={() => choose(i, false)}
            className={cn(
              "tap-y relative h-9 shrink-0 whitespace-nowrap rounded-lg px-3 text-[0.8125rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:flex-1 md:text-sm",
              on
                ? "bg-elevated text-foreground shadow-sm ring-1 ring-border-strong"
                : "text-muted-foreground hover:bg-elevated/50 hover:text-foreground",
            )}
          >
            <span className="md:hidden">{marketShort(m)}</span>
            <span className="hidden md:inline">{tabLabel(m)}</span>
          </button>
        );
      })}
    </div>
  );
}

function OddsSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true" aria-label={t("common.loading")}>
      <div className="space-y-3">
        <SkeletonBlock className="h-5 w-64 max-w-full" />
        <div className="flex gap-3 overflow-hidden sm:grid sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <SkeletonBlock key={i} className="h-36 w-[82%] shrink-0 sm:w-auto" />
          ))}
        </div>
      </div>
      <div className="space-y-3">
        <SkeletonBlock className="h-5 w-48" />
        {[0, 1, 2, 3].map((i) => (
          <SkeletonBlock key={i} className="h-44 lg:h-28" />
        ))}
      </div>
    </div>
  );
}
