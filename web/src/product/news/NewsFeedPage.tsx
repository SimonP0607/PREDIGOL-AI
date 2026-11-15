/**
 * Noticias as a section (plan maestro UX/UI 2026, decision 2; sheets N01 to N03): the news the matches already show, of
 * the matches not yet over, newest first - each with its match, its sources and how certain it is. The filters are the
 * status (confirmed, probable, contradictory, rumour) and «Solo lo que sigo». Read only: GET /news, behind FBI_NEWS_FEED.
 * Without items it says so: nothing is filled in.
 */
import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Newspaper } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { v1 } from "@/lib/api/v1/client";
import type { FeedStatus, TodayNewsItem } from "@/lib/api/v1/types_news";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatKickoff } from "@/lib/time";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, PageTitle, SkeletonCards } from "@/product/shared/States";
import { NewsCard } from "./NewsCard";

const FILTERS: readonly (FeedStatus | "all")[] = [
  "all",
  "CONFIRMED",
  "PROBABLE",
  "CONTRADICTORY",
  "RUMOR",
];

function FeedItem({ entry }: { entry: TodayNewsItem }) {
  const { match, item } = entry;
  return (
    <li data-testid="news-feed-item" data-fixture={match.fixture_id}>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(match.fixture_id) }}
        hash="news"
        data-testid="news-feed-match"
        className="tap-y relative mb-1.5 flex items-center gap-1.5 px-1 text-[0.8125rem] text-muted-foreground hover:text-foreground"
      >
        <span className="min-w-0 truncate">
          <span className="font-semibold text-foreground">
            {match.home} – {match.away}
          </span>
          {" · "}
          {match.competition} · {formatKickoff(match.kickoff_at)}
        </span>
        <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0" />
      </Link>
      <NewsCard item={item} />
    </li>
  );
}

export function NewsFeedPage() {
  const open = useAuth().user?.news_feed === true;
  const [status, setStatus] = useState<FeedStatus | "all">("all");
  const [mine, setMine] = useState(false);
  const q = useInfiniteQuery({
    queryKey: ["v1", "news-feed", mine, status],
    queryFn: ({ pageParam }) =>
      v1.newsFeed({ mine, status: status === "all" ? null : status, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.data?.next_offset ?? undefined,
    enabled: open,
    refetchInterval: 5 * 60_000,
  });
  const feed = q.data?.pages[0]?.data ?? null;
  const items = (q.data?.pages ?? []).flatMap((p) => p.data?.items ?? []);
  const counts = feed?.counts;
  const all = counts ? Object.values(counts).reduce((a, b) => a + b, 0) : null;
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4" data-testid="news-feed">
      <PageTitle title={t("match.newsFeed.title")} subtitle={t("match.newsFeed.subtitle")} />
      {!open ? (
        <EmptyState
          icon={<Newspaper aria-hidden className="h-6 w-6" />}
          title={t("match.newsFeed.closed")}
        />
      ) : (
        <>
          <div
            role="radiogroup"
            aria-label={t("match.newsFeed.filterLabel")}
            className="scroll-strip -mx-1 flex gap-2 px-1 py-1"
            data-testid="news-feed-filters"
          >
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                role="radio"
                aria-checked={status === f}
                onClick={() => setStatus(f)}
                data-testid={`news-feed-filter-${f}`}
                className={cn(
                  "tap-y relative inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 text-[0.8125rem] font-semibold leading-none transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  status === f
                    ? "border-primary/40 bg-primary-soft text-primary"
                    : "border-transparent bg-elevated text-foreground-soft hover:text-foreground",
                )}
              >
                {t(`match.newsFeed.filter.${f}`)}
                {counts ? (
                  <span className="numeric text-xs opacity-80">
                    {f === "all" ? all : counts[f]}
                  </span>
                ) : null}
              </button>
            ))}
          </div>
          <label className="flex min-h-11 items-center justify-between gap-4 px-1">
            <span className="text-sm font-medium">{t("match.newsFeed.mine")}</span>
            <Switch checked={mine} onCheckedChange={setMine} data-testid="news-feed-mine" />
          </label>
          {mine && feed?.suggested ? (
            <p className="px-1 text-[0.8125rem] text-muted-foreground">
              {t("match.newsFeed.mineSuggested")}
            </p>
          ) : null}
          {q.isPending ? (
            <SkeletonCards count={3} />
          ) : q.isError ? (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<Newspaper aria-hidden className="h-6 w-6" />}
              title={t(
                status === "all" && !mine ? "match.newsFeed.empty" : "match.newsFeed.emptyFilter",
              )}
              body={t("match.newsFeed.emptyBody")}
            />
          ) : (
            <>
              <p className="numeric px-1 text-[0.8125rem] text-muted-foreground" aria-live="polite">
                {t("match.newsFeed.count", { count: feed?.total ?? items.length })}
              </p>
              <ul className="space-y-4" data-testid="news-feed-list">
                {items.map((entry) => (
                  <FeedItem key={`${entry.match.fixture_id}-${entry.item.id}`} entry={entry} />
                ))}
              </ul>
              {q.hasNextPage ? (
                <button
                  type="button"
                  onClick={() => void q.fetchNextPage()}
                  disabled={q.isFetchingNextPage}
                  data-testid="news-feed-more"
                  className={buttonVariants({ variant: "secondary", block: true })}
                >
                  {t("match.newsFeed.more")}
                </button>
              ) : null}
            </>
          )}
        </>
      )}
    </div>
  );
}
