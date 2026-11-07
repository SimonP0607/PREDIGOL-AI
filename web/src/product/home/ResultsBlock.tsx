/**
 * «Últimos resultados» (plan de Inicio, 3.1), the last block of the general layer: the matches that ended in the last 24 hours,
 * the most recent first, six at most - chosen by the server (GET /home), the same for everyone. Each row says when it was
 * played («Hoy · 18:00», «Ayer · 21:30»), who against whom with the score, the competition and how it ended («Final», «Final
 * (prór.)», «Final (pen.)» and the shoot-out), and opens the match on its Postpartido. A refresh that fails keeps the rows
 * with a small notice (plan de Inicio, 1.4); a day without results says so.
 */
import { Link } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { History } from "lucide-react";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import type { Envelope } from "@/lib/api/v1/types";
import type { Home, HomeResult } from "@/lib/api/v1/types_product";
import { formatDate, formatTime, relativeDay } from "@/lib/time";
import { Card, ErrorState, SectionHeader, SkeletonBlock, StaleNote } from "@/product/shared/States";

export type HomeQuery = UseQueryResult<Envelope<Home>>;

/** «Hoy», «Ayer» or «sáb 4 oct», then the hour: «Hoy · 18:00». */
export function playedAt(at: string, now: number = Date.now()): string {
  const rel = relativeDay(at, undefined, now);
  const day =
    rel === "today"
      ? t("common.day.today")
      : rel === "yesterday"
        ? t("common.day.yesterday")
        : formatDate(at);
  return `${day} · ${formatTime(at)}`;
}

function ResultRow({ r, now }: { r: HomeResult; now: number }) {
  const pens =
    r.pens_home != null && r.pens_away != null ? { home: r.pens_home, away: r.pens_away } : null;
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(r.fixture_id) }}
      hash="postmatch"
      data-testid="today-row"
      data-fixture={r.fixture_id}
      className="flex h-full items-start gap-3 px-4 py-3 transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none sm:px-5"
    >
      <div className="w-14 shrink-0 pt-0.5">
        <span className="flex flex-col leading-tight">
          <span className="text-xs font-medium text-muted-foreground">
            {t(`matches.clock.${r.status}`)}
          </span>
          {pens ? (
            <span className="numeric text-micro text-subtle-foreground">
              {t("matches.row.pens", pens)}
            </span>
          ) : null}
        </span>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <Matchup
          home={{ name: r.home.name, logo: r.home.logo_url }}
          away={{ name: r.away.name, logo: r.away.logo_url }}
          score={{ home: r.goals_home, away: r.goals_away }}
          size={18}
          strong={false}
          className="font-medium"
        />
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-caption">
          <CompetitionTag
            name={r.competition.name}
            logo={r.competition.logo_url}
            flag={r.competition.flag_url}
            country={r.competition.country}
            size={12}
            className="min-w-0"
          />
          <span className="numeric text-muted-foreground" data-testid="result-played-at">
            {playedAt(r.kickoff_at, now)}
          </span>
        </div>
      </div>
    </Link>
  );
}

export function ResultsBlock({ query, now }: { query: HomeQuery; now: number }) {
  const home = query.data?.data ?? null;
  const rows = home?.results?.data ?? [];
  let body;
  if (query.isPending) {
    body = (
      <div aria-busy="true" aria-label={t("common.loading")} className="mt-3 space-y-px">
        {[0, 1].map((i) => (
          <SkeletonBlock
            key={i}
            className="h-[4.5rem] rounded-none first:rounded-t-xl last:rounded-b-xl"
          />
        ))}
      </div>
    );
  } else if (!home) {
    body = (
      <Card className="mt-3">
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  } else if (rows.length === 0) {
    body = (
      <p
        data-empty-state
        data-testid="results-empty"
        className="mt-3 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
      >
        {t("home.results.empty")}
      </p>
    );
  } else {
    body = (
      <Card className="mt-3 overflow-hidden">
        <ul
          className="grid grid-cols-1 gap-px bg-border/70 lg:grid-cols-2"
          data-testid="results-list"
        >
          {rows.map((r) => (
            <li key={r.fixture_id} className="bg-card">
              <ResultRow r={r} now={now} />
            </li>
          ))}
          {rows.length % 2 === 1 ? <li aria-hidden className="hidden bg-card lg:block" /> : null}
        </ul>
      </Card>
    );
  }
  return (
    <section data-testid="home-results" data-guide="home-results">
      <SectionHeader
        title={t("home.results.title")}
        subtitle={t("home.results.subtitle")}
        icon={<History aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      {query.isError && home ? (
        <StaleNote className="mt-1" onRetry={() => void query.refetch()} />
      ) : null}
      {body}
    </section>
  );
}
