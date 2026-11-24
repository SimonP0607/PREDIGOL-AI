/**
 * NOTICIAS, the Match Center's section (plan UX, A10; sections 25 and 27): what PrediGol Intelligence found and verified in
 * the press about the match, as cards with their seven elements - confirmed and probable first, then contradictions, rumours
 * and the outdated, each group named. No coverage is said with the plan's exact sentence; the owner having turned the news off
 * is said too, never hidden; a failure shows its reference and a retry. Reading only: no visit searches the web or calls an AI.
 * From IA-016 the header says when the match was last searched and how many pages were read, and an empty list tells «not searched yet»
 * from «searched, nothing found».
 */
import { MatrixNotes } from "@/product/shared/matrixModules";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { MatchStoriesView } from "./MatchStories";
import { stories } from "./storiesApi";
import { Segmented } from "@/components/ui/segmented";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { NewsItem } from "@/lib/api/v1/types_news";
import { ChevronRight, Newspaper } from "lucide-react";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "@/product/match/context";
import { NewsCard } from "./NewsCard";
import { byTeam, emptyText, groups, searchLine } from "./news";
import { useNews, useTeamNews, type NewsLoad, type TeamNews } from "./useNews";

function Frame({
  children,
  count,
  search,
}: {
  children: ReactNode;
  count?: number;
  search?: string | null;
}) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      data-testid="match-news"
      className="min-w-0 rounded-xl border border-border bg-card"
    >
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          <h2
            id={id}
            className="flex items-center gap-2 font-display text-[0.95rem] font-bold uppercase tracking-[0.08em]"
          >
            <Newspaper aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 break-words">{t("match.news.title")}</span>
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("match.news.note")}</p>
          {search ? (
            <p className="mt-0.5 text-caption text-subtle-foreground" data-testid="news-search">
              {search}
            </p>
          ) : null}
        </div>
        {count ? (
          <span className="shrink-0 text-caption text-subtle-foreground" data-testid="news-count">
            {t("match.news.count", { count })}
          </span>
        ) : null}
      </header>
      <div className="space-y-5 px-4 pb-4 pt-3">{children}</div>
    </section>
  );
}

