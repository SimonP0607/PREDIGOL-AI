/**
 * Live: every followed match being played, refreshed every 15 seconds. The matches we
 * know most about come first as full cards (the API already orders them richest first);
 * those with little more than a score follow as compact rows.
 */
import { useMemo, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Clock, RadioTower, RefreshCw } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { LiveMatch } from "@/lib/api/v1/types_center";
import { t } from "@/lib/i18n";
import { formatRelative, formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { emptyReason } from "@/product/shared/markets";
import {
  Card,
  EmptyState,
  ErrorState,
  PageTitle,
  SectionHeader,
  SkeletonBlock,
} from "@/product/shared/States";
import { FixtureLine } from "@/product/matches/FixtureLine";
import { RowClock } from "@/product/matches/MatchRow";
import { liveLabel, phaseOf, shortStatus } from "@/product/matches/status";
import { LiveCard } from "./LiveCard";
import { boardSummary, levelOf } from "./model";
import { useNow } from "./useNow";

const NO_MATCHES: LiveMatch[] = [];

function BasicRow({ m }: { m: LiveMatch }) {
  const pre = phaseOf(shortStatus(m.status)) === "pre";
  const score =
    !pre && m.goals_home !== null && m.goals_away !== null
      ? { home: m.goals_home, away: m.goals_away }
      : null;
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.fixture_id) }}
      data-testid="live-row"
      className="flex min-h-[3.25rem] items-center gap-2 px-3 py-2.5 transition-colors hover:bg-elevated/60 focus-visible:bg-elevated focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring sm:min-h-11 sm:gap-3 sm:py-2"
    >
      <span className="w-[3.25rem] shrink-0 sm:w-14">
        {pre ? (
          <span className="numeric text-xs font-medium text-muted-foreground">
            {formatTime(m.kickoff_at)}
          </span>
        ) : (
          <RowClock label={liveLabel(m.status, m.elapsed, m.extra)} />
        )}
      </span>
      <FixtureLine
        home={{ name: m.home.name, logo: m.home.logo_url }}
        away={{ name: m.away.name, logo: m.away.logo_url }}
        score={score}
        live={!pre}
      />
      <span className="flex w-4 shrink-0 justify-end">
        {m.data_status === "stale" ? (
          <span title={t("live.stale")} className="text-subtle-foreground">
            <Clock aria-hidden className="h-3.5 w-3.5" />
            <span className="sr-only">{t("live.stale")}</span>
          </span>
        ) : null}
      </span>
    </Link>
  );
}

function BoardSkeleton() {
  return (
    <div
      className="grid gap-3 md:grid-cols-2 xl:grid-cols-3"
      aria-busy="true"
      aria-label={t("common.loading")}
    >
      {[0, 1, 2].map((i) => (
        <div key={i} className="space-y-4 rounded-xl border border-border bg-card p-4">
          <SkeletonBlock className="h-3.5 w-1/2" />
          <div className="flex items-center justify-between gap-3">
            <SkeletonBlock className="h-9 w-9 rounded-full" />
            <SkeletonBlock className="h-8 w-20" />
            <SkeletonBlock className="h-9 w-9 rounded-full" />
          </div>
          <SkeletonBlock className="h-16 w-full" />
          <SkeletonBlock className="h-14 w-full" />
        </div>
      ))}
    </div>
  );
}

export function LivePage() {
  const q = useQuery(live.liveBoard);
  const now = useNow(15_000);
  const matches = q.data?.data.matches ?? NO_MATCHES;
  const summary = useMemo(() => boardSummary(matches), [matches]);
  // Kept in the API's order: richest first.
  const cards = matches.filter((m) => levelOf(m) !== "basic");
  const rows = matches.filter((m) => levelOf(m) === "basic");

  const subtitle =
    matches.length > 0
      ? [
          t("live.inPlay", { count: summary.inPlay }),
          summary.starting > 0 ? t("live.starting", { count: summary.starting }) : null,
          summary.newest ? t("live.updated", { when: formatRelative(summary.newest, now) }) : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : undefined;

  let body: ReactNode;
  if (q.isPending) {
    body = <BoardSkeleton />;
  } else if (q.isError && !q.data) {
    body = (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  } else if (matches.length === 0) {
    body = (
      <Card>
        <EmptyState
          icon={<RadioTower aria-hidden className="h-6 w-6" />}
          title={emptyReason("no_live_matches")}
          body={t("live.emptyBody")}
          action={
            <Link
              to="/matches"
              className="inline-flex rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium hover:bg-elevated"
            >
              {t("live.seeMatches")}
            </Link>
          }
        />
      </Card>
    );
  } else {
    body = (
      <div className="space-y-6">
        {q.isError ? (
          <div
            role="status"
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground"
          >
            {t("live.refreshFailed")}
            <button
              type="button"
              onClick={() => void q.refetch()}
              className="font-medium text-primary hover:underline"
            >
              {t("common.retry")}
            </button>
          </div>
        ) : null}

        {cards.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="live-cards">
            {cards.map((m) => (
              <LiveCard key={m.fixture_id} m={m} now={now} />
            ))}
          </div>
        ) : null}

        {rows.length > 0 ? (
          <section aria-label={t("live.lessInfo")} className="space-y-2.5">
            <SectionHeader title={t("live.lessInfo")} subtitle={t("live.lessInfoHint")} />
            <Card as="div" className="overflow-hidden">
              <ul className="divide-y divide-border/60" data-testid="live-rows">
                {rows.map((m) => (
                  <li key={m.fixture_id}>
                    <BasicRow m={m} />
                  </li>
                ))}
              </ul>
            </Card>
          </section>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageTitle
        title={t("nav.live")}
        subtitle={subtitle}
        right={
          <span className="inline-flex items-center gap-1.5 text-caption text-subtle-foreground">
            <RefreshCw aria-hidden className={cn("h-3 w-3", q.isFetching && "animate-spin")} />
            {t("live.autoRefresh")}
          </span>
        }
      />
      {body}
    </div>
  );
}
