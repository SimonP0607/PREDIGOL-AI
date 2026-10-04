/** The match at a glance: competition, crests, score or kick-off, state and venue. */
import type { ReactNode } from "react";
import { CalendarDays, MapPin, UserRound } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { formatDate, formatDateLong, formatRelative, formatTime, relativeDay } from "@/lib/time";
import type { TeamRef } from "@/lib/api/v1/types";
import { CompetitionTag, TeamLogo } from "@/components/football/Logos";
import { Freshness, LiveMinute } from "@/product/shared/Bits";
import { Card } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import {
  ageLevel,
  capitalize,
  FINISHED_CODES,
  roundLabel,
  scorerName,
  scorers,
  type EventKind,
  type Goals,
} from "./model";

type Tone = "neutral" | "warning" | "negative";

const PILL_TONE: Record<Tone, string> = {
  neutral: "border-border-strong bg-elevated text-muted-foreground",
  warning: "border-warning/40 bg-warning-soft text-warning",
  negative: "border-negative/40 bg-negative-soft text-negative",
};

function StatePill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[0.7rem] font-semibold",
        PILL_TONE[tone],
      )}
    >
      {children}
    </span>
  );
}

function ScoreLine({ score, home, away }: { score: Goals | null; home: string; away: string }) {
  if (!score) {
    return (
      <p className="numeric text-4xl font-bold leading-none text-subtle-foreground sm:text-5xl">
        <span className="sr-only">{t("match.header.noScore")}</span>
        <span aria-hidden>–:–</span>
      </p>
    );
  }
  return (
    <p className="numeric flex items-center gap-2 text-4xl font-bold leading-none tabular-nums sm:gap-3 sm:text-5xl">
      <span className="sr-only">
        {t("match.header.scoreAria", { home, away, homeGoals: score.home, awayGoals: score.away })}
      </span>
      <span aria-hidden>{score.home}</span>
      <span aria-hidden className="text-subtle-foreground">
        –
      </span>
      <span aria-hidden>{score.away}</span>
    </p>
  );
}

function Center({ ctx }: { ctx: MatchCtx }) {
  const { match: m, phase, live, score } = ctx;
  const names = { home: m.home.name, away: m.away.name };

  if (phase === "scheduled") {
    const rel = relativeDay(m.kickoff_at);
    const day = rel ? t(`common.day.${rel}`) : formatDate(m.kickoff_at);
    const tbd = m.status_short === "TBD";
    const ms = Date.parse(m.kickoff_at) - Date.now();
    return (
      <div className="flex flex-col items-center gap-1.5 pt-1 text-center">
        <span className="text-label text-muted-foreground">{day}</span>
        <span className="numeric text-3xl font-semibold leading-none sm:text-[2.6rem]">
          {tbd ? "—" : formatTime(m.kickoff_at)}
        </span>
        {tbd ? (
          <StatePill>{t("match.header.timeTbd")}</StatePill>
        ) : ms > 0 && ms < 48 * 3_600_000 ? (
          <StatePill>
            {t("match.header.startsIn", { when: formatRelative(m.kickoff_at) })}
          </StatePill>
        ) : null}
      </div>
    );
  }

  if (phase === "postponed" || phase === "cancelled") {
    return (
      <div className="flex flex-col items-center gap-2 pt-1 text-center">
        <ScoreLine score={null} {...names} />
        <StatePill tone={phase === "postponed" ? "warning" : "negative"}>
          {t(`common.status.${phase}`)}
        </StatePill>
      </div>
    );
  }

  if (phase === "live") {
    const status = live?.status ?? m.status_short;
    return (
      <div className="flex flex-col items-center gap-2 pt-1 text-center">
        <ScoreLine score={score} {...names} />
        {FINISHED_CODES.has(status) ? (
          <StatePill>{t("common.status.finished")}</StatePill>
        ) : (
          <LiveMinute
            status={status}
            elapsed={live?.elapsed ?? null}
            extra={live?.extra ?? null}
            className="text-[0.8rem]"
          />
        )}
      </div>
    );
  }

  if (phase === "awaiting") {
    return (
      <div className="flex flex-col items-center gap-2 pt-1 text-center">
        <ScoreLine score={score} {...names} />
        <StatePill tone="warning">{t("common.status.awaiting")}</StatePill>
      </div>
    );
  }

  // Finished.
  const s = m.score;
  const ht = s && s.ht_home !== null && s.ht_away !== null ? `${s.ht_home}–${s.ht_away}` : null;
  const pens =
    s && s.pen_home !== null && s.pen_away !== null ? `${s.pen_home}–${s.pen_away}` : null;
  const label =
    m.status_short === "PEN" || pens
      ? t("match.header.afterPenalties")
      : m.status_short === "AET"
        ? t("match.header.afterExtraTime")
        : t("common.status.finished");
  return (
    <div className="flex flex-col items-center gap-1.5 pt-1 text-center">
      <ScoreLine score={score} {...names} />
      <StatePill>{label}</StatePill>
      {pens ? (
        <span className="numeric text-caption text-foreground">
          {t("match.header.penalties", { score: pens })}
        </span>
      ) : null}
      {ht ? (
        <span className="numeric text-caption text-muted-foreground">
          {t("match.header.halfTime", { score: ht })}
        </span>
      ) : null}
    </div>
  );
}

