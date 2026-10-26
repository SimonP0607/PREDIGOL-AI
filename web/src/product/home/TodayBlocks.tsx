/**
 * Inicio's blocks fed by GET /today (plan UX, A9; section 24): «Hoy en las ligas sugeridas» (1), «Partidos relevantes»
 * (3), «Qué se juega» (5) and «Resultados» (6). One board for every reader, cut in the reader's day and zone
 * (./today.ts); each block says when it was updated, and the page reads it again when the reader comes back to it.
 *
 * Until the reader picks their leagues (A13) the blocks follow the leagues suggested for Colombia, labelled as such, and
 * there is no «Elige tus ligas» button yet: nothing on the page offers what does not exist. A failure shows in the
 * blocks that always show (1 and 6) with its reference and a retry - never as an empty list; the two blocks that only
 * show with content (3 and 5) stay out until the board loads.
 */
import { Link } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { CalendarDays, ChevronRight, Compass, Flag, History, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { CompetitionTag } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { formatTime, getTimeZone, zoneName } from "@/lib/time";
import type { Envelope } from "@/lib/api/v1/types";
import type { Today, TodayMatch } from "@/lib/api/v1/types_today";
import { factText } from "@/product/reading/text";
import { Card, ErrorState, SectionHeader, SkeletonBlock } from "@/product/shared/States";
import {
  TODAY_ROWS,
  contextAhead,
  pickContext,
  recentResults,
  relevantToday,
  suggestedToday,
} from "./today";
import { TodayRow } from "./TodayRow";

export type TodayQuery = UseQueryResult<Envelope<Today>>;

function Updated({ query, zone = false }: { query: TodayQuery; zone?: boolean }) {
  if (!query.dataUpdatedAt) return null;
  return (
    <p className="mt-1 text-caption text-subtle-foreground" data-testid="block-updated">
      {t("home.today.updated", { time: formatTime(query.dataUpdatedAt) })}
      {zone ? ` · ${t("home.today.zone", { zone: zoneName() })}` : ""}
    </p>
  );
}

/** Rows with hairlines between them (and between the two columns from 1024 px). */
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

function Pending({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy="true" aria-label={t("common.loading")} className="mt-3 space-y-px">
      {Array.from({ length: rows }, (_, i) => (
        <SkeletonBlock
          key={i}
          className="h-[4.5rem] rounded-none first:rounded-t-xl last:rounded-b-xl"
        />
      ))}
    </div>
  );
}

function Failed({ query }: { query: TodayQuery }) {
  return (
    <Card className="mt-3">
      <ErrorState error={query.error} onRetry={() => void query.refetch()} />
    </Card>
  );
}

function Note({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p
      data-empty-state
      data-testid={testId}
      className="mt-3 flex items-start gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
    >
      <CalendarDays aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-subtle-foreground" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}

/** The suggested leagues, named: what «sugeridas» means, on one line that scrolls. */
function SuggestedLeagues({ today }: { today: Today }) {
  if (today.suggested.length === 0) return null;
  return (
    <ul
      aria-label={t("home.today.subtitle")}
      data-testid="suggested-leagues"
      className="-mx-4 mt-2.5 flex gap-1.5 overflow-x-auto px-4 pb-0.5 [scrollbar-width:none] md:mx-0 md:flex-wrap md:px-0 [&::-webkit-scrollbar]:hidden"
    >
      {today.suggested.map((c) => (
        <li
          key={c.id}
          className="shrink-0 rounded-full border border-border bg-card px-2.5 py-1 text-caption"
        >
          <CompetitionTag
            name={c.name}
            logo={c.logo_url}
            flag={c.flag_url}
            country={c.country}
            size={12}
          />
        </li>
      ))}
      {today.suggested_team ? (
        <li className="flex shrink-0 items-center gap-1 rounded-full border border-border bg-card px-2.5 py-1 text-caption text-muted-foreground">
          <Flag aria-hidden className="h-3 w-3" />
          {today.suggested_team}
        </li>
      ) : null}
    </ul>
  );
}

/** The way to every match of the day (Partidos), under the list: «Ver todos los partidos», or how many more there are. */
function AllMatches({ more }: { more: number }) {
  return (
    <Link
      to="/matches"
      data-testid="today-all"
      className="tap-y relative mt-2 inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary hover:underline"
    >
      {more > 0 ? t("home.today.more", { count: more }) : t("home.today.seeAll")}
      <ChevronRight aria-hidden className="h-4 w-4" />
    </Link>
  );
}

/** 1 · Hoy en las ligas sugeridas: today's matches still to finish, in play first; when there are none, why. */
export function TodayBlock({ query, now }: { query: TodayQuery; now: number }) {
  const today = query.data?.data ?? null;
  let body: ReactNode;
  if (query.isPending) body = <Pending rows={4} />;
  else if (query.isError || !today) body = <Failed query={query} />;
  else {
    const { rows, playedToday, next } = suggestedToday(today.matches.data, getTimeZone(), now);
    if (rows.length > 0) {
      const shown = rows.slice(0, TODAY_ROWS);
      const more = rows.length - shown.length;
      body = (
        <>
          <Rows count={shown.length} testId="today-list">
            {shown.map((m) => (
              <li key={m.fixture_id} className="bg-card">
                <TodayRow m={m} now={now} why />
              </li>
            ))}
          </Rows>
          <AllMatches more={more} />
          {shown.some((m) => m.forecast) ? (
            <p className="mt-2 text-caption text-subtle-foreground" data-testid="forecast-note">
              {t("home.today.forecastNote")}
            </p>
          ) : null}
        </>
      );
    } else {
      body = (
        <>
          <Note testId="today-empty">
            {playedToday > 0
              ? t("home.today.played", { count: playedToday })
              : t("home.today.empty")}
          </Note>
          {next.length > 0 ? (
            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {t("home.today.next")}
              </h3>
              <Rows count={next.length} testId="today-next">
                {next.map((m) => (
                  <li key={m.fixture_id} className="bg-card">
                    <TodayRow m={m} now={now} why />
                  </li>
                ))}
              </Rows>
            </div>
          ) : null}
          <AllMatches more={0} />
        </>
      );
    }
  }
  return (
    <section data-testid="home-today">
      <SectionHeader
        title={t("home.today.title")}
        subtitle={t("home.today.subtitle")}
        icon={<Sparkles aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Updated query={query} zone />
      {today ? <SuggestedLeagues today={today} /> : null}
      {body}
    </section>
  );
}

/** 3 · Partidos relevantes: from 3 to 5 of today's other matches with a reading; out of the page when there are none. */
export function RelevantBlock({ query, now }: { query: TodayQuery; now: number }) {
  const today = query.data?.data;
  if (!today) return null;
  const rows = relevantToday(today.matches.data, getTimeZone(), now);
  if (rows.length === 0) return null;
  return (
    <section data-testid="home-relevant">
      <SectionHeader
        title={t("home.relevant.title")}
        subtitle={t("home.relevant.subtitle")}
        icon={<Compass aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Updated query={query} />
      <Rows count={rows.length} testId="relevant-list">
        {rows.map((m) => (
          <li key={m.fixture_id} className="bg-card">
            <TodayRow m={m} now={now} />
          </li>
        ))}
      </Rows>
    </section>
  );
}

function ContextFacts({ m }: { m: TodayMatch }) {
  const known = m.context.filter((fact) => factText(fact) !== null);
  const lines = pickContext(known, m.headline);
  if (lines.length === 0) return null;
  return (
    <ul className="space-y-1 border-l-2 border-primary/30 pl-2.5" data-testid="context-facts">
      {lines.map((fact, i) => (
        <li
          key={`${fact.code}-${i}`}
          data-code={fact.code}
          data-ref={fact.ref}
          className="text-xs leading-snug text-foreground/85"
        >
          {factText(fact)}
        </li>
      ))}
    </ul>
  );
}

/** 5 · Qué se juega: the table or the tie, the rest and the next match of the next suggested matches. */
export function ContextBlock({ query, now }: { query: TodayQuery; now: number }) {
  const today = query.data?.data;
  if (!today) return null;
  const rows = contextAhead(today.matches.data, now).filter(
    (m) =>
      pickContext(
        m.context.filter((f) => factText(f) !== null),
        m.headline,
      ).length > 0,
  );
  if (rows.length === 0) return null;
  return (
    <section data-testid="home-context">
      <SectionHeader
        title={t("home.context.title")}
        subtitle={t("home.context.subtitle")}
        icon={<Flag aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Updated query={query} />
      <Rows count={rows.length} testId="context-list">
        {rows.map((m) => (
          <li key={m.fixture_id} className="bg-card">
            <TodayRow
              m={m}
              now={now}
              why
              reading={false}
              forecast={false}
              tab="analysis"
              extra={<ContextFacts m={m} />}
            />
          </li>
        ))}
      </Rows>
    </section>
  );
}

/** 6 · Resultados: the suggested leagues' results of the last 48 hours, each to its Postpartido. */
export function ResultsBlock({ query, now }: { query: TodayQuery; now: number }) {
  const today = query.data?.data ?? null;
  let body: ReactNode;
  if (query.isPending) body = <Pending rows={2} />;
  else if (query.isError || !today) body = <Failed query={query} />;
  else {
    const rows = recentResults(today.matches.data, now);
    body =
      rows.length === 0 ? (
        <Note testId="results-empty">{t("home.results.empty")}</Note>
      ) : (
        <Rows count={rows.length} testId="results-list">
          {rows.map((m) => (
            <li key={m.fixture_id} className="bg-card">
              <TodayRow m={m} now={now} reading={false} forecast={false} tab="postmatch" />
            </li>
          ))}
        </Rows>
      );
  }
  return (
    <section data-testid="home-results">
      <SectionHeader
        title={t("home.results.title")}
        subtitle={t("home.results.subtitle")}
        icon={<History aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Updated query={query} />
      {body}
    </section>
  );
}
