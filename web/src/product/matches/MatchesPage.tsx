/**
 * Matches: every match of the reader's local day, by competition. Live rows take their
 * score and minute from the live follow; the rest comes from the stored fixtures.
 *
 * REVIEW PREDIGOL, point 3: the day chips read Hoy, Mañana and the date after; the list
 * narrows by country, category and a team's name (and still by competition).
 *
 * Plan UX, B2 (section 38): the reader's own come first - by default, once they chose
 * favourites, the day of their leagues and teams, everything one tap away and counted (while
 * they are the suggested ones, every match, the suggested a tap away); their leagues lead the
 * list in their order, after what is in play; each of their competitions and each match of a
 * team they follow says why. A day without theirs says so and shows their next matches.
 * FBI_PERSONALIZATION=0: the common list.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { CalendarX2, ChevronRight, Globe2, Layers, RadioTower, SearchX } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { MatchSummary } from "@/lib/api/v1/types";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { t, useI18n } from "@/lib/i18n";
import { formatDateLong, shiftDay, todayKey, zonedInstant } from "@/lib/time";
import { Card, EmptyState, ErrorState, PageTitle, SkeletonBlock } from "@/product/shared/States";
import { FilterSheet, SheetField } from "@/product/shared/FilterSheet";
import {
  followFirst,
  followSet,
  reasonOf,
  whyOf,
  type FollowSet,
} from "@/product/favorites/follow";
import { ScopeSwitch } from "@/product/favorites/ScopeSwitch";
import { NextRow } from "@/product/home/TodayBlocks";
import type { Why } from "@/product/home/why";
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
  type MatchItem,
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

/**
 * En vivo is a filter of Partidos (plan UX, A15): with it on, today, the board of the matches in play - their
 * statistics, PrediGol's picks first, every 15 seconds - is one tap further, at its own address (/live).
 */
