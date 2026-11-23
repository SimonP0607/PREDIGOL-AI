/**
 * The one query behind every entity search - the console's palette and the readers' search (UX-153): `GET /search`, from
 * two characters, kept a minute. One cache key, so both read the same answer.
 */
import { useQueries, useQuery } from "@tanstack/react-query";
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
  const aliased = useQueries({
    queries: aliases.map((a) => ({
      queryKey: ["v1", "search", a],
      queryFn: () => v1.search(a),
      staleTime: 60_000,
    })),
  });
  const hits =
    on && res.data
      ? merge(
          res.data.data,
          aliased.map((a) => a.data?.data ?? []),
          aliases,
          (h) => `${h.type}:${h.id}`,
          (h) => (h.type === "team" ? h.label : ""),
        )
      : on
        ? undefined
        : [];
  return {
    hits,
    pending: on && (res.isPending || aliased.some((a) => a.isPending && !a.isError)),
    error: on && res.isError,
    refetch: () => void res.refetch(),
  };
}
