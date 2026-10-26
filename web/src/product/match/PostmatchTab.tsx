/**
 * Postpartido (plan UX, A9 - the base; B4 adds more): once the match is over, the result, what PrediGol's forecast said against
 * what happened, how PrediGol's picks of the match ended, and what happened put together in layers (plan F7: c1 to c6 - the
 * internal layers stay the owner's). Facts only: the forecast is not re-written after the fact and a pick is never re-priced.
 */
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookmarkCheck, ChevronRight, Scale } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { forecastVsResult } from "./postmatch";
import { KnowledgeBlock } from "./KnowledgeBlock";
import { PicksTab } from "./PicksTab";
import { ResultBlock } from "./SummaryTab";
import { Block, SectionNote } from "./ui";

function ForecastVsResult({ ctx }: { ctx: MatchCtx }) {
  const preview = usePreviewParam();
  const q = useQuery(live.matchForecast(ctx.fixtureId, preview));
  const score = ctx.score;
  const sides = { home: ctx.match.home.name, away: ctx.match.away.name };
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
    const market =
      q.data.data.forecast.status === "ok"
        ? q.data.data.forecast.data.find((m) => m.market === "1X2")
        : undefined;
    const read = market ? forecastVsResult(market, score, sides) : null;
    body =
      market && read ? (
        <div
          className="space-y-2"
          data-testid="forecast-vs-result"
          data-hit={read.hit ? "true" : "false"}
        >
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
          <p className="text-caption text-subtle-foreground">
            {t("match.postmatch.said", { date: formatDateTime(market.known_at) })}
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
  return (
    <div
      className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]"
      data-testid="postmatch"
    >
      <div className="min-w-0 space-y-4">
        <ResultBlock ctx={ctx} />
        <ForecastVsResult ctx={ctx} />
        {/* What happened, put together once the provider stopped changing it (plan F7). */}
        <KnowledgeBlock ctx={ctx} />
      </div>
      <div className="min-w-0 space-y-4">
        <PicksTab ctx={ctx} />
        <MyPicksLink />
      </div>
    </div>
  );
}
