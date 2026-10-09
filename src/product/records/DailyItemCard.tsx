/**
 * One of the day's picks as PrediGol recorded it: the price and probabilities frozen when it
 * was chosen, the stage it was chosen at, and - once the match is played - its result. It
 * stays on the page after kick-off.
 */
import { Link } from "@tanstack/react-router";
import { Snowflake } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { EvBadge, Kickoff, OddsPill, ProbCompare } from "@/product/shared/Bits";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { AiNote } from "./AiNote";
import { formatTime } from "@/lib/time";
import { isLivePhase, matchPhaseOf } from "@/product/matches/status";
import { MatchStateBadge, OriginLabel, ResultBadge, Units } from "./Badges";
import { hasStarted } from "./model";
import { pickableOfItem } from "./pickable";
import { SelectionActions } from "./SelectionActions";

export function MatchScore({ home, away }: { home: number | null; away: number | null }) {
  if (home === null || away === null) return null;
  return (
    <span className="numeric rounded-md border border-border-strong bg-elevated px-1.5 py-0.5 text-xs font-semibold">
      {home}–{away}
    </span>
  );
}

export function DailyItemCard({
  item,
  compact = false,
  className,
}: {
  item: DailyItem;
  compact?: boolean;
  className?: string | undefined;
}) {
  const m = item.match;
  const label = selectionLabel({
    market_key: item.market_key,
    selection: item.selection,
    line: item.line,
    home: m.home.name,
    away: m.away.name,
  });
  const started = hasStarted(m);
  const settled = item.status !== "PENDING";
  const phase = matchPhaseOf(m.status_short, m.kickoff_at, Date.now(), m.phase);
  const liveScore =
    isLivePhase(phase) && m.live_home != null && m.live_away != null
      ? { home: m.live_home, away: m.live_away }
      : null;
  return (
    <article
      data-testid="daily-item"
      data-status={item.status}
      className={cn(
        "flex h-full flex-col rounded-xl border bg-card transition-colors",
        settled ? "border-border/70" : "border-border hover:border-border-strong",
        item.rank === 1 && !settled && "gold-ring",
        className,
      )}
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(m.fixture_id) }}
        className="block flex-1 rounded-t-xl focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <div className="flex items-center justify-between gap-2 px-4 pt-3.5">
          <CompetitionTag
            name={m.competition.name}
            logo={m.competition.logo_url}
            flag={m.competition.flag_url}
            country={m.competition.country}
            className="min-w-0"
          />
          <Kickoff at={m.kickoff_at} className="shrink-0" />
        </div>
        <div className="flex items-center gap-2 px-4 pt-2.5">
          <span
            aria-label={`#${item.rank}`}
            className={cn(
              "numeric flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
              item.rank === 1
                ? "bg-gold text-gold-foreground"
                : "bg-elevated text-muted-foreground",
            )}
          >
            {item.rank}
          </span>
          <div className="grid min-w-0 flex-1 grid-cols-[1fr_auto_1fr] items-center gap-2 text-sm">
            <TeamName
              name={m.home.name}
              logo={m.home.logo_url}
              size={22}
              strong
              className="min-w-0"
            />
            {m.score_home !== null && m.score_away !== null ? (
              <MatchScore home={m.score_home} away={m.score_away} />
            ) : liveScore ? (
              <MatchScore home={liveScore.home} away={liveScore.away} />
            ) : (
              <span className="text-caption text-subtle-foreground">{t("common.vs")}</span>
            )}
            <TeamName
              name={m.away.name}
              logo={m.away.logo_url}
              size={22}
              strong
              reverse
              className="min-w-0"
            />
          </div>
        </div>

        <div className="mt-3 border-t border-border/70 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <OriginLabel origin="predigol" />
              <div className="mt-1 text-caption uppercase tracking-wider text-subtle-foreground">
                {marketName(item.market_key)}
              </div>
              <div
                className="mt-0.5 truncate font-display text-[0.95rem] font-semibold"
                data-testid="pick-selection"
              >
                {label}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <OddsPill odds={item.odds} best={!settled} size={compact ? "md" : "lg"} />
              {item.bookmaker ? (
                <span className="max-w-[8rem] truncate text-caption text-muted-foreground">
                  {item.bookmaker}
                </span>
              ) : null}
            </div>
          </div>
          {!compact ? (
            <ProbCompare model={item.p_model} market={item.p_market} className="mt-3" />
          ) : null}
          {item.ai ? (
            <div className="mt-3">
              <AiNote ai={item.ai} compact={compact} />
            </div>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <EvBadge ev={item.ev} />
            <span
              className="inline-flex items-center gap-1 text-caption text-muted-foreground"
              title={t("records.frozenHelp")}
              data-testid="daily-item-stage"
            >
              <Snowflake aria-hidden className="h-3 w-3" />
              {t(`records.stage.${item.stage}`)}
            </span>
            <span
              className="text-caption text-muted-foreground"
              data-testid="daily-item-selected-at"
            >
              {t("records.selectedAt", { time: formatTime(item.selected_at) })}
            </span>
          </div>
        </div>
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-caption text-subtle-foreground">{t("records.labels.result")}</span>
          {!settled && started && phase !== "scheduled" && phase !== "unknown" ? (
            <MatchStateBadge match={m} />
          ) : (
            <ResultBadge status={item.status} />
          )}
          {settled ? <Units value={item.profit_units} className="text-xs" /> : null}
        </div>
        {!started ? <SelectionActions sel={pickableOfItem(item)} /> : null}
      </div>
    </article>
  );
}
