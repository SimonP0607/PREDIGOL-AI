/**
 * The day's picks as PrediGol recorded them (GET /daily): up to five, chosen as their matches
 * came within 24 hours, frozen when chosen, kept after kick-off and settled after the match.
 * Never padded: a day with two picks shows two, a day with none says so.
 */
import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ArrowRight, Target, Trophy } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { formatDateLong, shiftDay } from "@/lib/time";
import type { Envelope } from "@/lib/api/v1/types";
import type { DailyBoard } from "@/lib/api/v1/types_records";
import {
  Card,
  EmptyState,
  ErrorState,
  SectionHeader,
  SkeletonBlock,
} from "@/product/shared/States";
import { EvaluationBadge } from "./Badges";
import { DailyItemCard } from "./DailyItemCard";

type BoardQuery = UseQueryResult<Envelope<DailyBoard>>;

/** The product day is a calendar day in the board's own zone (America/Bogota). */
function dayLabel(day: string, zone: string): string {
  return formatDateLong(`${day}T12:00:00Z`, zone);
}

export function EvaluationNote() {
  return (
    <div
      data-testid="evaluation-note"
      className="flex flex-wrap items-start gap-2 rounded-lg border border-info/30 bg-info-soft/60 px-3 py-2 text-xs text-info"
    >
      <EvaluationBadge />
      <span className="min-w-0 flex-1">{t("records.evaluation.body")}</span>
    </div>
  );
}

function Skeleton({ count }: { count: number }) {
  return (
    <div
      aria-busy="true"
      aria-label={t("common.loading")}
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
    >
      {Array.from({ length: count }, (_, i) => (
        <SkeletonBlock key={i} className="h-72" />
      ))}
    </div>
  );
}

export function DailySetBlock({
  query,
  variant = "page",
  title,
  nav,
}: {
  query: BoardQuery;
  variant?: "page" | "home";
  /** A title of its own (Home's "Ayer · aún por terminar"). */
  title?: string | undefined;
  /** The page's day navigation: the previous days' sets stay readable, never gone. */
  nav?: { day: string; today: string; onDay: (day: string) => void } | undefined;
}) {
  const board = query.data?.data;
  const items = board?.set?.items ?? [];
  const evaluation = board?.evaluation_mode ?? false;
  const reason = board?.reason ?? (evaluation ? "no_shadow_picks" : "no_qualified_picks");

  let body: ReactNode;
  if (query.isPending) {
    body = <Skeleton count={3} />;
  } else if (query.isError) {
    body = (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  } else if (items.length === 0) {
    body = (
      <Card>
        <EmptyState
          icon={<Trophy aria-hidden className="h-6 w-6" />}
          title={t(`records.daily.reason.${reason}`)}
          body={t("records.daily.emptyBody")}
        />
      </Card>
    );
  } else if (variant === "home") {
    body = (
      <ul
        aria-label={t("records.daily.list")}
        data-testid="daily-list"
        className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-1 [scrollbar-width:none] md:mx-0 md:grid md:grid-cols-2 md:gap-4 md:overflow-visible md:px-0 md:pb-0 xl:grid-cols-3 [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item) => (
          <li
            key={item.rank}
            className="w-[88%] max-w-[23rem] shrink-0 snap-start text-caption md:w-auto md:max-w-none"
          >
            <DailyItemCard item={item} compact evaluation={evaluation} />
          </li>
        ))}
        <li className="w-40 shrink-0 snap-start md:w-auto">
          <Link
            to="/picks"
            className="flex h-full min-h-[9rem] flex-col items-center justify-center gap-2.5 rounded-xl border border-dashed border-border-strong p-5 text-center text-sm font-medium text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-elevated text-primary">
              <ArrowRight aria-hidden className="h-5 w-5" />
            </span>
            {t("home.picks.allTile")}
          </Link>
        </li>
      </ul>
    );
  } else {
    body = (
      <>
        <div
          className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
          data-testid="daily-list"
        >
          {items.map((item) => (
            <DailyItemCard key={item.rank} item={item} evaluation={evaluation} />
          ))}
        </div>
        {items.length < 5 ? (
          <p className="text-caption text-muted-foreground">
            {t("records.daily.partial", { count: items.length })}
          </p>
        ) : null}
      </>
    );
  }

  return (
    <section
      className="space-y-3"
      data-testid="daily-set"
      data-evaluation={evaluation || undefined}
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <SectionHeader
          className="min-w-0"
          title={title ?? t("records.daily.title")}
          subtitle={
            board
              ? t("records.daily.subtitle", { date: dayLabel(board.day, board.timezone) })
              : undefined
          }
          icon={
            variant === "home" ? (
              <Target aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            ) : (
              <Trophy aria-hidden className="h-4 w-4 text-gold" />
            )
          }
          action={variant === "home" ? { label: t("home.picks.seeAll"), to: "/picks" } : undefined}
        />
        <div className="flex items-center gap-2">
          {items.length > 0 ? (
            <span
              className="numeric mb-0.5 text-caption text-muted-foreground"
              data-testid="daily-count"
            >
              {t("records.daily.count", { count: items.length })}
            </span>
          ) : null}
          {nav ? (
            <span className="inline-flex items-center gap-1" data-testid="daily-nav">
              <button
                type="button"
                onClick={() => nav.onDay(shiftDay(nav.day, -1))}
                className="rounded-md border border-border px-2 py-1 text-caption hover:bg-elevated"
              >
                ← {t("records.daily.previous")}
              </button>
              {nav.day !== nav.today ? (
                <>
                  <button
                    type="button"
                    onClick={() => nav.onDay(shiftDay(nav.day, 1))}
                    className="rounded-md border border-border px-2 py-1 text-caption hover:bg-elevated"
                  >
                    {t("records.daily.next")} →
                  </button>
                  <button
                    type="button"
                    onClick={() => nav.onDay(nav.today)}
                    className="rounded-md border border-primary/40 px-2 py-1 text-caption text-primary hover:bg-primary/10"
                  >
                    {t("records.daily.today")}
                  </button>
                </>
              ) : null}
            </span>
          ) : null}
        </div>
      </div>
      {evaluation ? <EvaluationNote /> : null}
      {body}
    </section>
  );
}
