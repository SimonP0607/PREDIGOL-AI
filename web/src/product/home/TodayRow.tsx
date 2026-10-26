/**
 * One match of Inicio (plan UX, A9 and A13; section 24): when - the hour in the reader's zone, the minute while it is played
 * or its final state -, who, the score, where it comes from and why it is shown («Sigues a Nacional», «Tu liga» or
 * «Sugerida»: plan section 38, every personalised item says why), PrediGol's forecast labelled («sin calibrar» where it is
 * the model's own number) and one line of its reading. The whole row opens the match; a figure's help opens with a tap
 * without opening it (A1).
 */
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { hintProps } from "@/components/system/tapHint";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { termShort } from "@/lib/glossary";
import { t } from "@/lib/i18n";
import { fmtPct } from "@/lib/i18n/format";
import { formatDate, formatTime, relativeDay } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { TodayMatch } from "@/lib/api/v1/types_today";
import type { TabKey } from "@/product/match/context";
import { RowClock } from "@/product/matches/MatchRow";
import { liveLabel } from "@/product/matches/status";
import { factText } from "@/product/reading/text";
import { inPlay, phaseOf, played } from "./today";
import { whyText, type Why } from "./why";

function dayLabel(at: string): string | null {
  const rel = relativeDay(at);
  if (rel === "today") return null;
  if (rel === "tomorrow") return t("common.day.tomorrow");
  if (rel === "yesterday") return t("common.day.yesterday");
  return formatDate(at);
}

function When({ m, now }: { m: TodayMatch; now: number }) {
  if (inPlay(m, now)) {
    return <RowClock label={liveLabel(m.status, m.elapsed, null)} />;
  }
  const phase = phaseOf(m, now);
  if (phase === "finished") {
    return (
      <span className="text-xs font-medium text-muted-foreground">{t("matches.clock.FT")}</span>
    );
  }
  const day = dayLabel(m.kickoff_at);
  const off = phase !== "scheduled";
  return (
    <span className="flex flex-col leading-tight">
      <span
        className={cn(
          "numeric text-sm font-semibold",
          off && "text-subtle-foreground line-through",
        )}
      >
        {formatTime(m.kickoff_at)}
      </span>
      {day ? <span className="mt-0.5 text-caption text-muted-foreground">{day}</span> : null}
      {off ? (
        <span className="mt-0.5 text-caption text-warning">{t(`common.status.${phase}`)}</span>
      ) : null}
    </span>
  );
}

export function WhyChip({ why }: { why: Why }) {
  const { label, help } = whyText(why);
  return (
    <span
      {...hintProps(help)}
      data-testid="today-why"
      data-why={why.kind}
      className="min-w-0 max-w-full truncate rounded-full border border-primary/30 bg-primary/10 px-2 py-px font-medium text-primary"
    >
      {label}
    </span>
  );
}

/** «Pronóstico: gana Nacional · 52 %», labelled when uncalibrated. */
export function ForecastLine({ m }: { m: TodayMatch }) {
  const f = m.forecast;
  if (!f) return null;
  const team = f.outcome === "home" ? m.home.name : f.outcome === "away" ? m.away.name : "";
  return (
    <p
      className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-caption"
      data-testid="today-forecast"
      data-outcome={f.outcome}
    >
      <span className="font-medium text-foreground/90" {...hintProps(termShort("forecast"))}>
        {t(`home.today.forecast.${f.outcome}`, { team })}
      </span>
      <span className="numeric font-semibold text-foreground">{fmtPct(f.probability, 0)}</span>
      {f.calibrated ? null : (
        <span
          {...hintProps(termShort("calibrated"))}
          data-testid="today-uncalibrated"
          className="rounded-full border border-border-strong bg-elevated px-1.5 py-px font-medium text-muted-foreground"
        >
          {t("home.today.uncalibrated")}
        </span>
      )}
    </p>
  );
}

export function TodayRow({
  m,
  now,
  why = null,
  reading = true,
  forecast = true,
  tab,
  extra,
}: {
  m: TodayMatch;
  now: number;
  /** Why it is on Inicio (plan section 38: every personalised item says why); nothing for the rest of the board. */
  why?: Why | null | undefined;
  /** The reading's line (what the match is about). */
  reading?: boolean;
  /** PrediGol's forecast, labelled (not for a result: the Postpartido says what it said). */
  forecast?: boolean;
  /** The section of the match to open (the Postpartido of a result). */
  tab?: TabKey | undefined;
  extra?: ReactNode;
}) {
  const line = reading && m.headline ? factText(m.headline) : null;
  const score =
    (inPlay(m, now) || played(m, now)) && m.goals_home !== null && m.goals_away !== null
      ? { home: m.goals_home, away: m.goals_away }
      : null;
  return (
    <Link
      to="/matches/$fixtureId"
      params={{ fixtureId: String(m.fixture_id) }}
      {...(tab ? { hash: tab } : {})}
      data-testid="today-row"
      data-fixture={m.fixture_id}
      className="flex h-full items-start gap-3 px-4 py-3 transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none sm:px-5"
    >
      <div className="w-12 shrink-0 pt-0.5">
        <When m={m} now={now} />
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <Matchup
          home={{ name: m.home.name, logo: m.home.logo_url }}
          away={{ name: m.away.name, logo: m.away.logo_url }}
          score={score}
          live={inPlay(m, now)}
          size={18}
          strong={false}
          className="font-medium"
        />
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-caption">
          <CompetitionTag
            name={m.competition.name}
            logo={m.competition.logo_url}
            flag={m.competition.flag_url}
            country={m.competition.country}
            size={12}
            className="min-w-0"
          />
          {why ? <WhyChip why={why} /> : null}
        </div>
        {forecast ? <ForecastLine m={m} /> : null}
        {line ? (
          <p className="text-xs leading-snug text-muted-foreground" data-testid="today-headline">
            {line}
          </p>
        ) : null}
        {extra}
      </div>
    </Link>
  );
}
