/**
 * Inicio's blocks fed by GET /today (plan UX, A9 and A13; section 24): «Hoy en tus ligas» (1) and the reader's own «Qué se
 * juega» (5). «Partidos relevantes» and the general «Qué se juega» are GET /home's now (./HomeStakes). One board for every reader, cut in the reader's day and zone (./today.ts), with
 * the reader's own part on top: their leagues and teams - while they chose none, the ones suggested for Colombia, labelled
 * as such with the way to choose - and on each of their matches why it is theirs. Each block says when it was updated, and
 * the page reads it again when the reader comes back to it.
 *
 * A failure shows in the block that always shows (1) with its reference and a retry - never as an empty list; the block that
 * only shows with content (5) stays out until the board loads.
 */
import { Link } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { CalendarDays, ChevronRight, Flag, History, Pencil, Sparkles, Star } from "lucide-react";
import type { ReactNode } from "react";
import { CompetitionTag, Matchup, TeamLogo } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { formatDate, formatTime, getTimeZone, relativeDay, zoneName } from "@/lib/time";
import type { Envelope } from "@/lib/api/v1/types";
import type { Following, NextFixture, Today, TodayMatch } from "@/lib/api/v1/types_today";
import { factText } from "@/product/reading/text";
import { Card, ErrorState, SectionHeader, SkeletonBlock, StaleNote } from "@/product/shared/States";
import {
  TODAY_ROWS,
  contextAhead,
  followedOf,
  mineToday,
  nextOfFavourites,
  pickContext,
  suggestedView,
} from "./today";
import { TodayRow } from "./TodayRow";
import { namesText, type Why } from "./why";

/** Why a match of the reader's is on Inicio: «Sugerida» while their part is the suggested one, else the API's reason. */
function whyOf(m: TodayMatch, suggested: boolean): Why | null {
  const reason = followedOf(m);
  if (!reason) return null;
  return suggested ? { kind: "suggested" } : reason;
}

export type TodayQuery = UseQueryResult<Envelope<Today>>;