function LiveBoardLink() {
  return (
    <Link
      to="/live"
      data-testid="matches-live-board"
      className="flex min-h-14 items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 px-3 py-2.5 transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <RadioTower aria-hidden className="h-5 w-5 shrink-0 text-primary" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">{t("matches.liveBoard.open")}</span>
        <span className="block text-caption text-muted-foreground">
          {t("matches.liveBoard.body")}
        </span>
      </span>
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-primary" />
    </Link>
  );
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

/** Why a competition is the reader's: a league they follow («Tu liga», or «Sugerida» while they chose none). */
function competitionWhy(id: number, name: string, follow: FollowSet | null): Why | null {
  if (!follow || !follow.leagues.has(id)) return null;
  return whyOf({ kind: "league", names: [name] }, follow.suggested);
}

/** Why a match is the reader's when its competition is not: a team they follow plays it. */
function rowWhyOf(follow: FollowSet | null) {
  return (item: MatchItem): Why | null => {
    if (!follow) return null;
    const reason = reasonOf(item.match, follow);
    if (!reason || reason.kind !== "team") return null;
    return whyOf(reason, follow.suggested);
  };
}

/** The reader's next matches, from Home's own answer (GET /today): when their day is empty, what comes next. */
function NextOfMine() {
  const today = useQuery(live.today);
  const next = today.data?.data?.following?.next ?? [];
  if (next.length === 0) return null;
  return (
    <div data-testid="matches-next-mine">
      <Card className="overflow-hidden">
        <p className="px-4 pt-3 text-sm font-semibold sm:px-5">{t("matches.mine.next")}</p>
        <ul className="divide-y divide-border/60">
          {next.slice(0, 5).map((n) => (
            <li key={n.fixture_id}>
              <NextRow n={n} />
            </li>
          ))}
        </ul>
      </Card>
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

  // A reader's own (the owner's console account sees the common list, as with the welcome and the star).
  const reader = useAuth().user?.role === "USER";
  const favorites = useQuery({ ...live.favorites, enabled: reader });
  const follow = useMemo(
    () => (reader ? followSet(favorites.data) : null),
    [reader, favorites.data],
  );
  // The reader's own by default once they chose favourites (plan UX, B2); while they are the suggested ones, every match
  // with the suggested a tap away; without favourites known or with personalisation off, every match.
  const scope = follow ? (view.scope ?? (follow.suggested ? "all" : "mine")) : "all";
  const allItems = useMemo(() => toItems(rows, followed), [rows, followed]);
  const ownItems = useMemo(
    () => (follow ? allItems.filter((it) => reasonOf(it.match, follow) !== null) : allItems),
    [allItems, follow],
  );
  const items = scope === "mine" ? ownItems : allItems;
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
    return followFirst(groupByCompetition(visible, locale), follow);
  }, [items, view.status, view.query, view.category, country, competition, locale, follow]);

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
  } else if (scope === "mine" && ownItems.length === 0) {
    const suggested = follow?.suggested ?? false;
    body = (
      <div className="space-y-3">
        <div data-testid="matches-mine-empty">
          <Card>
            <EmptyState
              icon={<CalendarX2 aria-hidden className="h-6 w-6" />}
              title={t(
                view.day === today
                  ? suggested
                    ? "matches.mine.emptyTodaySuggested"
                    : "matches.mine.emptyToday"
                  : suggested
                    ? "matches.mine.emptyDaySuggested"
                    : "matches.mine.emptyDay",
              )}
              body={t("matches.mine.others", { count: allItems.length })}
              action={
                <button
                  type="button"
                  onClick={() => update({ scope: "all" })}
                  data-testid="matches-mine-see-all"
                  className="tap-y relative rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium hover:bg-elevated"
                >
                  {t("matches.mine.seeAll")}
                </button>
              }
            />
          </Card>
        </div>
        <NextOfMine />
      </div>
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
            why={competitionWhy(g.id, g.competition.name, follow)}
            rowWhy={follow && !follow.leagues.has(g.id) ? rowWhyOf(follow) : undefined}
          />
        ))}
      </div>
    );
  }

  // The four facets - a team's name, the country, the category, the competition: in a row from 1024 px, in the
  // «Filtros» sheet below it (plan UX, A15); the day and the state chips (En vivo among them) stay on the page.
  const facetsOn =
    (country !== null ? 1 : 0) +
    (view.category !== null ? 1 : 0) +
    (competition !== null ? 1 : 0) +
    (searching ? 1 : 0);
  const shown = groups.reduce((n, g) => n + g.items.length, 0);
  // The same pickers in the desk's row and in the sheet, where their name is written above them: there, while nothing
  // is chosen, they say «Todos los países» instead of repeating «País».
  const countryPicker = (sheet: boolean) => (
    <FacetPicker<string>
      label={t("matches.filters.country")}
      anyLabel={t("matches.filters.allCountries")}
      emptyText={sheet ? t("matches.filters.allCountries") : undefined}
      value={country}
      options={countries}
      onChange={(c) => update({ country: c, competition: null })}
      icon={<Globe2 />}
      testId="country-select"
    />
  );
  const categoryPicker = (sheet: boolean) => (
    <FacetPicker<Category>
      label={t("matches.filters.category")}
      anyLabel={t("matches.filters.allCategories")}
      emptyText={sheet ? t("matches.filters.allCategories") : undefined}
      value={view.category}
      options={categories}
      onChange={(c) => update({ category: c, competition: null })}
      icon={<Layers />}
      testId="category-select"
    />
  );
  const competitionPicker = (sheet: boolean) => (
    <CompetitionPicker
      value={competition}
      options={options}
      onChange={(c) => update({ competition: c })}
      emptyText={sheet ? t("matches.filters.allCompetitions") : undefined}
    />
  );
  const searchBox = <SearchBox value={view.query} onChange={search} />;

  return (
    <div className="space-y-4">
      <PageTitle title={t("nav.matches")} subtitle={dayTitle(view.day, today)} />

      <div className="space-y-3">
        {follow ? (
          <ScopeSwitch
            value={scope}
            onChange={(next) => update({ scope: next })}
            mine={ownItems.length}
            all={allItems.length}
            suggested={follow.suggested}
            ns="matches"
            testId="matches-scope"
          />
        ) : null}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <DayNav day={view.day} today={today} onChange={(day) => update({ day })} />
          <div
            className="hidden gap-2 lg:flex lg:flex-wrap lg:justify-end"
            data-testid="matches-facets"
          >
            {countryPicker(false)}
            {categoryPicker(false)}
            {competitionPicker(false)}
            {searchBox}
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          <div className="min-w-0 flex-1">
            {/* On a phone the chips scroll from the screen's left edge up to the «Filtros» button. */}
            <StatusChips
              value={view.status}
              counts={matches.data ? counts : null}
              onChange={(status: StatusFilter) => update({ status })}
              className="mr-0 pr-1"
            />
          </div>
          <FilterSheet
            testId="matches-filters"
            active={facetsOn}
            onReset={() => update({ competition: null, query: "", country: null, category: null })}
            showLabel={matches.data ? t("matches.filters.show", { count: shown }) : undefined}
          >
            <SheetField label={t("matches.filters.team")}>{searchBox}</SheetField>
            <SheetField label={t("matches.filters.country")}>{countryPicker(true)}</SheetField>
            <SheetField label={t("matches.filters.category")}>{categoryPicker(true)}</SheetField>
            <SheetField label={t("matches.filters.competition")}>
              {competitionPicker(true)}
            </SheetField>
          </FilterSheet>
          {filtered && rows.length > 0 ? (
            <button
              type="button"
              onClick={clearFilters}
              className="tap-y relative ml-auto hidden min-h-9 shrink-0 items-center text-xs font-medium text-primary hover:underline lg:inline-flex"
            >
              {t("matches.filters.clear")}
            </button>
          ) : null}
        </div>
      </div>

      {view.status === "live" && view.day === today && counts.live > 0 ? <LiveBoardLink /> : null}
      {body}
    </div>
  );
}
