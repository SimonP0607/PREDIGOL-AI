/**
 * Inicio's block 4, «Noticias» (plan UX, A10; section 24): the newest confirmed or probable news of the reader's matches of
 * today - until they pick their leagues (A13), the suggested ones -, each card with its seven elements and the way to the
 * match's Noticias. Like «Partidos relevantes» and «Qué se juega», the block only shows with content: nothing while it loads,
 * if it cannot be read, when the owner turned the news off or when there is none - the page never fills it with generic news.
 */
import { Link } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { ChevronRight, Newspaper } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatTime, getTimeZone } from "@/lib/time";
import type { Envelope } from "@/lib/api/v1/types";
import type { TodayNews } from "@/lib/api/v1/types_news";
import { NewsCard } from "@/product/news/NewsCard";
import { homeNews } from "@/product/news/news";
import { SectionHeader } from "@/product/shared/States";

export type TodayNewsQuery = UseQueryResult<Envelope<TodayNews | null>>;

export function NewsBlock({ query, now }: { query: TodayNewsQuery; now: number }) {
  const body = query.data;
  if (!body || body.status !== "ok" || !body.data) return null;
  const shown = homeNews(body.data.items, getTimeZone(), now);
  if (shown.length === 0) return null;
  return (
    <section data-testid="home-news">
      <SectionHeader
        title={t("home.news.title")}
        subtitle={t("home.news.subtitle")}
        icon={<Newspaper aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      {query.dataUpdatedAt ? (
        <p className="mt-1 text-caption text-subtle-foreground" data-testid="block-updated">
          {t("home.today.updated", { time: formatTime(query.dataUpdatedAt) })}
        </p>
      ) : null}
      <ul className="mt-3 grid grid-cols-1 gap-2.5 lg:grid-cols-2" data-testid="home-news-list">
        {shown.map(({ match, item }) => (
          <li key={`${match.fixture_id}-${item.id}`} className="min-w-0 space-y-1.5">
            <Link
              to="/matches/$fixtureId"
              params={{ fixtureId: String(match.fixture_id) }}
              hash="news"
              data-testid="home-news-match"
              className="tap-y flex min-w-0 items-center gap-1 text-caption font-medium text-muted-foreground hover:text-foreground"
            >
              <span className="min-w-0 truncate">
                {t("home.news.match", {
                  home: match.home,
                  away: match.away,
                  time: formatTime(match.kickoff_at),
                })}
              </span>
              <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0" />
            </Link>
            <NewsCard item={item} now={now} />
          </li>
        ))}
      </ul>
    </section>
  );
}
