/**
 * A match in play, as much as we know of it: competition, minute, score, the goals and
 * red cards, a few statistics side by side and the main in-play prices. The whole card
 * opens the match; the data meter in the corner opens its own small list.
 */
import { Link } from "@tanstack/react-router";
import { Clock, Lock, RectangleVertical, Volleyball } from "lucide-react";
import type { LiveMatch, LiveQuote, LiveTeam } from "@/lib/api/v1/types_center";
import { CompetitionTag, TeamLogo } from "@/components/football/Logos";
import { t, translateOr } from "@/lib/i18n";
import { fmtInt, fmtOdds, fmtPct } from "@/lib/i18n/format";
import { formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Freshness, LiveMinute } from "@/product/shared/Bits";
import { marketShort, selectionLabel } from "@/product/shared/markets";
import { minuteText, phaseOf, shortStatus } from "@/product/matches/status";
import { Completeness } from "./Completeness";
import {
  X12,
  homeShare,
  keyEvents,
  latestEvents,
  liveOdds,
  quoteFreshness,
  statRows,
  type KeyEvent,
  type LiveOdds,
  type StatKey,
  type StatRow,
} from "./model";

/** The shared live pill (67', Descanso, Penales...) and a quiet "Por empezar" before kick-off. */
function MatchClock({ m, className }: { m: LiveMatch; className?: string | undefined }) {
  const short = shortStatus(m.status);
  const phase = phaseOf(short);
  if (phase === "pre" || phase === "over") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-md border border-border-strong bg-elevated px-1.5 py-0.5 text-xs font-medium text-muted-foreground",
          className,
        )}
      >
        <Clock aria-hidden className="h-3 w-3" />
        {phase === "pre" ? t("live.aboutToStart") : t("matches.clock.FT")}
      </span>
    );
  }
  if (short === "HT") return <LiveMinute status="HT" elapsed={null} className={className} />;
  if (phase === "pause" || phase === "pens" || phase === "stopped") {
    // No minute for a break: the pill says what is happening instead.
    const label = translateOr(`live.clock.${short}`, t("common.status.live"));
    return <LiveMinute status={label} elapsed={null} className={className} />;
  }
  return (
    <LiveMinute
      status={phase === "play" ? short : "LIVE"}
      elapsed={m.elapsed !== null && m.elapsed > 0 ? m.elapsed : null}
      extra={m.extra}
      className={className}
    />
  );
}

function TeamBlock({ team }: { team: LiveTeam }) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-1.5 text-center">
      <TeamLogo src={team.logo_url} name={team.name} size={36} />
      <span className="line-clamp-2 text-sm font-semibold leading-tight">{team.name}</span>
    </div>
  );
}

function EventIcon({ kind }: { kind: KeyEvent["kind"] }) {
  if (kind === "red_card") {
    return (
      <>
        <RectangleVertical aria-hidden className="h-3 w-3 shrink-0 fill-negative text-negative" />
        <span className="sr-only">{t("live.events.redCard")}</span>
      </>
    );
  }
  return (
    <>
      <Volleyball
        aria-hidden
        className={cn(
          "h-3 w-3 shrink-0",
          kind === "own_goal" ? "text-negative" : "text-foreground",
        )}
      />
      <span className="sr-only">
        {kind === "own_goal" ? t("live.events.ownGoalLong") : t("live.events.goal")}
      </span>
    </>
  );
}

function EventItem({ e, end }: { e: KeyEvent; end: boolean }) {
  const suffix =
    e.kind === "own_goal"
      ? ` (${t("live.events.ownGoal")})`
      : e.kind === "penalty"
        ? ` (${t("live.events.penalty")})`
        : "";
  return (
    <li
      className={cn(
        "flex min-w-0 items-center gap-1.5 text-caption",
        end && "flex-row-reverse text-right",
      )}
    >
      <EventIcon kind={e.kind} />
      <span className="numeric shrink-0 text-muted-foreground">
        {minuteText(e.minute, e.extra) ?? `${e.minute}'`}
      </span>
      <span className="truncate text-foreground/90">
        {e.player ?? t("live.events.unknownPlayer")}
        {suffix}
      </span>
    </li>
  );
}

