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
 *
 * Plan Partidos, F1 (UX-029): the competitions in the owner's priority after what is in play and the reader's own
 * (P1); a category that does not play that day is ignored, as a country is (P2); the state counts read the other
 * filters (P3); the day and the filters in the URL, the folds in the tab, and «‹ Partidos» back to the same place (P4);
 * one search box for a team or a competition, the filters on as chips, the bar of days and states kept in sight (P3,
 * P6); a search that waits 200 ms and rows drawn again only when they change (P5).
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
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
  type Scope,
} from "@/product/favorites/follow";
import { ScopeSwitch } from "@/product/favorites/ScopeSwitch";
import { NextRow } from "@/product/home/TodayBlocks";
import type { Why } from "@/product/home/why";
import { CompetitionSection } from "./CompetitionSection";
import { rememberOpened } from "./backToList";
import type { Category } from "./facets";
import {
  AppliedFilters,
  CompetitionPicker,
  DayNav,
  FacetPicker,
  SearchBox,
  StatusChips,
  type AppliedFilter,
} from "./Filters";
import {
  groupByCompetition,
  toItems,
  wantsLiveBoard,
  type MatchItem,
  type StatusFilter,
} from "./model";
import { narrowDay } from "./narrow";
import { dayMatchesQuery } from "./query";
import {
  hasFilters,
  readCollapsed,
  readView,
  searchOf,
  viewOf,
  writeCollapsed,
  writeView,
  type MatchesSearch,
  type MatchesView,
} from "./viewState";
import { useGuideScreen } from "@/product/guides/context";

const NO_ROWS: MatchSummary[] = [];
const NO_LIVE: LiveMatch[] = [];
/** The search waits this long after the last keystroke before the list follows (plan Partidos, P5). */
export const SEARCH_WAIT_MS = 200;
/** A filter change rewrites the list's own entry of the history: no new entry, no jump to the top, no cross-fade. */
const IN_PLACE = { replace: true, resetScroll: false, viewTransition: false } as const;
/** The buttons of the empty states: 44 px tall, like every control a thumb reaches (plan UX, A15). */
const EMPTY_ACTION =
  "min-h-11 rounded-md border border-border-strong px-4 text-sm font-medium transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

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

/**
 * The search as it is typed, and the search the list follows: the list follows 200 ms after the last keystroke, and a
 * cleared box at once. A change from outside (Limpiar, a chip's «×», the back button) replaces what is typed - unless
 * it is only what is typed without its trailing space.
 */
function useSearchDraft(committed: string, commit: (query: string) => void) {
  const [draft, setDraft] = useState(committed);
  const [seen, setSeen] = useState(committed);
  if (committed !== seen) {
    setSeen(committed);
    if (committed !== draft.trim()) setDraft(committed);
  }
  useEffect(() => {
    if (draft.trim() === committed) return;
    if (!draft.trim()) {
      commit("");
      return;
    }
    const id = window.setTimeout(() => commit(draft), SEARCH_WAIT_MS);
    return () => window.clearTimeout(id);
  }, [draft, committed, commit]);
  return [draft, setDraft] as const;
}

/**
 * The bar of days and states sticks under the app bar; the competitions' headers stick under it. Its height goes to
 * --matches-bar-h on the page, measured as it changes (a wrapped row, a rotated phone) - and 0 where it does not stick
 * (a phone held sideways, where the app bar scrolls away too).
 */
