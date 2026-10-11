/**
 * Matches: every match of the reader's local day, by competition. Live rows take their
 * score and minute from the live follow; the rest comes from the stored fixtures.
 *
 * REVIEW PREDIGOL, point 3: the day chips read Hoy, Mañana and the date after; the list
 * narrows by country, category and a team's name (and still by competition).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarX2, Globe2, Layers, SearchX } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { MatchSummary } from "@/lib/api/v1/types";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { t, useI18n } from "@/lib/i18n";
import { formatDateLong, shiftDay, todayKey, zonedInstant } from "@/lib/time";
import { Card, EmptyState, ErrorState, PageTitle, SkeletonBlock } from "@/product/shared/States";
import { CompetitionSection } from "./CompetitionSection";
import {
  CATEGORIES,
  categoriesOf,
  countryKey,
  countryOptions,
  inFacets,
  type Category,
} from "./facets";
import { CompetitionPicker, DayNav, FacetPicker, SearchBox, StatusChips } from "./Filters";
import {
  competitionOptions,
  groupByCompetition,
  inStatus,
  statusCounts,
  toItems,
  wantsLiveBoard,
  type StatusFilter,
} from "./model";
import { dayMatchesQuery } from "./query";
import { readView, writeView, type MatchesView } from "./viewState";

const NO_ROWS: MatchSummary[] = [];
const NO_LIVE: LiveMatch[] = [];

function dayTitle(day: string, today: string): string {
  const long = formatDateLong(zonedInstant(day, 12));
  const rel =
    day === today
      ? t("common.day.today")
      : day === shiftDay(today, 1)
        ? t("common.day.tomorrow")
        : day === shiftDay(today, -1)
          ? t("common.day.yesterday")
          : null;
  return rel ? `${rel} · ${long}` : long.charAt(0).toUpperCase() + long.slice(1);
}

function ListSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label={t("common.loading")}>
      {[4, 3, 5].map((rows, i) => (
        <div key={i} className="rounded-xl border border-border bg-card">
          <div className="flex items-center gap-2 border-b border-border/70 px-3 py-3">
            <SkeletonBlock className="h-[18px] w-[18px] rounded-sm" />
            <SkeletonBlock className="h-3.5 w-40" />
            <SkeletonBlock className="ml-auto h-3 w-6" />
          </div>
          <div className="divide-y divide-border/60">
            {Array.from({ length: rows }, (_, j) => (
              <div key={j} className="flex items-center gap-3 px-3 py-3">
                <SkeletonBlock className="h-3.5 w-10" />
                <div className="flex-1 space-y-2 sm:space-y-0">
                  <SkeletonBlock className="h-3.5 w-3/5 sm:w-full" />
                  <SkeletonBlock className="h-3.5 w-1/2 sm:hidden" />
                </div>
                <SkeletonBlock className="h-4 w-12" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function MatchesPage() {
  const { locale } = useI18n();
  const [view, setView] = useState<MatchesView>(readView);
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(() => new Set());
  useEffect(() => writeView(view), [view]);

  const today = todayKey();
  const update = useCallback(
    (patch: Partial<MatchesView>) => setView((v) => ({ ...v, ...patch })),
    [],
  );

  const matches = useQuery(dayMatchesQuery(view.day));
  const rows = matches.data?.rows ?? NO_ROWS;
  const needsBoard = useMemo(() => wantsLiveBoard(rows, Date.now()), [rows]);
  const board = useQuery({ ...live.liveBoard, enabled: needsBoard });
  const followed = needsBoard ? (board.data?.data.matches ?? NO_LIVE) : NO_LIVE;

  const items = useMemo(() => toItems(rows, followed), [rows, followed]);
  const counts = useMemo(() => statusCounts(items), [items]);
  const countries = useMemo(
    () =>
      countryOptions(
        items.map((i) => i.match),
        locale,
        t("matches.filters.international"),
      ),
    [items, locale],
  );
  // A country or category picked on another day may not play today: the list then shows them all.
  const country =
    view.country !== null && countries.some((c) => c.key === view.country) ? view.country : null;
  const inScope = useMemo(
    () =>
      items.filter(
        (it) =>
          (country === null || countryKey(it.match.competition) === country) &&
          (view.category === null || categoriesOf(it.match.competition).includes(view.category)),
      ),
    [items, country, view.category],
  );
  const categories = useMemo(
    () =>
      CATEGORIES.map((key) => ({
        key,
        label: t(`matches.category.${key}`),
        count: items.filter(
          (it) =>
            (country === null || countryKey(it.match.competition) === country) &&
            categoriesOf(it.match.competition).includes(key),
        ).length,
      })).filter((c) => c.count > 0),
    [items, country],
  );
  const options = useMemo(() => competitionOptions(inScope, locale), [inScope, locale]);
  const competition =
    view.competition !== null && options.some((o) => o.id === view.competition)
      ? view.competition
      : null;
  const searching = view.query.trim().length > 0;
  const search = (query: string) => {
    // A search shows every hit: folded competitions open again.
    if (query.trim()) setCollapsed(new Set());
    update({ query });
  };

  const groups = useMemo(() => {
    const visible = items.filter(
      (it) =>
        inStatus(it.group, view.status) &&
        (competition === null || it.match.competition.id === competition) &&
        inFacets(it.match, { country, category: view.category, team: view.query }),
    );
    return groupByCompetition(visible, locale);
  }, [items, view.status, view.query, view.category, country, competition, locale]);

  const filtered =
    view.status !== "all" ||
    competition !== null ||
    searching ||
    country !== null ||
    view.category !== null;
  const clearFilters = () =>
    update({ status: "all", competition: null, query: "", country: null, category: null });
  const toggle = (id: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  let body: ReactNode;
  if (matches.isPending) {
    body = <ListSkeleton />;
  } else if (matches.isError && !matches.data) {
    body = (
      <Card>
        <ErrorState error={matches.error} onRetry={() => void matches.refetch()} />
      </Card>
    );
  } else if (rows.length === 0) {
    body = (
      <Card>
        <EmptyState
          icon={<CalendarX2 aria-hidden className="h-6 w-6" />}
          title={t("matches.empty.dayTitle")}
          body={t("matches.empty.dayBody")}
          action={
            view.day !== today ? (
              <button
                type="button"
                onClick={() => update({ day: today })}
                className="rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium hover:bg-elevated"
              >
                {t("matches.empty.goToday")}
              </button>
            ) : null
          }
        />
      </Card>
    );
  } else if (groups.length === 0) {
    body = (
      <Card>
        <EmptyState
          icon={<SearchX aria-hidden className="h-6 w-6" />}
          title={t("matches.empty.filtersTitle")}
          body={t("matches.empty.filtersBody")}
          action={
            <button
              type="button"
              onClick={clearFilters}
              className="rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium hover:bg-elevated"
            >
              {t("matches.filters.clear")}
            </button>
          }
        />
      </Card>
    );
  } else {
    body = (
      <div className="space-y-3" data-testid="matches-list">
        {groups.map((g) => (
          <CompetitionSection
            key={g.id}
            group={g}
            collapsed={collapsed.has(g.id)}
            onToggle={() => toggle(g.id)}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageTitle title={t("nav.matches")} subtitle={dayTitle(view.day, today)} />

      <div className="space-y-3">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <DayNav day={view.day} today={today} onChange={(day) => update({ day })} />
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end">
            <FacetPicker<string>
              label={t("matches.filters.country")}
              anyLabel={t("matches.filters.allCountries")}
              value={country}
              options={countries}
              onChange={(c) => update({ country: c, competition: null })}
              icon={<Globe2 />}
              testId="country-select"
            />
            <FacetPicker<Category>
              label={t("matches.filters.category")}
              anyLabel={t("matches.filters.allCategories")}
              value={view.category}
              options={categories}
              onChange={(c) => update({ category: c, competition: null })}
              icon={<Layers />}
              testId="category-select"
            />
            <CompetitionPicker
              value={competition}
              options={options}
              onChange={(c) => update({ competition: c })}
            />
            <SearchBox value={view.query} onChange={search} />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <StatusChips
              value={view.status}
              counts={matches.data ? counts : null}
              onChange={(status: StatusFilter) => update({ status })}
            />
          </div>
          {filtered && rows.length > 0 ? (
            <button
              type="button"
              onClick={clearFilters}
              className="ml-auto hidden shrink-0 text-xs font-medium text-primary hover:underline sm:inline"
            >
              {t("matches.filters.clear")}
            </button>
          ) : null}
        </div>
      </div>

      {body}
    </div>
  );
}
