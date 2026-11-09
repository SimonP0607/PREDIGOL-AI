/**
 * Cuotas as an explorer by families (plan Cuotas, section 5; ola 3): family tabs and market chips, the period and the line
 * inside the market's card, one search for teams, competitions and markets, filters and order that live in the URL, and for
 * each match the best price of every selection with its bookmaker - the market's fair price and the difference with it only
 * where there is one, small and grey -, the comparison of every bookmaker and the movement on demand.
 *
 * The route (`product/odds/ExplorerScreen.tsx`, while `odds_explorer` is on) parses its search with `parseExplorerSearch`,
 * hands the state in and writes back what `onStateChange` gives (`serializeExplorerState`); the data comes through
 * `ExplorerData`, one hook per endpoint (`apiData.ts` on the API, `fake.ts` in the tests).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { t } from "@/lib/i18n";
import { GlossaryLink } from "@/components/system/GlossaryTerm";
import { useGuideScreen } from "@/product/guides/context";
import { Card, EmptyState, ErrorState, PageTitle, StaleNote } from "@/product/shared/States";
import type { RowEnv } from "./env";
import { filterOptions } from "./filterOptions";
import { ExplorerSearch, FiltersRow, FiltersSheet } from "./Filters";
import { useAnnouncer, useMarketMemory, usePriceMoves, useSeen, useSlipAnnouncer } from "./hooks";
import { MarketCard } from "./MarketCard";
import type { BoardSort, ExplorerData } from "./model";
import { MOTION } from "./motion";
import { FamilyTabs, MarketChips } from "./Navigation";
import { clientFilter } from "./rows";
import { ExplorerSkeleton } from "./Skeletons";
import {
  activeFilters,
  boardQuery,
  clearFilters,
  familiesQuery,
  filtersOf,
  withFilters,
  withLine,
  withMarket,
  withPeriod,
  withTab,
  type ExplorerFilters,
  type ExplorerState,
} from "./state";
import { StatusBar } from "./Status";
import {
  buildTabs,
  familyFor,
  marketOfTab,
  resolveView,
  tabId,
  type MarketHit,
  type TabKey,
  type TabMarket,
} from "./tabs";

export interface StateChange {
  /** Typing in the search: replace the history entry instead of adding one per pause. */
  replace?: boolean;
}

export interface OddsExplorerProps {
  /** The data layer: one hook per endpoint (a stable object). */
  data: ExplorerData;
  /** The URL's state (`parseExplorerSearch` of the route's search). */
  state: ExplorerState;
  /** A choice changed it: the route writes `serializeExplorerState(next)` to the URL. */
  onStateChange: (next: ExplorerState, how?: StateChange) => void;
  /** The screen's guide: its «?» in the header, and the screen said ready for its steps. The route's; none in the tests. */
  guide?: boolean;
  /** A fixed clock (tests); the real one otherwise. */
  now?: number;
}

const PANEL_ID = "explorer-panel";

