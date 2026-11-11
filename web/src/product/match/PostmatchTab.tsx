/**
 * Postpartido (plan UX, A9 - the base - and B4): once the match is over, the result; what PrediGol's forecast said against what
 * happened (the result, the goals at 2.5 and both teams to score); how what the reader saved ended, with its units; how each pick
 * PrediGol published ended and why - the match's own facts as the post-mortem found them, never what it judges; what happened put
 * together in layers (plan F7: c1 to c6 - the internal layers stay the owner's); and the news published once it had started.
 * Facts only: the forecast is not re-written after the fact and a pick is never re-priced.
 */
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookmarkCheck, ChevronRight, Newspaper, Scale } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { formatOdds } from "@/lib/i18n/format";
import { formatDateTime } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { PostmatchPick } from "@/lib/api/v1/types_postmatch";
import type { UserPick } from "@/lib/api/v1/types_records";
import { NewsCard } from "@/product/news/NewsCard";
import { useNews } from "@/product/news/useNews";
import { OriginLabel, ResultBadge, Units } from "@/product/records/Badges";
import { selectionLabel } from "@/product/shared/markets";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { marketTitle } from "./intelligence";
import {
  causeLines,
  causesEmptyText,
  chancesText,
  forecastMarkets,
  forecastVsResult,
  newsAfterKickoff,
  outcomeText,
  type Sides,
} from "./postmatch";
import { useUsefulMoment } from "@/product/feedback/moments";
import { KnowledgeBlock } from "./KnowledgeBlock";
import { PicksTab } from "./PicksTab";
import { ResultBlock } from "./SummaryTab";
import { Block, SectionNote } from "./ui";

function sidesOf(ctx: MatchCtx): Sides {
  return { home: ctx.match.home.name, away: ctx.match.away.name };
}

function ForecastVsResult({ ctx }: { ctx: MatchCtx }) {
  const preview = usePreviewParam();
  const q = useQuery(live.matchForecast(ctx.fixtureId, preview));
  const score = ctx.score;
  const sides = sidesOf(ctx);
  let body;
  if (!score) {
    body = <SectionNote>{t("match.postmatch.pending")}</SectionNote>;
  } else if (q.isPending) {
    body = <SkeletonBlock className="h-16" />;
  } else if (q.isError) {
    body = <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-4" />;
  } else if (q.data.status !== "ok" || !q.data.data) {
    // the owner has not let readers see the forecast (FBI_FORECAST_USERS=0): nothing to set against the result
    return null;
  } else {
    const markets =
      q.data.data.forecast.status === "ok" ? forecastMarkets(q.data.data.forecast.data) : [];
    const reads = markets.flatMap((market) => {
      const read = forecastVsResult(market, score, sides);
      return read ? [{ market, read }] : [];
    });
    body = reads.length ? (
      <div className="space-y-3">
        {reads.map(({ market, read }) => (
          <div
            key={market.market}
            className="space-y-1.5"
            data-testid="forecast-vs-result"
            data-market={market.market}
            data-hit={read.hit ? "true" : "false"}
          >
            <p className="text-caption font-semibold uppercase tracking-wider text-muted-foreground">
              {marketTitle(market.market, market.line)}
            </p>
            <p className="text-sm leading-relaxed">{read.line}</p>
            <p
              className={cn(
                "inline-flex rounded-full border px-2 py-0.5 text-caption font-semibold",
                read.hit
                  ? "border-positive/40 text-positive"
                  : "border-border-strong text-muted-foreground",
              )}
            >
              {read.hit ? t("match.postmatch.hit") : t("match.postmatch.miss")}
            </p>
          </div>
        ))}
        <p className="text-caption text-subtle-foreground">
          {t("match.postmatch.said", { date: formatDateTime(reads[0]?.market.known_at) })}
        </p>
      </div>
    ) : (
      <SectionNote>{t("match.postmatch.none")}</SectionNote>
    );
  }
  return (
    <Block title={t("match.postmatch.title")} icon={<Scale />}>
      {body}
    </Block>
  );
}

/** A saved pick's line: what, at what price, and how it ended - or that it waits for the official result. */
export function SavedOutcome({ pick, sides }: { pick: UserPick; sides: Sides }) {
  const label = selectionLabel({
    market_key: pick.market_key,
    selection: pick.selection,
    line: pick.line,
    home: sides.home,
    away: sides.away,
  });
  const price = pick.user_odds ?? pick.odds;
  return (
    <li
      className="space-y-1 border-t border-border/70 pt-2.5 first:border-t-0 first:pt-0"
      data-testid="postmatch-saved-pick"
      data-status={pick.status}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="min-w-0 break-words text-sm font-semibold">{label}</span>
        <ResultBadge status={pick.status} />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-muted-foreground">
        <OriginLabel origin={pick.origin === "predigol_pick" ? "predigol" : "mine"} />
        {price ? (
          <span className="numeric">
            {pick.user_odds
              ? t("match.postmatch.saved.yourPrice", { odds: formatOdds(pick.user_odds) })
              : t("match.postmatch.saved.price", { odds: formatOdds(price) })}
          </span>
        ) : null}
        {pick.status !== "PENDING" ? <Units value={pick.profit_units} /> : null}
      </div>
      {pick.status === "PENDING" ? (
        <p className="text-caption text-subtle-foreground">{t("match.postmatch.saved.pending")}</p>
      ) : pick.corrections?.length ? (
        <p className="text-caption text-subtle-foreground">
          {t("match.postmatch.saved.corrected")}
        </p>
      ) : null}
    </li>
  );
}

/**
 * Under a pick's card in the Postpartido: why it ended as it did - how it ended, the chances it had, and the facts of the match
 * behind it, each for it or against it; or that nothing out of the ordinary explains it, or that the analysis is not written yet.
 */