function useStickyHeight(
  page: RefObject<HTMLDivElement | null>,
  bar: RefObject<HTMLDivElement | null>,
) {
  useEffect(() => {
    const root = page.current;
    const el = bar.current;
    if (!root || !el || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const sticky = getComputedStyle(el).position === "sticky";
      root.style.setProperty("--matches-bar-h", `${sticky ? el.offsetHeight : 0}px`);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [page, bar]);
}

export function MatchesPage() {
  const { locale } = useI18n();
  const today = todayKey();
  const search: MatchesSearch = useSearch({ from: "/matches/" });
  const navigate = useNavigate({ from: "/matches/" });

  // Plan Partidos, P4: the URL says the view. A bare /matches (the menu's link) opens on the view kept for this tab,
  // written into the URL at once; from then on the URL alone decides, so «Limpiar» leaves it bare.
  const [stored] = useState(readView);
  const [scopeChoice, setScopeChoice] = useState<Scope | null>(stored.scope);
  const [restore, setRestore] = useState<MatchesSearch | null>(() => {
    if (hasFilters(search)) return null;
    const saved = searchOf(stored, today);
    return hasFilters(saved) ? saved : null;
  });
  if (restore !== null && hasFilters(search)) setRestore(null);
  useEffect(() => {
    if (restore) void navigate({ search: restore, ...IN_PLACE });
  }, [restore, navigate]);
  const effective = restore ?? search;
  const view = useMemo(
    () => viewOf(effective, today, scopeChoice),
    [effective, today, scopeChoice],
  );
  useEffect(() => writeView(view), [view]);

  const update = useCallback(
    (patch: Partial<MatchesView>) => {
      const { scope, ...filters } = patch;
      if (scope !== undefined) setScopeChoice(scope);
      if (Object.keys(filters).length === 0) return;
      void navigate({
        search: (prev: MatchesSearch) =>
          searchOf({ ...viewOf(prev, today, null), ...filters }, today),
        ...IN_PLACE,
      });
    },
    [navigate, today],
  );

  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(readCollapsed);
  useEffect(() => writeCollapsed(collapsed), [collapsed]);
  const toggle = useCallback(
    (id: number) =>
      setCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      }),
    [],
  );

  const commitQuery = useCallback(
    (query: string) => {
      // A search shows every hit: folded competitions open again.
      if (query.trim()) setCollapsed((prev) => (prev.size === 0 ? prev : new Set()));
      update({ query });
    },
    [update],
  );
  const [draft, setDraft] = useSearchDraft(view.query, commitQuery);

  const matches = useQuery(dayMatchesQuery(view.day));
  useGuideScreen("matches", { ready: !matches.isPending });
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
  // A country, category or competition that does not play this day is ignored (plan Partidos, P2); the state chips
  // count with every other filter on (P3).
  const day = useMemo(
    () =>
      narrowDay(
        items,
        {
          status: view.status,
          country: view.country,
          category: view.category,
          competition: view.competition,
          query: view.query,
        },
        locale,
        {
          international: t("matches.filters.international"),
          category: (key) => t(`matches.category.${key}`),
        },
      ),
    [items, view.status, view.country, view.category, view.competition, view.query, locale],
  );
  const { countries, categories, options, country, category, competition, query, counts } = day;
  const searching = query.length > 0;
  const groups = useMemo(
    () => followFirst(groupByCompetition(day.visible, locale), follow),
    [day.visible, locale, follow],
  );

  const filtered =
    view.status !== "all" ||
    competition !== null ||
    searching ||
    country !== null ||
    category !== null;
  const clearFilters = useCallback(() => {
    setDraft("");
    update({ status: "all", competition: null, query: "", country: null, category: null });
  }, [update, setDraft]);
  const resetFacets = useCallback(() => {
    setDraft("");
    update({ competition: null, query: "", country: null, category: null });
  }, [update, setDraft]);
  const onSearch = useCallback(
    (next: string) => {
      setDraft(next);
      // the box's «×»: the whole day back at once
      if (!next.trim()) commitQuery("");
    },
    [setDraft, commitQuery],
  );

  // A row opened from here: «‹ Partidos» on the match goes back to this very entry (filters and scroll).
  const onListClick = useCallback((e: MouseEvent<HTMLDivElement>) => {
    const target = e.target instanceof Element ? e.target.closest("a[data-fixture-id]") : null;
    const id = Number(target?.getAttribute("data-fixture-id"));
    if (Number.isSafeInteger(id) && id > 0) rememberOpened(id);
  }, []);

  const page = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  useStickyHeight(page, bar);

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
              <button type="button" onClick={() => update({ day: today })} className={EMPTY_ACTION}>
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
                  className={EMPTY_ACTION}
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
            <button type="button" onClick={clearFilters} className={EMPTY_ACTION}>
              {t("matches.filters.clear")}
            </button>
          }
        />
      </Card>
    );
  } else {
    body = (
      <div
        className="space-y-3"
        data-testid="matches-list"
        data-guide="matches-list"
        onClickCapture={onListClick}
      >
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

  // The four facets - a team or a competition, the country, the category, the competition: in a row from 1024 px, in the
  // «Filtros» sheet below it (plan UX, A15); the day and the state chips (En vivo among them) stay on the page.
  const facetsOn =
    (country !== null ? 1 : 0) +
    (category !== null ? 1 : 0) +
    (competition !== null ? 1 : 0) +
    (searching ? 1 : 0);
  const shown = groups.reduce((n, g) => n + g.items.length, 0);
  const applied: AppliedFilter[] = [];
  if (country !== null) {
    applied.push({
      key: "country",
      label: countries.find((c) => c.key === country)?.label ?? country,
      onRemove: () => update({ country: null }),
    });
  }
  if (category !== null) {
    applied.push({
      key: "category",
      label: t(`matches.category.${category}`),
      onRemove: () => update({ category: null }),
    });
  }
  if (competition !== null) {
    applied.push({
      key: "competition",
      label: options.find((o) => o.id === competition)?.name ?? String(competition),
      onRemove: () => update({ competition: null }),
    });
  }
  if (searching) {
    applied.push({
      key: "query",
      label: t("matches.filters.query", { query }),
      onRemove: () => {
        setDraft("");
        update({ query: "" });
      },
    });
  }
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
      value={category}
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
  const searchBox = (
    <SearchBox
      value={draft}
      onChange={onSearch}
      placeholder={t("matches.filters.searchAnyPlaceholder")}
      label={t("matches.filters.searchAny")}
    />
  );

  return (
    <div ref={page} className="space-y-4">
      <PageTitle guide="matches" title={t("nav.matches")} subtitle={dayTitle(view.day, today)} />

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
      {/* The days and the states stay in sight while the list scrolls (plan Partidos, P3); held sideways, a phone
          keeps its little height for the list. */}
      <div
        ref={bar}
        role="region"
        aria-label={t("matches.bar.label")}
        data-testid="matches-bar"
        className="top-sticky sticky z-20 -mx-4 space-y-2 bg-background/95 px-4 py-2 backdrop-blur short:static"
      >
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
            onReset={resetFacets}
            showLabel={matches.data ? t("matches.filters.show", { count: shown }) : undefined}
          >
            <SheetField label={t("matches.filters.teamOrCompetition")}>{searchBox}</SheetField>
            <SheetField label={t("matches.filters.country")}>{countryPicker(true)}</SheetField>
            <SheetField label={t("matches.filters.category")}>{categoryPicker(true)}</SheetField>
            <SheetField label={t("matches.filters.competition")}>
              {competitionPicker(true)}
            </SheetField>
          </FilterSheet>
        </div>
      </div>
      {rows.length > 0 ? (
        <AppliedFilters filters={applied} onClear={clearFilters} showClear={filtered} />
      ) : null}

      {view.status === "live" && view.day === today && counts.live > 0 ? <LiveBoardLink /> : null}
      {body}
    </div>
  );
}