export function OddsExplorer({
  data,
  state,
  onStateChange,
  guide,
  now: fixedNow,
}: OddsExplorerProps) {
  const now = fixedNow ?? Date.now();
  const [paused, setPaused] = useState(false);
  const [memory, remember] = useMarketMemory();
  const [said, announce] = useAnnouncer();
  useSlipAnnouncer(announce);
  const follow = data.useFollow();

  const families = data.useFamilies(familiesQuery(state), { paused, enabled: true });
  useGuideScreen("odds", { ready: guide === true && !families.isPending });
  const tabs = useMemo(() => buildTabs(families.data?.families), [families.data]);
  const view = useMemo(
    () =>
      resolveView(
        tabs,
        { tab: state.tab, market: state.market, period: state.period, line: state.line },
        memory,
      ),
    [tabs, state.tab, state.market, state.period, state.line, memory],
  );
  const query = boardQuery(state, view);
  const answer = data.useBoard(query, { paused, enabled: view !== null });
  const seen = useSeen(answer.data);
  // While another board loads, the previous one stays (dimmed) when it is the same market and period - other filters, another
  // line -; another market's rows would read wrong under this one's name: then the skeleton.
  const held = answer.data?.[answer.data.length - 1];
  const sameBoard =
    !!view && !!held && held.market.key === view.market.key && held.period === view.period;
  const board =
    answer.isPlaceholderData && !sameBoard
      ? { ...answer, data: undefined, isPending: true, isPlaceholderData: false }
      : answer;
  const pages = board.data;
  const loaded = useMemo(() => pages?.flatMap((p) => p.rows) ?? [], [pages]);
  const rows = useMemo(
    () => clientFilter(loaded, { window: state.window, mine: state.mine }, follow, now),
    // `now` moves every render: the day only changes at midnight, so the rows follow the data, not the clock.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loaded, state.window, state.mine, follow],
  );
  const boardKey = JSON.stringify(query);
  const moves = usePriceMoves(loaded, boardKey, board.updatedAt);
  const lastPage = pages?.[pages.length - 1];
  const filters = filtersOf(state);
  const filtered = activeFilters(filters) > 0;
  // «Hoy» by kick-off: once a loaded match starts after today, no later page can bring one of today's.
  const lastRow = loaded[loaded.length - 1];
  const pastToday =
    state.window === "today" && state.sort === "time" && !!lastRow && !rows.includes(lastRow);
  const hasMore = board.hasNextPage && !pastToday;
  // The API counts its own filters; «Hoy» and «Mis equipos y ligas» are the client's, over the pages loaded: their count is
  // known once nothing more can come.
  const clientFiltered = state.window === "today" || (state.mine && follow !== null);
  const total = board.isPlaceholderData
    ? null
    : clientFiltered
      ? hasMore
        ? null
        : rows.length
      : (lastPage?.total ?? null);

  // Said once the answer to a new board arrives: how many matches it has.
  const told = useRef<string | null>(null);
  useEffect(() => {
    if (board.isPending || board.isPlaceholderData || total === null) return;
    if (told.current === boardKey) return;
    const first = told.current === null;
    told.current = boardKey;
    if (!first) announce(t("explorer.status.results", { count: total }));
  }, [board.isPending, board.isPlaceholderData, total, boardKey, announce]);

  const change = useCallback(
    (next: ExplorerState, how?: StateChange) => onStateChange(next, how),
    [onStateChange],
  );
  const chooseTab = (key: TabKey) => {
    const tab = tabs.find((x) => x.key === key);
    if (!tab || key === view?.tab.key) return;
    change(withTab(state, key, marketOfTab(tab, null, memory)?.key ?? null));
  };
  const chooseMarket = (m: TabMarket) => {
    if (!view) return;
    remember(view.tab.key, m.key);
    change(
      withMarket(
        state,
        view.tab.key,
        m.key,
        m.periods.map((p) => p.period),
      ),
    );
  };
  const jump = (hit: MarketHit) => {
    remember(hit.tab, hit.market.key);
    const next = withMarket(
      state,
      hit.tab,
      hit.market.key,
      hit.market.periods.map((p) => p.period),
    );
    change({ ...next, q: "" });
    announce(t("explorer.search.jumped", { market: hit.title }));
  };
  const onQuery = useCallback(
    (q: string) => change({ ...state, q }, { replace: true }),
    [change, state],
  );
  const patch = (p: Partial<ExplorerFilters>) => change(withFilters(state, p));
  const sortBy = (sort: BoardSort) => change({ ...state, sort });
  const clear = () => change(clearFilters(state));
  const pause = (next: boolean) => {
    setPaused(next);
    announce(next ? t("explorer.status.paused") : t("explorer.status.resumed"));
  };

  const env: RowEnv | null = view
    ? {
        data,
        // The rows are read as the market they were fetched for (the same as the view's but for a moment).
        info: lastPage?.market ?? view.market.info,
        period: view.period,
        family: familyFor(view.market, view.period),
        bookmakers: seen.bookmakers,
        competitions: seen.competitions,
        now,
        moves: moves.moves,
        version: moves.version,
        withDay: state.sort !== "time",
      }
    : null;
  const options = filterOptions(seen.competitions, seen.bookmakers, follow !== null);

  let content;
  if (families.isPending) {
    content = <ExplorerSkeleton />;
  } else if (families.isError && !families.data) {
    content = (
      <Card>
        <ErrorState error={families.error} onRetry={families.refetch} />
      </Card>
    );
  } else if (!view || !env) {
    const off = families.data ? !families.data.book_enabled : false;
    content = (
      <Card>
        <EmptyState
          title={off ? t("explorer.empty.offTitle") : t("explorer.empty.windowTitle")}
          body={off ? t("explorer.empty.offBody") : t("explorer.empty.windowBody")}
          action={
            !off && state.window !== 72 ? (
              <button
                type="button"
                onClick={() => patch({ window: 72 })}
                className="tap-y relative inline-flex h-9 items-center rounded-full border border-border-strong px-4 text-xs font-semibold hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("explorer.empty.widen")}
              </button>
            ) : undefined
          }
        />
      </Card>
    );
  } else {
    content = (
      <>
        <FamilyTabs tabs={tabs} active={view.tab.key} onChoose={chooseTab} panelId={PANEL_ID} />
        <div
          id={PANEL_ID}
          role="tabpanel"
          aria-labelledby={tabId(view.tab.key)}
          className="space-y-3"
        >
          <div key={view.tab.key} className={MOTION.swap}>
            <MarketChips tab={view.tab} active={view.market.key} onChoose={chooseMarket} />
          </div>
          <FiltersRow
            value={filters}
            sort={state.sort}
            options={options}
            onChange={patch}
            onSort={sortBy}
            onClear={clear}
          />
          {board.isError && board.data ? <StaleNote onRetry={board.refetch} /> : null}
          <MarketCard
            key={`${view.tab.key}|${view.market.key}|${view.period}|${view.line}`}
            className={MOTION.swap}
            view={view}
            sort={state.sort}
            rows={rows}
            total={total}
            board={board}
            env={env}
            filtered={filtered}
            hasMore={hasMore}
            onPeriod={(p) => change(withPeriod(state, p))}
            onLine={(l) => change(withLine(state, l))}
            onClear={clear}
            onWiden={state.window === 72 ? null : () => patch({ window: 72 })}
          />
        </div>
      </>
    );
  }

  return (
    <div className="space-y-4" data-testid="odds-explorer">
      <PageTitle
        {...(guide ? { guide: "odds" as const } : {})}
        title={t("nav.odds")}
        subtitle={t("explorer.subtitle")}
        right={
          <StatusBar
            updatedAt={
              lastPage ? Date.parse(lastPage.generated_at) || board.updatedAt : board.updatedAt
            }
            paused={paused}
            onPause={pause}
          />
        }
      />
      <p className="text-xs text-muted-foreground" data-guide="odds-fair">
        {t("explorer.fairLine")} <GlossaryLink term="fairOdds" />
      </p>
      <div className="flex items-start gap-2">
        <ExplorerSearch value={state.q} tabs={tabs} onQuery={onQuery} onJump={jump} />
        <FiltersSheet
          value={filters}
          sort={state.sort}
          options={options}
          onApply={(f, sort) => change({ ...withFilters(state, f), sort })}
        />
      </div>
      {content}
      <p aria-live="polite" aria-atomic="true" className="sr-only" data-testid="explorer-live">
        {said}
      </p>
    </div>
  );
}