/** The section from an answer of the API (apart from the query, so a test can render it from a fixture). */
/** The timeline by team (maqueta 15, UX-161): each side's news in the order it was known, with when. */
function ByTeam({ items, now }: { items: NewsItem[]; now?: number | undefined }) {
  return (
    <div className="space-y-5" data-testid="news-by-team">
      {byTeam(items).map((g) => (
        <section key={g.side} className="space-y-2.5" data-testid={`news-team-${g.side}`}>
          <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {g.side === "general"
              ? t("match.news.byTeam.general")
              : (g.team ?? t(`match.news.byTeam.${g.side}`))}
            <span className="numeric ml-1.5 text-subtle-foreground">{g.items.length}</span>
          </h3>
          <ol className="relative space-y-2.5 border-l border-border pl-4">
            {g.items.map((item) => (
              <li key={item.id} className="relative">
                <span
                  aria-hidden
                  className="absolute -left-[1.3rem] top-4 h-2 w-2 rounded-full bg-primary"
                />
                <NewsCard item={item} now={now} />
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

/** AP-P11 (a): the match has no news of its own - the latest of each side, with its date, never «no hay noticias» while they exist. */
function TeamLatest({ sides, now }: { sides: TeamNews[]; now?: number | undefined }) {
  return (
    <div className="space-y-4" data-testid="news-team-latest">
      <p className="text-sm text-muted-foreground" data-testid="news-team-latest-note">
        {t("match.news.teamLatest.note")}
      </p>
      {sides
        .filter((s) => s.items.length > 0)
        .map((s) => (
          <section key={s.team} className="space-y-2.5">
            <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {t("match.news.teamLatest.of", { team: s.team })}
            </h3>
            <div className="space-y-2.5">
              {s.items.map((item) => (
                <NewsCard key={item.id} item={item} now={now} />
              ))}
            </div>
          </section>
        ))}
    </div>
  );
}

export function NewsView({
  load,
  now,
  v2 = false,
  teamNews = [],
}: {
  load: NewsLoad;
  now?: number | undefined;
  /** The latest news of each side, shown when the match has none of its own (AP-P11). */
  teamNews?: TeamNews[];
  /** The unified plan's news (FBI_NEWS_V2): «Por certeza | Por equipo». */
  v2?: boolean;
}) {
  const [view, setView] = useState<"certainty" | "team">("certainty");
  if (load.status === "pending") {
    return (
      <Frame>
        <div aria-busy="true" aria-label={t("common.loading")} className="space-y-3">
          <SkeletonBlock className="h-24" />
          <SkeletonBlock className="h-24" />
        </div>
      </Frame>
    );
  }
  if (load.status === "error") {
    return (
      <Frame>
        <ErrorState error={load.error} onRetry={load.retry} className="py-5" />
      </Frame>
    );
  }
  const { envelope } = load;
  if (envelope.status === "not_available" || !envelope.data) {
    return (
      <Frame>
        <p
          className="text-sm text-muted-foreground"
          data-empty-state
          data-testid="news-unavailable"
        >
          {t("match.news.unavailable")}
        </p>
      </Frame>
    );
  }
  const items = envelope.data.items;
  const search = envelope.data.search;
  const searched = searchLine(search, now);
  if (!items.length && teamNews.some((s) => s.items.length > 0)) {
    return (
      <Frame search={searched}>
        <TeamLatest sides={teamNews} now={now} />
      </Frame>
    );
  }
  if (!items.length) {
    return (
      <Frame search={search?.searched === "yes" ? searched : null}>
        <p
          className="text-sm text-muted-foreground"
          data-empty-state
          data-testid="news-empty"
          data-searched={search?.searched ?? "unknown"}
        >
          {emptyText(search)}
        </p>
      </Frame>
    );
  }
  // The rumours and the outdated come last, labelled - folded away when there is something verified above them, so the
  // page opens on what is confirmed or probable; open when they are all there is (a page of folded groups reads as empty).
  const folded = items.some((i) => i.status !== "RUMOR" && i.status !== "OUTDATED");
  return (
    <Frame count={items.length} search={searched}>
      {v2 ? (
        <Segmented<"certainty" | "team">
          value={view}
          onChange={setView}
          label={t("match.news.byTeam.label")}
          testId="news-view"
          options={[
            { value: "certainty", label: t("match.news.byTeam.certainty") },
            { value: "team", label: t("match.news.byTeam.team") },
          ]}
        />
      ) : null}
      {v2 && view === "team" ? (
        <ByTeam items={items} now={now} />
      ) : (
        groups(items).map(({ group, items: shown }, i) => {
          const cards = (
            <>
              {group === "rumor" ? (
                <p
                  className="text-caption leading-snug text-subtle-foreground"
                  data-testid="news-rumor-note"
                >
                  {t("match.news.rumorNote")}
                </p>
              ) : null}
              <div className="space-y-2.5">
                {shown.map((item) => (
                  <NewsCard key={item.id} item={item} now={now} />
                ))}
              </div>
            </>
          );
          const title = (
            <>
              {t(`match.news.group.${group}`)}
              <span className="numeric ml-1.5 text-subtle-foreground">{shown.length}</span>
            </>
          );
          if (folded && (group === "rumor" || group === "outdated")) {
            return (
              <details
                key={`${group}-${i}`}
                className="group space-y-2.5"
                data-testid={`news-group-${group}`}
              >
                <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground [&::-webkit-details-marker]:hidden">
                  <ChevronRight
                    aria-hidden
                    className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90"
                  />
                  {title}
                </summary>
                <div className="space-y-2.5 pt-1">{cards}</div>
              </details>
            );
          }
          return (
            <section
              key={`${group}-${i}`}
              className="space-y-2.5"
              data-testid={`news-group-${group}`}
            >
              <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {title}
              </h3>
              {cards}
            </section>
          );
        })
      )}
    </Frame>
  );
}

/** The Noticias tab: counts as the reader opening the match's news (news_opened), once per match. */
export function NewsTab({ ctx }: { ctx: MatchCtx }) {
  const load = useNews(ctx.fixtureId);
  const counted = useRef<string | null>(null);
  useEffect(() => {
    if (load.status === "success" && counted.current !== ctx.fixtureId) {
      counted.current = ctx.fixtureId;
      track("news_opened", { match_id: Number(ctx.fixtureId) });
    }
  }, [load.status, ctx.fixtureId]);
  const user = useAuth().user;
  const v2 = user?.news_v2 === true;
  const empty =
    load.status === "success" &&
    load.envelope.status !== "not_available" &&
    !!load.envelope.data &&
    load.envelope.data.items.length === 0;
  const teamNews = useTeamNews(
    [
      { id: ctx.match.home.id, name: ctx.match.home.name },
      { id: ctx.match.away.id, name: ctx.match.away.name },
    ],
    empty && user?.news_feed === true,
  );
  // the unified stories (FBI_NEWS_V2, AP-N04): when the server has any for this match they lead the tab, the cards as they were below
  const storiesOn = user?.news_feed === true && v2;
  const storyQuery = useQuery({
    queryKey: ["v1", "stories", "match", ctx.fixtureId],
    queryFn: () => stories.match(ctx.fixtureId),
    enabled: storiesOn,
    retry: false,
  });
  const match = storyQuery.data?.data?.match;
  return (
    <div className="space-y-4">
      {/* PM-14-04 (FBI_MATRIX_NEWS, show or on): one note when the line-ups or the referee the cards lean on are not complete. */}
      <MatrixNotes module="news" fixtureId={ctx.fixtureId} />
      {storiesOn && match && "stories" in match ? (
        <MatchStoriesView
          data={match}
          teams={[
            { id: ctx.match.home.id, name: ctx.match.home.name },
            { id: ctx.match.away.id, name: ctx.match.away.name },
          ]}
        />
      ) : null}
      <NewsView load={load} v2={v2} teamNews={teamNews} />
    </div>
  );
}
