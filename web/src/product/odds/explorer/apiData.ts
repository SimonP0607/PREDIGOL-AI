/**
 * The explorer's data layer on the API (plan Cuotas, UX-069): each member of `ExplorerData` on the react-query options of
 * `lib/api/v1/queries` (BE-011). The envelopes are opened, an open page reads again every two minutes unless the reader
 * paused the updates (WCAG 2.2.2), and the previous answer stays on screen while another query loads (the explorer dims
 * it or shows its skeleton). Every reader shares the server's cache: nothing here asks the provider.
 */
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  type UseQueryResult,
} from "@tanstack/react-query";
import { useMemo } from "react";
import { live } from "@/lib/api/v1/queries";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  OddsBoardQuery,
  OddsFamiliesQuery,
  OddsMovementQuery,
  OddsPeriod,
} from "@/lib/api/v1/types_odds_explorer";
import { useAuth } from "@/lib/auth/AuthProvider";
import { followSet } from "@/product/favorites/follow";
import type {
  BoardPages,
  BoardQuery,
  ExplorerData,
  ExplorerFollow,
  FamiliesQuery,
  LiveOptions,
  Loadable,
  MovementQuery,
} from "./model";

/** How often an open page reads again: the server keeps an answer a minute and the book changes every few. */
export const REFRESH_MS = 2 * 60_000;

const PERIODS: ReadonlySet<string> = new Set<OddsPeriod>(["FT", "1H", "2H", "INTERVAL"]);

function periodOf(period: string): OddsPeriod | undefined {
  return PERIODS.has(period) ? (period as OddsPeriod) : undefined;
}

function interval(o: LiveOptions): number | false {
  return o.paused ? false : REFRESH_MS;
}

/** GET /odds/families' parameters: an empty choice is left out, so the same choice is the same cache entry. */
export function familiesParams(q: FamiliesQuery): OddsFamiliesQuery {
  return {
    hours: q.hours,
    country: q.country ?? undefined,
    competition: q.competition ?? undefined,
  };
}

/** GET /odds/board's parameters (the cursor is the page's): the explorer's own names, empty ones left out. */
export function boardParams(q: BoardQuery): OddsBoardQuery {
  const text = q.q.trim();
  return {
    ...familiesParams(q),
    market: q.market,
    period: periodOf(q.period),
    line: q.line,
    q: text || undefined,
    bookmaker: q.bookmaker ?? undefined,
    min_books: q.min_books ?? undefined,
    odds_min: q.odds_min ?? undefined,
    odds_max: q.odds_max ?? undefined,
    fair_only: q.fair_only || undefined,
    sort: q.sort,
  };
}

/** GET /odds/fixtures/{id}/movement's parameters: without a line, the market's main one. */
export function movementParams(q: MovementQuery): OddsMovementQuery {
  return { market: q.market, period: periodOf(q.period), line: q.line ?? undefined };
}

/** A react-query answer as the explorer reads it, the envelope opened. */
export function opened<T>(r: UseQueryResult<Envelope<T>>): Loadable<T> {
  return {
    data: r.data?.data,
    isPending: r.isPending,
    isError: r.isError,
    error: r.error,
    isFetching: r.isFetching,
    isPlaceholderData: r.isPlaceholderData,
    updatedAt: r.dataUpdatedAt,
    refetch: () => void r.refetch(),
  };
}

/** The data layer of the page (a module constant: the explorer calls its members as hooks, in the same order). */
export const API_EXPLORER_DATA: ExplorerData = {
  useFamilies(q, o) {
    const r = useQuery({
      ...live.oddsFamilies(familiesParams(q)),
      enabled: o.enabled,
      placeholderData: keepPreviousData,
      refetchInterval: interval(o),
    });
    return opened(r);
  },

  useBoard(q, o): BoardPages {
    const r = useInfiniteQuery({
      ...live.oddsBoardPages(boardParams(q)),
      enabled: o.enabled,
      placeholderData: keepPreviousData,
      refetchInterval: interval(o),
    });
    const pages = useMemo(() => r.data?.pages.map((p) => p.data), [r.data]);
    return {
      data: pages,
      isPending: r.isPending,
      isError: r.isError,
      error: r.error,
      isFetching: r.isFetching,
      isPlaceholderData: r.isPlaceholderData,
      updatedAt: r.dataUpdatedAt,
      refetch: () => void r.refetch(),
      hasNextPage: r.hasNextPage,
      isFetchingNextPage: r.isFetchingNextPage,
      fetchNextPage: () => void r.fetchNextPage(),
    };
  },

  useMatchBook(fixtureId, family, enabled) {
    return opened(useQuery({ ...live.matchOddsBook(fixtureId, family), enabled }));
  },

  useMovement(fixtureId, q, enabled) {
    return opened(useQuery({ ...live.oddsMovement(fixtureId, movementParams(q)), enabled }));
  },

  useFollow(): ExplorerFollow | null {
    // «Mis equipos y ligas» is a reader's: the owner's account and personalisation off have none
    const reader = useAuth().user?.role === "USER";
    const favorites = useQuery({ ...live.favorites, enabled: reader });
    return useMemo(() => (reader ? followSet(favorites.data) : null), [reader, favorites.data]);
  },
};
