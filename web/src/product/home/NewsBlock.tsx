/**
 * Inicio's «Noticias» as a summary (plan UX, A10; plan de Inicio, 3.3): the server's best few - three in the general layer,
 * two for the reader's own teams and leagues («Para ti», `mine`) -, each card with its seven elements, the way to the match's
 * Noticias and, in «Para ti», why the match is theirs («Sigues a Nacional», «Tu liga»). «Confirmado» is the server's word: an
 * official source or two distinct outlets. A rumour, at most one, wears its «Rumor» chip like on the match's page. Like
 * «Partidos relevantes» and «Qué se juega», the block only shows with content: nothing while it loads, if it cannot be read,
 * when the owner turned the news off or when there is none - the page never fills it with generic news.
 */
import { Link } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { ChevronRight, Newspaper } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import type { Envelope } from "@/lib/api/v1/types";
import type { TodayNews } from "@/lib/api/v1/types_news";
import { WhyChip } from "@/product/favorites/WhyChip";
import { NewsCard } from "@/product/news/NewsCard";
import { homeNews } from "@/product/news/news";
import { SectionHeader } from "@/product/shared/States";

export type TodayNewsQuery = UseQueryResult<Envelope<TodayNews | null>>;

export function NewsBlock({
  query,
  now,
  mine = false,
}: {
  query: TodayNewsQuery;
  now: number;
  /** «Para ti»: the reader's own news (two). Otherwise the general layer's (three). */
  mine?: boolean;
}) {
  const body = query.data;
  if (!body || body.status !== "ok" || !body.data) return null;
  const shown = homeNews(body.data.items, mine ? 2 : 3);
  if (shown.length === 0) return null;
  // An API from before B2 says nothing: those were the suggested ones.
  const suggested = body.data.suggested ?? true;
  return (
    <section data-testid={mine ? "home-news-mine" : "home-news"}>
      <SectionHeader
        title={t("home.news.title")}
        subtitle={t(suggested ? "home.news.subtitle" : "home.news.subtitleMine")}
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
            <div className="flex min-w-0 items-center gap-2">
              <Link
                to="/matches/$fixtureId"
                params={{ fixtureId: String(match.fixture_id) }}
                hash="news"
                data-testid="home-news-match"
                className="tap-y relative flex min-w-0 items-center gap-1 text-caption font-medium text-muted-foreground hover:text-foreground"
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
              {!suggested && match.followed ? (
                <WhyChip
                  why={match.followed}
                  testId="home-news-why"
                  className="max-w-[45%] text-micro"
                />
              ) : null}
            </div>
            <NewsCard item={item} now={now} />
          </li>
        ))}
      </ul>
    </section>
  );
}