function Events({ m }: { m: LiveMatch }) {
  const { shown, hidden } = latestEvents(keyEvents(m.events));
  if (shown.length === 0) return null;
  const home = shown.filter((e) => e.side === "home");
  const away = shown.filter((e) => e.side === "away");
  return (
    <div className="px-4 pb-3">
      <div className="grid grid-cols-2 gap-x-3 border-t border-border/60 pt-2.5">
        <ul className="min-w-0 space-y-1" aria-label={m.home.name}>
          {home.map((e) => (
            <EventItem key={e.seq} e={e} end={false} />
          ))}
        </ul>
        <ul className="min-w-0 space-y-1" aria-label={m.away.name}>
          {away.map((e) => (
            <EventItem key={e.seq} e={e} end />
          ))}
        </ul>
      </div>
      {hidden > 0 ? (
        <p className="mt-1.5 text-center text-caption text-subtle-foreground">
          {t("live.events.more", { count: hidden })}
        </p>
      ) : null}
    </div>
  );
}

function statLabel(key: StatKey): string {
  switch (key) {
    case "possession":
      return t("live.stats.possession");
    case "shots":
      return t("live.stats.shots");
    case "shotsOnTarget":
      return t("live.stats.shotsOnTarget");
    case "corners":
      return t("live.stats.corners");
  }
}

function StatBar({ row }: { row: StatRow }) {
  const share = homeShare(row);
  const lead = row.home === row.away ? null : row.home > row.away ? "home" : "away";
  const fmt = (v: number) => (row.pct ? fmtPct(v / 100, 0) : fmtInt(v));
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-caption">
        <span
          className={cn(
            "numeric w-12 shrink-0 tabular-nums",
            lead === "home" ? "font-semibold text-foreground" : "text-muted-foreground",
          )}
        >
          {fmt(row.home)}
        </span>
        <span className="truncate text-muted-foreground">{statLabel(row.key)}</span>
        <span
          className={cn(
            "numeric w-12 shrink-0 text-right tabular-nums",
            lead === "away" ? "font-semibold text-foreground" : "text-muted-foreground",
          )}
        >
          {fmt(row.away)}
        </span>
      </div>
      {/* Each team's share of the total, growing out from the centre; the leader in green. */}
      <div aria-hidden className="mt-1 flex h-1.5 gap-1">
        <span className="flex flex-1 justify-end overflow-hidden rounded-full bg-elevated">
          <span
            className={cn(
              "h-full rounded-full",
              lead === "home" ? "bg-primary" : "bg-muted-foreground/45",
            )}
            style={{ width: `${row.home + row.away > 0 ? share * 100 : 0}%` }}
          />
        </span>
        <span className="flex flex-1 justify-start overflow-hidden rounded-full bg-elevated">
          <span
            className={cn(
              "h-full rounded-full",
              lead === "away" ? "bg-primary" : "bg-muted-foreground/45",
            )}
            style={{ width: `${row.home + row.away > 0 ? (1 - share) * 100 : 0}%` }}
          />
        </span>
      </div>
    </div>
  );
}

function Stats({ m }: { m: LiveMatch }) {
  const rows = statRows(m.statistics);
  if (rows.length === 0) return null;
  return (
    <div className="space-y-2 border-t border-border/60 px-4 py-3">
      {rows.map((row) => (
        <StatBar key={row.key} row={row} />
      ))}
    </div>
  );
}

function QuoteCell({ label, quote }: { label: string; quote: LiveQuote | null }) {
  const suspended = quote?.suspended === true;
  const missing = !quote || quote.odds === null;
  const note = suspended
    ? t("live.odds.suspended")
    : missing
      ? t("live.odds.unavailable")
      : undefined;
  return (
    <div
      title={note}
      className={cn(
        "flex min-w-0 items-center justify-between gap-1 rounded-md border border-border bg-elevated/50 px-2 py-1",
        (suspended || missing) && "opacity-60",
      )}
    >
      <span className="truncate text-caption text-muted-foreground">{label}</span>
      {suspended ? (
        <Lock aria-hidden className="h-3 w-3 shrink-0 text-muted-foreground" />
      ) : (
        <span className="numeric shrink-0 text-[0.8125rem] font-semibold tabular-nums">
          {missing ? "—" : fmtOdds(quote?.odds)}
        </span>
      )}
      {note ? <span className="sr-only">{note}</span> : null}
    </div>
  );
}