function Updated({ query, zone = false }: { query: TodayQuery; zone?: boolean }) {
  if (!query.dataUpdatedAt) return null;
  return (
    <>
      <p className="mt-1 text-caption text-subtle-foreground" data-testid="block-updated">
        {t("home.today.updated", { time: formatTime(query.dataUpdatedAt) })}
        {zone ? ` · ${t("home.today.zone", { zone: zoneName() })}` : ""}
      </p>
      {query.isError && query.data ? (
        <StaleNote className="mt-1" onRetry={() => void query.refetch()} />
      ) : null}
    </>
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

const CHIPS =
  "-mx-4 mt-2.5 flex gap-1.5 overflow-x-auto px-4 pb-0.5 [scrollbar-width:none] md:mx-0 md:flex-wrap md:px-0 [&::-webkit-scrollbar]:hidden";

/** The way to the reader's leagues and teams (the profile's «Tu fútbol»): «Elegir mis ligas» or «Cambiar». */
function ChooseLink({ chosen }: { chosen: boolean }) {
  return (
    <Link
      to="/profile"
      hash="football"
      data-testid="today-choose"
      className="tap-y relative mt-2 inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary hover:underline"
    >
      <Pencil aria-hidden className="h-3.5 w-3.5" />
      {chosen ? t("home.today.edit") : t("home.today.choose")}
    </Link>
  );
}

/** The reader's leagues and teams, named: what «tus ligas» means, on one line that scrolls. */
function MineChips({ following }: { following: Following }) {
  if (following.leagues.length + following.teams.length === 0) return null;
  return (
    <ul aria-label={t("home.today.mineLabel")} data-testid="mine-chips" className={CHIPS}>
      {following.leagues.map((c) => (
        <li
          key={`l${c.id}`}
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
      {following.teams.map((tm) => (
        <li
          key={`t${tm.id}`}
          className="flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-caption"
        >
          <span aria-hidden className="contents">
            <TeamLogo src={tm.logo_url} name={tm.name} size={12} />
          </span>
          {tm.name}
        </li>
      ))}
    </ul>
  );
}

/** The suggested leagues, named: what «sugeridas» means, on one line that scrolls. */
function SuggestedLeagues({ today }: { today: Today }) {
  if (today.suggested.length === 0) return null;
  return (
    <ul aria-label={t("home.today.subtitle")} data-testid="suggested-leagues" className={CHIPS}>
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
function AllMatches({ more, suggested }: { more: number; suggested: boolean }) {
  return (
    <Link
      to="/matches"
      data-testid="today-all"
      className="tap-y relative mt-2 inline-flex min-h-9 items-center gap-1 text-sm font-medium text-primary hover:underline"
    >
      {more > 0
        ? t(suggested ? "home.today.more" : "home.today.moreMine", { count: more })
        : t("home.today.seeAll")}
      <ChevronRight aria-hidden className="h-4 w-4" />
    </Link>
  );
}

function nextDay(at: string): string {
  const rel = relativeDay(at);
  if (rel === "today") return formatTime(at);
  if (rel === "tomorrow") return `${t("common.day.tomorrow")} · ${formatTime(at)}`;
  return `${formatDate(at)} · ${formatTime(at)}`;
}

/** A favourite's next match (beyond today's board too): when, who, where, and whose next it is. */
export function NextRow({ n }: { n: NextFixture }) {
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(n.fixture_id) }}
      data-testid="today-next-row"
      data-fixture={n.fixture_id}
      className="flex h-full items-start gap-3 px-4 py-3 transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none sm:px-5"
    >
      <CalendarDays aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-subtle-foreground" />
      <div className="min-w-0 flex-1 space-y-1.5">
        <Matchup
          home={{ name: n.home.name, logo: n.home.logo_url }}
          away={{ name: n.away.name, logo: n.away.logo_url }}
          score={null}
          size={18}
          strong={false}
          className="font-medium"
        />
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-caption">
          <span className="numeric font-semibold text-foreground">{nextDay(n.kickoff_at)}</span>
          <CompetitionTag
            name={n.competition.name}
            logo={n.competition.logo_url}
            flag={n.competition.flag_url}
            country={n.competition.country}
            size={12}
            className="min-w-0"
          />
          <span
            data-testid="today-next-of"
            className="flex min-w-0 max-w-full items-center gap-1 truncate rounded-full border border-primary/30 bg-primary/10 px-2 py-px font-medium text-primary"
          >
            <Star aria-hidden className="h-3 w-3 shrink-0" />
            {t("home.today.nextOf", { name: namesText(n.followed.names) })}
          </span>
        </div>
      </div>
    </Link>
  );
}

/** 1 · Hoy en tus ligas: today's matches still to finish, in play first; when there are none, why and what comes next. */
export function TodayBlock({
  query,
  now,
  suggestion = null,
  choose = true,
}: {
  query: TodayQuery;
  now: number;
  /** One league or team to add, with its reason (plan UX, B2: the page's SuggestionCard). */
  suggestion?: ReactNode;
  /** The way to choose the leagues - off where the page already has one (the layer's «Cambiar favoritos», the prompt). */
  choose?: boolean;
}) {
  const today = query.data?.data ?? null;
  const suggested = today ? suggestedView(today) : true;
  let body: ReactNode;
  if (query.isPending) body = <Pending rows={4} />;
  else if (!today) body = <Failed query={query} />;
  else {
    const { rows, playedToday, next } = mineToday(today.matches.data, getTimeZone(), now);
    if (rows.length > 0) {
      const shown = rows.slice(0, TODAY_ROWS);
      const more = rows.length - shown.length;
      body = (
        <>
          <Rows count={shown.length} testId="today-list">
            {shown.map((m) => (
              <li key={m.fixture_id} className="bg-card">
                <TodayRow m={m} now={now} why={whyOf(m, suggested)} />
              </li>
            ))}
          </Rows>
          <AllMatches more={more} suggested={suggested} />
          {shown.some((m) => m.forecast) ? (
            <p className="mt-2 text-caption text-subtle-foreground" data-testid="forecast-note">
              {t("home.today.forecastNote")}
            </p>
          ) : null}
        </>
      );
    } else {
      // The next match of each favourite (the API looks 120 days ahead); an API from before A13: the board's own.
      const ahead = today.following ? nextOfFavourites(today, now) : [];
      const played = suggested ? "home.today.played" : "home.today.playedMine";
      body = (
        <>
          <Note testId="today-empty">
            {playedToday > 0
              ? t(played, { count: playedToday })
              : t(suggested ? "home.today.empty" : "home.today.emptyMine")}
          </Note>
          {ahead.length > 0 ? (
            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {t(suggested ? "home.today.next" : "home.today.nextMine")}
              </h3>
              <Rows count={ahead.length} testId="today-next">
                {ahead.map((n) => (
                  <li key={n.fixture_id} className="bg-card">
                    <NextRow n={n} />
                  </li>
                ))}
              </Rows>
            </div>
          ) : next.length > 0 ? (
            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {t(suggested ? "home.today.next" : "home.today.nextMine")}
              </h3>
              <Rows count={next.length} testId="today-next">
                {next.map((m) => (
                  <li key={m.fixture_id} className="bg-card">
                    <TodayRow m={m} now={now} why={whyOf(m, suggested)} />
                  </li>
                ))}
              </Rows>
            </div>
          ) : null}
          <AllMatches more={0} suggested={suggested} />
        </>
      );
    }
  }
  // The personalisation switched off (FBI_PERSONALIZATION=0): the common view, without the way to choose.
  const personal = today?.following?.personalization ?? false;
  return (
    <section
      data-testid="home-today"
      data-guide="home-today"
      data-view={suggested ? "suggested" : "mine"}
    >
      <SectionHeader
        title={t(suggested ? "home.today.title" : "home.today.titleMine")}
        subtitle={t(suggested ? "home.today.subtitle" : "home.today.subtitleMine")}
        icon={<Sparkles aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Updated query={query} zone />
      {today ? (
        suggested || !today.following ? (
          <SuggestedLeagues today={today} />
        ) : (
          <MineChips following={today.following} />
        )
      ) : null}
      {today && personal && choose ? <ChooseLink chosen={!suggested} /> : null}
      {today && personal ? suggestion : null}
      {body}
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

/** 5 · Qué se juega: the table or the tie, the rest and the next match of the reader's next matches. */
export function ContextBlock({ query, now }: { query: TodayQuery; now: number }) {
  const today = query.data?.data;
  if (!today) return null;
  const suggested = suggestedView(today);
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
        subtitle={t(suggested ? "home.context.subtitle" : "home.context.subtitleMine")}
        icon={<Flag aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Updated query={query} />
      <Rows count={rows.length} testId="context-list">
        {rows.map((m) => (
          <li key={m.fixture_id} className="bg-card">
            <TodayRow
              m={m}
              now={now}
              why={whyOf(m, suggested)}
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
