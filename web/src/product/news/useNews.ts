/** A match's news, loaded for the signed-in view (plan UX, A10): Noticias and the press's absences in Alineaciones share it. */
import { useQueries, useQuery } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { Envelope } from "@/lib/api/v1/types";
import type { MatchNews, NewsItem } from "@/lib/api/v1/types_news";

export type NewsLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry?: () => void }
  | { status: "success"; envelope: Envelope<MatchNews | null> };

export function useNews(fixtureId: string): NewsLoad {
  const q = useQuery(live.matchNews(fixtureId));
  if (q.isPending) return { status: "pending" };
  if (q.isError) return { status: "error", error: q.error, retry: () => void q.refetch() };
  return { status: "success", envelope: q.data };
}

/** A side's latest news (AP-P11): what the feed lists of its matches, newest first. */
export interface TeamNews {
  team: string;
  items: NewsItem[];
}

/** At most this many stories of each side: «las últimas», not the whole feed. */
export const TEAM_NEWS_LIMIT = 3;

/**
 * The latest news of each side, read only when `enabled` (the match has none of its own and the reader has the Noticias feed):
 * GET /news?team=, behind FBI_NEWS_FEED - an answer that is not there (404, not_available) is simply no news of that side, never
 * an error on the page. A story that is already the match's own is not shown twice.
 */
export function useTeamNews(
  sides: ReadonlyArray<{ id: number; name: string }>,
  enabled: boolean,
): TeamNews[] {
  return useQueries({
    queries: sides.map((s) => ({
      queryKey: ["v1", "news-feed", "team", s.id],
      queryFn: () => v1.newsFeed({ team: s.id }),
      enabled,
      retry: false,
      staleTime: 5 * 60_000,
    })),
    combine: (results) =>
      results.map((r, i) => {
        const feed = r.data?.status === "ok" ? r.data.data : null;
        const seen = new Set<string>();
        const items: NewsItem[] = [];
        for (const e of feed?.items ?? []) {
          if (seen.has(e.item.id)) continue;
          seen.add(e.item.id);
          items.push(e.item);
          if (items.length >= TEAM_NEWS_LIMIT) break;
        }
        return { team: sides[i]?.name ?? "", items };
      }),
  });
}
