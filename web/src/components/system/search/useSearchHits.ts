/**
 * The one query behind every entity search - the console's palette and the readers' search (UX-153): `GET /search`, from
 * two characters, kept a minute. One cache key, so both read the same answer.
 */
import { useQuery } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
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
  return {
    hits: on ? res.data?.data : [],
    pending: on && res.isPending,
    error: on && res.isError,
    refetch: () => void res.refetch(),
  };
}
