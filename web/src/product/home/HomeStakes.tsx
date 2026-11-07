/**
 * «Partidos relevantes» and «Qué se juega» of the general layer (plan de Inicio, 3.1b), both from GET /home and both with the
 * reason chosen on the server (./homeReason.ts words it):
 *
 *   Partidos relevantes  the matches in play that have a reason - a final, a second leg and how the tie goes, a fight for the
 *                        title, Europe, relegation or promotion, a comeback -, four at most, by competition priority;
 *   Qué se juega         the matches not yet started in the next 36 hours with something at stake, one sentence each.
 *
 * A match with no reason is not shown, and a block with nothing to show stays out of the page: nothing is made up to fill it.
 * A load that fails is shown by «En vivo», which reads the same query; these two only draw what came.
 */
import { Link } from "@tanstack/react-router";
import { Compass, Scale } from "lucide-react";
import type { ReactNode } from "react";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { formatDate, formatTime, relativeDay } from "@/lib/time";
import type { Envelope } from "@/lib/api/v1/types";
import type { Home, HomeAtStake, HomeReason, HomeRelevant } from "@/lib/api/v1/types_product";
import { countryLabel } from "@/product/matches/country";
import { MatchClock } from "@/product/live/LiveCard";
import { Card, SectionHeader } from "@/product/shared/States";
import type { UseQueryResult } from "@tanstack/react-query";
import { reasonText } from "./homeReason";

type HomeQuery = UseQueryResult<Envelope<Home>>;

const ROW =
  "flex h-full items-start gap-3 px-4 py-3 transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none sm:px-5";

function Rows({ children, count, testId }: { children: ReactNode; count: number; testId: string }) {
  return (
    <Card className="mt-3 overflow-hidden">
      <ul className="grid grid-cols-1 gap-px bg-border/70 lg:grid-cols-2" data-testid={testId}>
        {children}
        {count % 2 === 1 ? <li aria-hidden className="hidden bg-card lg:block" /> : null}
      </ul>
    </Card>
  );
}

/** The sentences of a match's reasons: the ones the client can word, in the server's order. */
function Reasons({ reasons }: { reasons: HomeReason[] }) {
  const lines = reasons.map(reasonText).filter((x): x is string => x !== null);
  if (lines.length === 0) return null;
  return (
    <ul className="space-y-1 border-l-2 border-primary/30 pl-2.5" data-testid="reason-lines">
      {lines.map((line) => (
        <li key={line} className="text-xs leading-snug text-muted-foreground">
          {line}
        </li>
      ))}
    </ul>
  );
}

function RelevantRow({ x }: { x: HomeRelevant }) {
  const m = x.match;
  const score =
    m.goals_home !== null && m.goals_away !== null
      ? { home: m.goals_home, away: m.goals_away }
      : null;
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.fixture_id) }}
      data-testid="relevant-row"
      data-fixture={m.fixture_id}
      className={ROW}
    >
      <div className="w-14 shrink-0 pt-0.5">
        <MatchClock m={m} />
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <Matchup
          home={{ name: m.home.name, logo: m.home.logo_url }}
          away={{ name: m.away.name, logo: m.away.logo_url }}
          score={score}
          live
          size={18}
          strong={false}
          className="font-medium"
        />
        <CompetitionTag
          name={m.competition}
          logo={m.competition_logo}
          flag={m.competition_flag}
          country={countryLabel(m.country, m.country_code) ?? m.country}
          size={12}
          className="min-w-0 text-caption"
        />
        <Reasons reasons={x.reasons} />
      </div>
    </Link>
  );
}

/** Partidos relevantes: the matches in play with a reason; out of the page when there are none. */
export function RelevantNowBlock({ query }: { query: HomeQuery }) {
  const rows = query.data?.data?.relevant?.data ?? [];
  if (rows.length === 0) return null;
  return (
    <section data-testid="home-relevant">
      <SectionHeader
        title={t("home.relevant.title")}
        subtitle={t("home.relevant.subtitle")}
        icon={<Compass aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("common.seeAll"), to: "/live" }}
      />
      <Rows count={rows.length} testId="relevant-list">
        {rows.map((x) => (
          <li key={x.match.fixture_id} className="bg-card">
            <RelevantRow x={x} />
          </li>
        ))}
      </Rows>
    </section>
  );
}

/** «Hoy · 21:00», «Mañana · 03:00» or the date, then the hour. */
export function kickoffAt(at: string, now: number = Date.now()): string {
  const rel = relativeDay(at, undefined, now);
  const day =
    rel === "today"
      ? t("common.day.today")
      : rel === "tomorrow"
        ? t("common.day.tomorrow")
        : formatDate(at);
  return `${day} · ${formatTime(at)}`;
}

function AtStakeRow({ x, now }: { x: HomeAtStake; now: number }) {
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(x.fixture_id) }}
      data-testid="at-stake-row"
      data-fixture={x.fixture_id}
      className={ROW}
    >
      <div className="min-w-0 flex-1 space-y-1.5">
        <Matchup
          home={{ name: x.home.name, logo: x.home.logo_url }}
          away={{ name: x.away.name, logo: x.away.logo_url }}
          score={null}
          size={18}
          strong={false}
          className="font-medium"
        />
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-caption">
          <span className="numeric font-semibold text-foreground" data-testid="at-stake-kickoff">
            {kickoffAt(x.kickoff_at, now)}
          </span>
          <CompetitionTag
            name={x.competition.name}
            logo={x.competition.logo_url}
            flag={x.competition.flag_url}
            country={x.competition.country}
            size={12}
            className="min-w-0"
          />
        </div>
        <Reasons reasons={[x.reason]} />
      </div>
    </Link>
  );
}

/** Qué se juega: the matches of the next 36 hours with something at stake; out of the page when there are none. */
export function AtStakeBlock({ query, now }: { query: HomeQuery; now: number }) {
  const rows = query.data?.data?.at_stake?.data ?? [];
  if (rows.length === 0) return null;
  return (
    <section data-testid="home-at-stake">
      <SectionHeader
        title={t("home.atStake.title")}
        subtitle={t("home.atStake.subtitle")}
        icon={<Scale aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Rows count={rows.length} testId="at-stake-list">
        {rows.map((x) => (
          <li key={x.fixture_id} className="bg-card">
            <AtStakeRow x={x} now={now} />
          </li>
        ))}
      </Rows>
    </section>
  );
}
