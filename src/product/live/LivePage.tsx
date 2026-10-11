/**
 * Live: every followed match being played, refreshed every 15 seconds. The matches we
 * know most about come first as full cards (the API already orders them richest first);
 * those with little more than a score follow as compact rows.
 *
 * REVIEW PREDIGOL, point 11: a team search and country, league and gender filters - many
 * matches are played at once - and, by default, the matches PrediGol has picks on first,
 * marked: what we want to stand out.
 */
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Clock, Globe2, RadioTower, RefreshCw, Target, Trophy, Users } from "lucide-react";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import { FacetPicker, SearchBox } from "@/product/matches/Filters";
import {
  NO_FILTERS,
  competitionKey,
  countryOf,
  inLiveFilters,
  picksFirst,
  type LiveFilters,
} from "./filters";
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

function PicksBadge({ count }: { count: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full border border-gold/50 bg-gold-soft px-2 py-0.5 text-[0.65rem] font-semibold text-gold-strong"
      data-testid="live-picks-badge"
    >
      <Target aria-hidden className="h-3 w-3" />
      {t("live.picksBadge", { count })}
    </span>
  );
}

export function LivePage() {
  const q = useQuery(live.liveBoard);
  const preview = usePreviewParam();
  const started = useQuery(live.startedPicks(preview));
  const now = useNow(15_000);
  const [filters, setFilters] = useState<LiveFilters>(NO_FILTERS);
  const all = q.data?.data.matches ?? NO_MATCHES;
  const summary = useMemo(() => boardSummary(all), [all]);
  // The matches PrediGol has a pre-match pick on (today's, as taken): first, and marked.
  const picks = useMemo(() => {
    const out = new Map<number, number>();
    for (const p of started.data?.data ?? [])
      out.set(p.fixture_id, (out.get(p.fixture_id) ?? 0) + 1);
    return out;
  }, [started.data]);
  const matches = useMemo(
    () => picksFirst(all, picks).filter((m) => inLiveFilters(m, filters, picks)),
    [all, picks, filters],
  );
  const countries = useMemo(() => {
    const by = new Map<string, number>();
    for (const m of all) by.set(countryOf(m), (by.get(countryOf(m)) ?? 0) + 1);
    return [...by.entries()]
      .map(([key, count]) => ({
        key,
        label: key === "World" ? t("live.filters.world") : key,
        count,
      }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [all]);
  const leagues = useMemo(() => {
    const by = new Map<string, { key: string; label: string; count: number }>();
    for (const m of all) {
      if (filters.country !== null && countryOf(m) !== filters.country) continue;
      const key = competitionKey(m);
      const known = by.get(key);
      if (known) known.count += 1;
      else
        by.set(key, {
          key,
          label: m.country ? `${m.competition} · ${m.country}` : m.competition,
          count: 1,
        });
    }
    return [...by.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [all, filters.country]);
  const filtered = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS);
  const withPicks = all.filter((m) => (picks.get(m.fixture_id) ?? 0) > 0).length;
  // Kept in the API's order (richest first), the matches with picks before the rest.
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
  } else if (all.length > 0 && matches.length === 0) {
    body = (
      <Card>
        <EmptyState
          icon={<RadioTower aria-hidden className="h-6 w-6" />}
          title={t("live.filters.emptyTitle")}
          body={t("live.filters.emptyBody")}
          action={
            <button
              type="button"
              onClick={() => setFilters(NO_FILTERS)}
              className="inline-flex rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium hover:bg-elevated"
            >
              {t("live.filters.clear")}
            </button>
          }
        />
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
              <div key={m.fixture_id} className="relative min-w-0">
                {picks.get(m.fixture_id) ? (
                  <div className="pointer-events-none absolute -top-2 right-3 z-10">
                    <PicksBadge count={picks.get(m.fixture_id) ?? 0} />
                  </div>
                ) : null}
                <LiveCard m={m} now={now} />
              </div>
            ))}
          </div>
        ) : null}

        {rows.length > 0 ? (
          <section aria-label={t("live.lessInfo")} className="space-y-2.5">
            <SectionHeader title={t("live.lessInfo")} subtitle={t("live.lessInfoHint")} />
            <Card as="div" className="overflow-hidden">
              <ul className="divide-y divide-border/60" data-testid="live-rows">
                {rows.map((m) => (
                  <li key={m.fixture_id} className="relative">
                    <BasicRow m={m} />
                    {picks.get(m.fixture_id) ? (
                      <div className="pointer-events-none absolute right-8 top-1/2 -translate-y-1/2">
                        <PicksBadge count={picks.get(m.fixture_id) ?? 0} />
                      </div>
                    ) : null}
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
      {all.length > 0 ? (
        <div className="space-y-2.5" data-testid="live-filters">
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
            <SearchBox
              value={filters.team}
              onChange={(team) => setFilters((f) => ({ ...f, team }))}
            />
            <FacetPicker<string>
              label={t("live.filters.country")}
              anyLabel={t("live.filters.allCountries")}
              value={filters.country}
              options={countries}
              onChange={(country) => setFilters((f) => ({ ...f, country, competition: null }))}
              icon={<Globe2 />}
              testId="live-country"
            />
            <FacetPicker<string>
              label={t("live.filters.league")}
              anyLabel={t("live.filters.allLeagues")}
              value={filters.competition}
              options={leagues}
              onChange={(competition) => setFilters((f) => ({ ...f, competition }))}
              icon={<Trophy />}
              testId="live-league"
            />
            <FacetPicker<"men" | "women">
              label={t("live.filters.gender")}
              anyLabel={t("live.filters.allGenders")}
              value={filters.gender}
              options={[
                { key: "men", label: t("live.filters.men") },
                { key: "women", label: t("live.filters.women") },
              ]}
              onChange={(gender) => setFilters((f) => ({ ...f, gender }))}
              icon={<Users />}
              testId="live-gender"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {withPicks > 0 ? (
              <button
                type="button"
                aria-pressed={filters.picksOnly}
                onClick={() => setFilters((f) => ({ ...f, picksOnly: !f.picksOnly }))}
                data-testid="live-picks-only"
                className={cn(
                  "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  filters.picksOnly
                    ? "border-gold/60 bg-gold-soft text-gold-strong"
                    : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
                )}
              >
                <Target aria-hidden className="h-3.5 w-3.5" />
                {t("live.filters.picksOnly", { count: withPicks })}
              </button>
            ) : null}
            {filtered ? (
              <button
                type="button"
                onClick={() => setFilters(NO_FILTERS)}
                className="text-xs font-medium text-primary hover:underline"
              >
                {t("live.filters.clear")}
              </button>
            ) : null}
            <span className="numeric ml-auto text-caption text-muted-foreground" aria-live="polite">
              {t("live.filters.showing", { shown: matches.length, total: all.length })}
            </span>
          </div>
        </div>
      ) : null}
      {body}
    </div>
  );
}
