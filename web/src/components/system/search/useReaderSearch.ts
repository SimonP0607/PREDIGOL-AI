/**
 * The readers' search (AP-B07): `GET /search/v2` (C-10) in groups, from two characters, kept a minute. If v2 does not answer
 * (the route off, an error), the earlier `GET /search` answers instead, so the search never goes dark; going back is this hook
 * reading `useSearchHits` alone. «España» also asks for «Spain» (AP-B02) until C-10 1.1 carries the Spanish names.
 */
import { useQuery } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import { useProfilesOpen, usePmReaderSwitches } from "@/lib/auth/AuthProvider";
import { useCountryAliases } from "@/lib/i18n/useCountryAliases";
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
  const { aliases, merge } = useCountryAliases(q, on);
  const aliased = useQuery({
    queryKey: ["v1", "search-v2-aliased", ...aliases],
    queryFn: () => Promise.all(aliases.map((a) => v1.searchV2(a))),
    enabled: on && aliases.length > 0 && res.isSuccess,
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
  const hits = !on
    ? []
    : own
      ? merge(
          own,
          (aliased.data ?? []).map((a) => entriesOfV2(a.data, opened)),
          aliases,
          (h) => `${h.type}:${h.id}`,
          (h) => (h.type === "team" || h.type === "national_team" ? h.label : ""),
        )
      : undefined;
  return {
    hits,
    suggestions: own && own.length === 0 ? suggestionsOfV2(res.data?.data) : [],
    pending: on && (res.isPending || (aliases.length > 0 && aliased.isPending)),
    error: false,
    refetch: () => void res.refetch(),
  };
}
