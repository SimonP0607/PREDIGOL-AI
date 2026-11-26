/**
 * The readers' search (AP-B07): `GET /search/v2` (C-10) in groups, from two characters, kept a minute. If v2 does not answer
 * (the route off, an error), the earlier `GET /search` answers instead, so the search never goes dark; going back is this hook
 * reading `useSearchHits` alone. The Spanish names of countries and competitions come from C-10 1.1 itself (the table of
 * AP-B02 is no longer asked here; the earlier `GET /search`, which has no aliases, still uses it).
 */
import { useQuery } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import { useProfilesOpen, usePmReaderSwitches } from "@/lib/auth/AuthProvider";
import { entriesOfV2, MIN_QUERY, suggestionsOfV2, type Entry } from "./model";
import { useSearchHits } from "./useSearchHits";

export interface ReaderAnswer {
  hits: Entry[] | undefined;
  /** «¿Quisiste decir…?»: only with no hit, only from v2. */
  suggestions: string[];
  pending: boolean;
  error: boolean;
  refetch: () => void;
}

export function useReaderSearch(term: string, enabled = true): ReaderAnswer {
  const q = term.trim();
  const on = enabled && q.length >= MIN_QUERY;
  const profiles = useProfilesOpen();
  const { competitionPage } = usePmReaderSwitches();
  const res = useQuery({
    queryKey: ["v1", "search-v2", q],
    queryFn: () => v1.searchV2(q),
    enabled: on,
    staleTime: 60_000,
    retry: false,
  });
  // the earlier search answers only while v2 cannot
  const older = useSearchHits(term, enabled && res.isError);
  const opened = { profiles, competitionPage };
  if (res.isError) {
    return {
      hits: older.hits,
      suggestions: [],
      pending: older.pending,
      error: older.error,
      refetch: older.refetch,
    };
  }
  const own = res.data ? entriesOfV2(res.data.data, opened) : undefined;
  const hits = !on ? [] : own;
  return {
    hits,
    suggestions: own && own.length === 0 ? suggestionsOfV2(res.data?.data) : [],
    pending: on && res.isPending,
    error: false,
    refetch: () => void res.refetch(),
  };
}