export function PublishedWhy({ pick, sides }: { pick: PostmatchPick; sides: Sides }) {
  const lines = causeLines(pick, sides);
  const empty = lines.length ? null : causesEmptyText(pick);
  return (
    <div
      className="space-y-1.5"
      data-testid="postmatch-why-pick"
      data-result={pick.result ?? "pending"}
      data-analysed={pick.analysed ? "true" : "false"}
    >
      <p className="text-caption font-semibold uppercase tracking-wider text-muted-foreground">
        {t("match.postmatch.why.cardTitle")}
      </p>
      <p className="text-sm leading-relaxed" data-testid="postmatch-why-outcome">
        {outcomeText(pick)} {chancesText(pick)}
      </p>
      {lines.length ? (
        <ul className="space-y-1" data-testid="postmatch-why-causes">
          {lines.map((line, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-sm leading-relaxed text-foreground/90"
            >
              {line.effect === "neutral" ? (
                <span
                  aria-hidden
                  className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground"
                />
              ) : (
                <span
                  className={cn(
                    "mt-0.5 shrink-0 rounded border px-1 text-micro font-semibold uppercase tracking-wider",
                    line.effect === "for"
                      ? "border-positive/40 text-positive"
                      : "border-negative/40 text-negative",
                  )}
                  data-testid="postmatch-why-effect"
                  data-effect={line.effect}
                >
                  {t(`match.postmatch.why.effect.${line.effect}`)}
                </span>
              )}
              <span className="min-w-0 break-words">{line.text}</span>
            </li>
          ))}
        </ul>
      ) : empty ? (
        <p className="text-caption text-subtle-foreground" data-testid="postmatch-why-empty">
          {empty}
        </p>
      ) : null}
    </div>
  );
}

/** What the reader saved on the match, each with its settlement - nothing while they saved nothing here. */
function SavedBlock({ saved, sides }: { saved: UserPick[]; sides: Sides }) {
  if (!saved.length) return null;
  return (
    <Block title={t("match.postmatch.saved.title")} icon={<BookmarkCheck />}>
      <p className="mb-2.5 text-caption text-muted-foreground">
        {t("match.postmatch.saved.intro")}
      </p>
      <ul className="space-y-2.5" data-testid="postmatch-saved">
        {saved.map((pick) => (
          <SavedOutcome key={pick.id} pick={pick} sides={sides} />
        ))}
      </ul>
    </Block>
  );
}

/** The news first published after the kick-off, when there are any (the rest stay in Noticias). */
function NewsAfter({ ctx }: { ctx: MatchCtx }) {
  const load = useNews(ctx.fixtureId);
  if (load.status !== "success" || load.envelope.status !== "ok" || !load.envelope.data)
    return null;
  const items = newsAfterKickoff(load.envelope.data.items, ctx.match.kickoff_at);
  if (!items.length) return null;
  return (
    <Block title={t("match.postmatch.news.title")} icon={<Newspaper />}>
      <p className="mb-2.5 text-caption text-muted-foreground">{t("match.postmatch.news.intro")}</p>
      <div className="space-y-2.5" data-testid="postmatch-news">
        {items.map((item) => (
          <NewsCard key={item.id} item={item} />
        ))}
      </div>
    </Block>
  );
}

function MyPicksLink() {
  return (
    <Link
      to="/my-picks"
      data-testid="postmatch-my-picks"
      className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-2 text-left transition-colors hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <span className="flex items-center gap-2 text-sm">
        <BookmarkCheck aria-hidden className="h-4 w-4 shrink-0 text-primary" />
        {t("match.postmatch.myPicks")}
      </span>
      <span className="flex shrink-0 items-center gap-1 text-xs font-semibold text-primary">
        {t("match.postmatch.myPicksAction")}
        <ChevronRight aria-hidden className="h-3.5 w-3.5" />
      </span>
    </Link>
  );
}

export function PostmatchTab({ ctx }: { ctx: MatchCtx }) {
  const preview = usePreviewParam();
  // a result seen: a useful moment, after which the monthly survey may come (plan UX, B6)
  useUsefulMoment("result_seen", ctx.phase === "finished");
  // GET /matches/{id}/postmatch: what the reader saved, and how and why each published pick ended (plan UX, B4). Nothing of it
  // while the owner keeps the after-match from readers (FBI_KNOWLEDGE_USERS=0): the base blocks say what there is.
  const q = useQuery(live.matchPostmatch(ctx.fixtureId, preview));
  const data = q.data?.status === "ok" ? q.data.data : null;
  const sides = sidesOf(ctx);
  const byPick = new Map((data?.published ?? []).map((p) => [p.pick_id, p]));
  const why = data
    ? (pickId: number) => {
        const pick = byPick.get(pickId);
        return pick ? <PublishedWhy pick={pick} sides={sides} /> : null;
      }
    : undefined;
  return (
    <div
      className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]"
      data-testid="postmatch"
    >
      <div className="min-w-0 space-y-4">
        <ResultBlock ctx={ctx} />
        {q.isPending ? (
          <SkeletonBlock className="h-24" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-4" />
        ) : data ? (
          <SavedBlock saved={data.saved} sides={sides} />
        ) : null}
        <ForecastVsResult ctx={ctx} />
        {/* What happened, put together once the provider stopped changing it (plan F7). */}
        <KnowledgeBlock ctx={ctx} />
      </div>
      <div className="min-w-0 space-y-4">
        <PicksTab ctx={ctx} why={why} />
        <NewsAfter ctx={ctx} />
        <MyPicksLink />
      </div>
    </div>
  );
}
