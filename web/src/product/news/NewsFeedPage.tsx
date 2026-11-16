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
import { NewsCard, StatusChip } from "./NewsCard";
import { headline } from "./news";

const FILTERS: readonly (FeedStatus | "all")[] = [
  "all",
  "CONFIRMED",
  "PROBABLE",
  "CONTRADICTORY",
  "RUMOR",
];
/** The unified plan (FBI_NEWS_V2; decision D-04): no «Rumores» tab - each news item says its own confirmation level. */
const FILTERS_V2: readonly (FeedStatus | "all")[] = [
  "all",
  "CONFIRMED",
  "PROBABLE",
  "CONTRADICTORY",
];

/**
 * The front of maqueta 08 (UX-158), from the same feed: the lead - the newest high-relevance confirmed item, else the
 * newest -, «Última hora» (the next four by publication) and the rest; a rumour only in the rest. Pure: it orders what
 * the API gave.
 */
export function frontOf(items: readonly TodayNewsItem[]): {
  lead: TodayNewsItem | null;
  breaking: TodayNewsItem[];
  rest: TodayNewsItem[];
} {
  if (items.length === 0) return { lead: null, breaking: [], rest: [] };
  // a rumour is never put up front (decision D-04): it stays in «Más recientes», labelled as one
  const said = items.filter((e) => e.item.status !== "RUMOR");
  const lead =
    said.find((e) => e.item.relevance === "high" && e.item.status === "CONFIRMED") ??
    said[0] ??
    null;
  const others = items.filter((e) => e !== lead);
  const when = (e: TodayNewsItem) => Date.parse(e.item.published_at ?? e.item.seen_at) || 0;
  const breaking = others
    .filter((e) => e.item.status !== "RUMOR")
    .sort((a, b) => when(b) - when(a))
    .slice(0, 4);
  return { lead, breaking, rest: others.filter((e) => !breaking.includes(e)) };
}

function CompactItem({ entry }: { entry: TodayNewsItem }) {
  const { match, item } = entry;
  return (
    <li data-testid="news-front-item">
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(match.fixture_id) }}
        hash="news"
        className="block space-y-1 rounded-control px-1 py-2 hover:bg-elevated/60"
      >
        <StatusChip status={item.status} />
        <p className="text-sm font-semibold leading-snug">{headline(item)}</p>
        <p className="truncate text-caption text-muted-foreground">
          {match.home} – {match.away} · {formatKickoff(match.kickoff_at)}
        </p>
      </Link>
    </li>
  );
}

function FrontSection({
  title,
  items,
  testId,
}: {
  title: string;
  items: readonly TodayNewsItem[];
  testId: string;
}) {
  if (items.length === 0) return null;
  return (
    <section aria-label={title} data-testid={testId} className="card-surface rounded-card p-4">
      <h2 className="text-subheading">{title}</h2>
      <ul className="mt-2 divide-y divide-border">
        {items.map((e) => (
          <CompactItem key={`${e.match.fixture_id}-${e.item.id}`} entry={e} />
        ))}
      </ul>
    </section>
  );
}

function MineFront() {
  const q = useInfiniteQuery({
    queryKey: ["v1", "news-feed", true, "all"],
    queryFn: () => v1.newsFeed({ mine: true, status: null, offset: 0 }),
    initialPageParam: 0,
    getNextPageParam: () => undefined,
    refetchInterval: 5 * 60_000,
  });
  const feed = q.data?.pages[0]?.data;
  if (!feed || feed.suggested) return null;
  return (
    <FrontSection
      title={t("match.newsFeed.v2.mine")}
      items={feed.items.slice(0, 3)}
      testId="news-front-mine"
    />
  );
}

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

/** Maqueta 08's front: the lead large, «Última hora» and «Tus equipos» beside it on a desk, then «Más recientes». */
function NewsFront({ items }: { items: readonly TodayNewsItem[] }) {
  const front = frontOf(items);
  return (
    <div className="flex flex-col gap-4" data-testid="news-front">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:items-start">
        {front.lead ? (
          <section aria-label={t("match.newsFeed.v2.lead")} data-testid="news-front-lead">
            <h2 className="mb-2 text-overline text-primary">{t("match.newsFeed.v2.lead")}</h2>
            <ul>
              <FeedItem entry={front.lead} />
            </ul>
          </section>
        ) : null}
        <div className="flex min-w-0 flex-col gap-4">
          <FrontSection
            title={t("match.newsFeed.v2.breaking")}
            items={front.breaking}
            testId="news-front-breaking"
          />
          <MineFront />
        </div>
      </div>
      {front.rest.length > 0 ? (
        <section aria-labelledby="news-recent" className="space-y-3">
          <h2 id="news-recent" className="text-title">
            {t("match.newsFeed.v2.recent")}
          </h2>
          <ul className="grid gap-4 lg:grid-cols-2" data-testid="news-feed-list">
            {front.rest.map((entry) => (
              <FeedItem key={`${entry.match.fixture_id}-${entry.item.id}`} entry={entry} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

export function NewsFeedPage() {
  const open = useAuth().user?.news_feed === true;
  const v2 = useAuth().user?.news_v2 === true;
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
    <div
      className={cn("mx-auto flex w-full max-w-2xl flex-col gap-4", v2 && "lg:max-w-6xl")}
      data-testid="news-feed"
    >
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
            {(v2 ? FILTERS_V2 : FILTERS).map((f) => (
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
              {v2 && status === "all" && !mine ? (
                <NewsFront items={items} />
              ) : (
                <ul className="space-y-4" data-testid="news-feed-list">
                  {items.map((entry) => (
                    <FeedItem key={`${entry.match.fixture_id}-${entry.item.id}`} entry={entry} />
                  ))}
                </ul>
              )}
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