function scorerSuffix(kind: EventKind): string {
  if (kind === "penalty") return ` ${t("match.events.penaltyShort")}`;
  if (kind === "ownGoal") return ` ${t("match.events.ownGoalShort")}`;
  return "";
}

function TeamSide({
  team,
  goals,
  dim,
}: {
  team: TeamRef;
  goals: ReturnType<typeof scorers>["home"];
  dim: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-2 text-center">
      <span className="flex sm:hidden">
        <TeamLogo src={team.logo_url} name={team.name} size={52} />
      </span>
      <span className="hidden sm:flex">
        <TeamLogo src={team.logo_url} name={team.name} size={64} />
      </span>
      <span
        className={cn(
          "line-clamp-2 break-words font-display text-sm font-semibold leading-tight sm:text-lg",
          dim && "text-muted-foreground",
        )}
      >
        {team.name}
      </span>
      {goals.length > 0 ? (
        <ul
          aria-label={t("match.header.scorers", { team: team.name })}
          className="w-full space-y-0.5 text-[0.7rem] leading-snug text-muted-foreground sm:text-xs"
        >
          {goals.map((g) => (
            <li key={g.seq} className="break-words" title={g.name}>
              <span className="sm:hidden">{scorerName(g.name)}</span>
              <span className="hidden sm:inline">{g.name}</span>{" "}
              <span className="numeric">{g.minute}</span>
              {scorerSuffix(g.kind)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function MatchHeader({ ctx }: { ctx: MatchCtx }) {
  const { match: m, venue, phase, live, score } = ctx;
  const round = roundLabel(m.round);
  const center = ctx.center.data;
  const played = phase === "live" || phase === "finished" || phase === "awaiting";
  const events = played && center?.events.status === "ok" ? center.events.data : [];
  const goals = scorers(events, score);
  const winner =
    phase === "finished" && score && score.home !== score.away
      ? score.home > score.away
        ? "home"
        : "away"
      : null;

  return (
    <Card className="pitch-glow overflow-hidden">
      <h1 className="sr-only">{t("match.title", { home: m.home.name, away: m.away.name })}</h1>
      <div className="flex min-w-0 items-center gap-1.5 px-4 pt-3.5 text-caption text-muted-foreground sm:px-5">
        <CompetitionTag
          name={m.competition.name}
          logo={m.competition.logo_url}
          flag={m.competition.flag_url}
          country={m.competition.country}
          className="min-w-0 shrink"
        />
        {round ? (
          <>
            <span aria-hidden className="text-subtle-foreground">
              ·
            </span>
            <span className="min-w-0 truncate">{round}</span>
          </>
        ) : null}
      </div>

      <div className="mx-auto grid max-w-3xl grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-2 px-3 pb-5 pt-4 sm:gap-6 sm:px-6 sm:pb-6">
        <TeamSide team={m.home} goals={goals.home} dim={winner === "away"} />
        <div className="min-w-[6.25rem] sm:min-w-[9rem]">
          <Center ctx={ctx} />
        </div>
        <TeamSide team={m.away} goals={goals.away} dim={winner === "home"} />
      </div>

      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 border-t border-border/70 px-4 py-2.5 text-caption text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <CalendarDays aria-hidden className="h-3.5 w-3.5 text-subtle-foreground" />
          {capitalize(formatDateLong(m.kickoff_at))}
          {m.status_short === "TBD" ? null : (
            <span className="numeric">· {formatTime(m.kickoff_at)}</span>
          )}
        </span>
        {venue ? (
          <span className="inline-flex min-w-0 items-center gap-1.5">
            <MapPin aria-hidden className="h-3.5 w-3.5 shrink-0 text-subtle-foreground" />
            <span className="truncate">
              {venue.name}
              {venue.city ? `, ${venue.city}` : ""}
            </span>
          </span>
        ) : null}
        {center?.facts?.referee ? (
          <span className="inline-flex min-w-0 items-center gap-1.5" data-testid="match-referee">
            <UserRound aria-hidden className="h-3.5 w-3.5 shrink-0 text-subtle-foreground" />
            <span className="truncate">
              {t("match.header.referee", { name: center.facts.referee })}
              {center.facts.referee_country ? ` (${center.facts.referee_country})` : ""}
            </span>
          </span>
        ) : null}
        {phase === "live" && live ? (
          <Freshness at={live.at} level={ageLevel(live.at, 3, 10)} />
        ) : null}
      </div>
    </Card>
  );
}
