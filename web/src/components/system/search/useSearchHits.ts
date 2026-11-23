/**
 * The one query behind every entity search - the console's palette and the readers' search (UX-153): `GET /search`, from
 * two characters, kept a minute. One cache key, so both read the same answer.
 */
import { useQuery } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import { useCountryAliases } from "@/lib/i18n/useCountryAliases";
import type { SearchHit } from "@/lib/api/v1/types";
import { MIN_QUERY } from "./model";

export function useSearchHits(
  term: string,
  enabled = true,
): { hits: SearchHit[] | undefined; pending: boolean; error: boolean; refetch: () => void } {
  const q = term.trim();
  const on = enabled && q.length >= MIN_QUERY;
  const res = useQuery({
    queryKey: ["v1", "search", q],
    queryFn: () => v1.search(q),
    enabled: on,
    staleTime: 60_000,
  });
  // AP-B02: «España» also asks for «Spain»; the national team leads the list
  const { aliases, merge } = useCountryAliases(q, on);
  // one query for all the aliases (not one per alias: the first visit's JS does not carry `useQueries`)
  const aliased = useQuery({
    queryKey: ["v1", "search-aliased", ...aliases],
    queryFn: () => Promise.all(aliases.map((a) => v1.search(a))),
    enabled: aliases.length > 0,
    staleTime: 60_000,
  });
  const hits =
    on && res.data
      ? merge(
          res.data.data,
          (aliased.data ?? []).map((a) => a.data),
          aliases,
          (h) => `${h.type}:${h.id}`,
          (h) => (h.type === "team" ? h.label : ""),
        )
      : on
        ? undefined
        : [];
  return {
    hits,
    pending: on && (res.isPending || (aliases.length > 0 && aliased.isPending)),
    error: on && res.isError,
    refetch: () => void res.refetch(),
  };
}
