/**
 * Every match of one local day. The API gives at most 200 rows a page, so a busy day is
 * read page by page (in parallel once the first page tells the total).
 */
import { v1 } from "@/lib/api/v1/client";
import type { DataStatus, MatchSummary } from "@/lib/api/v1/types";
import { dayBounds, todayKey } from "@/lib/time";

export const PAGE_SIZE = 200;
/** 2 000 matches in one day is far beyond any real calendar; past it the list is cut. */
const MAX_PAGES = 10;

export interface DayMatches {
  rows: MatchSummary[];
  total: number;
  status: DataStatus;
  generatedAt: string;
}

export async function fetchDay(from: string, to: string): Promise<DayMatches> {
  const base = {
    kickoff_after: from,
    kickoff_before: to,
    order: "asc" as const,
    limit: PAGE_SIZE,
  };
  const first = await v1.matches({ ...base, offset: 0 });
  const total = Math.max(first.meta.total ?? first.data.length, first.data.length);
  const offsets: number[] = [];
  if (first.data.length > 0) {
    for (
      let offset = first.data.length;
      offset < total && offsets.length < MAX_PAGES - 1;
      offset += PAGE_SIZE
    ) {
      offsets.push(offset);
    }
  }
  const rest = await Promise.all(offsets.map((offset) => v1.matches({ ...base, offset })));
  // Pages are ordered by (kick-off, id); a row that moved between two reads is kept once.
  const seen = new Set<number>();
  const rows: MatchSummary[] = [];
  for (const page of [first, ...rest]) {
    for (const m of page.data) {
      if (seen.has(m.id)) continue;
      seen.add(m.id);
      rows.push(m);
    }
  }
  return { rows, total, status: first.status, generatedAt: first.meta.generated_at };
}

/** The day is the reader's own: its bounds (and so the cache key) follow their time zone. */
export function dayMatchesQuery(day: string) {
  const { from, to } = dayBounds(day);
  return {
    queryKey: ["v1", "matches", "day", day, from, to] as const,
    queryFn: () => fetchDay(from, to),
    // Today keeps moving (kick-offs, results); other days are read once per visit.
    refetchInterval: day === todayKey() ? 2 * 60_000 : (false as const),
  };
}