function Prices({ odds, now }: { odds: LiveOdds; now: number }) {
  if (!odds.x12 && !odds.ou) return null;
  return (
    <div className="border-t border-border/60 px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-label text-subtle-foreground">{t("live.odds.title")}</span>
        {/* The size is set here: cn() inside Freshness drops its own text-caption. */}
        <span className="text-caption">
          <Freshness at={odds.newest} level={quoteFreshness(odds.newest, now)} />
        </span>
      </div>
      <div className="space-y-1.5">
        {odds.x12 ? (
          <div className="grid grid-cols-[2.75rem_repeat(3,minmax(0,1fr))] items-center gap-1.5">
            <span className="text-caption text-muted-foreground">{marketShort("1X2")}</span>
            {odds.x12.map((q, i) => (
              <QuoteCell
                key={X12[i]}
                label={selectionLabel({ market_key: "1X2", selection: X12[i] ?? "" }, true)}
                quote={q}
              />
            ))}
          </div>
        ) : null}
        {odds.ou ? (
          <div className="grid grid-cols-[2.75rem_repeat(2,minmax(0,1fr))] items-center gap-1.5">
            <span className="text-caption text-muted-foreground">{marketShort("OU")}</span>
            <QuoteCell
              label={selectionLabel(
                { market_key: "OU", selection: "Over", line: odds.ou.line },
                true,
              )}
              quote={odds.ou.over}
            />
            <QuoteCell
              label={selectionLabel(
                { market_key: "OU", selection: "Under", line: odds.ou.line },
                true,
              )}
              quote={odds.ou.under}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function LiveCard({ m, now }: { m: LiveMatch; now: number }) {
  const phase = phaseOf(shortStatus(m.status));
  const hasScore = m.goals_home !== null && m.goals_away !== null;
  const odds = liveOdds(m.main_odds);
  return (
    <article
      className="relative flex h-full flex-col rounded-xl border border-border bg-card transition-colors hover:border-border-strong"
      data-testid="live-card"
    >
      <header className="flex min-h-12 items-center gap-2 pl-4 pr-2 pt-2">
        {/* The size is set here: cn() inside CompetitionTag drops its own text-caption. */}
        <div className="min-w-0 flex-1 text-xs">
          <CompetitionTag
            name={m.competition}
            logo={m.competition_logo}
            flag={m.competition_flag}
            country={m.country}
          />
        </div>
        {m.data_status === "stale" ? (
          <span className="inline-flex shrink-0 items-center gap-1 text-caption text-muted-foreground">
            <Clock aria-hidden className="h-3 w-3" />
            {t("live.stale")}
          </span>
        ) : null}
        {m.completeness ? <Completeness data={m.completeness} className="relative z-10" /> : null}
      </header>

      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(m.fixture_id) }}
        className="block px-4 pb-3 pt-2 after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring"
      >
        <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2">
          <TeamBlock team={m.home} />
          <div className="flex min-w-[5.5rem] flex-col items-center gap-2 pt-0.5">
            {phase === "pre" ? (
              <span className="numeric text-2xl font-semibold text-muted-foreground">
                {formatTime(m.kickoff_at)}
              </span>
            ) : (
              <span className="numeric flex items-center gap-2 text-3xl font-bold leading-none tabular-nums">
                <span>{hasScore ? m.goals_home : "–"}</span>
                <span aria-hidden className="text-xl font-medium text-subtle-foreground">
                  -
                </span>
                <span>{hasScore ? m.goals_away : "–"}</span>
              </span>
            )}
            <MatchClock m={m} />
          </div>
          <TeamBlock team={m.away} />
        </div>
      </Link>

      <div className="flex flex-1 flex-col">
        <Events m={m} />
        <Stats m={m} />
        <div className="mt-auto">
          <Prices odds={odds} now={now} />
        </div>
      </div>
    </article>
  );
}
