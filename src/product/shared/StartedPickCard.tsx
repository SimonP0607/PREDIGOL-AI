/**
 * A pre-match pick whose match has kicked off, as PrediGol took it: "PICK PREPARTIDO", the
 * time the price was taken, the price and the bookmaker, the model and the market at that
 * moment - frozen, never re-priced - and beside it, never mixed in, what the match is doing
 * now (minute and score), its result and its value against the last pre-match price (a
 * near-close price, not validated as the closing line - so the label says so).
 */
import { Link } from "@tanstack/react-router";
import { History } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtSignedPct } from "@/lib/i18n/format";
import { formatTime } from "@/lib/time";
import type { StartedPick } from "@/lib/api/v1/types_product";
import type { ResultStatus } from "@/lib/api/v1/types_records";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { MatchStateBadge, ResultBadge, Units } from "@/product/records/Badges";
import { MatchScore } from "@/product/records/DailyItemCard";
import { isLivePhase } from "@/product/matches/status";
import { EvBadge, Kickoff, OddsPill, ProbCompare, ShadowBadge } from "./Bits";
import { marketName, selectionLabel } from "./markets";

const RESULTS: Record<string, ResultStatus> = {
  win: "WIN",
  loss: "LOSS",
  push: "PUSH",
  void: "VOID",
  half_win: "HALF_WIN",
  half_loss: "HALF_LOSS",
};

export function StartedPickCard({
  pick,
  shadow = false,
  className,
}: {
  pick: StartedPick;
  /** From the admin's shadow preview: labelled, never a recommendation. */
  shadow?: boolean;
  className?: string | undefined;
}) {
  const label = selectionLabel({
    market_key: pick.market_key,
    selection: pick.selection,
    line: pick.line,
    home: pick.home.name,
    away: pick.away.name,
  });
  const result = pick.result_status ? RESULTS[pick.result_status] : undefined;
  const live = isLivePhase(pick.phase);
  const score =
    pick.score_home !== null && pick.score_away !== null
      ? { home: pick.score_home, away: pick.score_away }
      : live && pick.live_home !== null && pick.live_away !== null
        ? { home: pick.live_home, away: pick.live_away }
        : null;
  return (
    <article
      data-testid="started-pick"
      data-phase={pick.phase}
      data-result={pick.result_status ?? "open"}
      className={cn("flex flex-col rounded-xl border border-border/80 bg-card", className)}
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(pick.fixture_id) }}
        className="block flex-1 rounded-t-xl focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <div className="flex items-center justify-between gap-2 px-4 pt-3.5">
          <CompetitionTag
            name={pick.competition.name}
            logo={pick.competition.logo_url}
            flag={pick.competition.flag_url}
            country={pick.competition.country}
            className="min-w-0"
          />
          <div className="flex shrink-0 items-center gap-1.5">
            {shadow ? <ShadowBadge compact /> : null}
            <Kickoff at={pick.kickoff_at} />
          </div>
        </div>
        <div className="grid min-w-0 grid-cols-[1fr_auto_1fr] items-center gap-2 px-4 pt-2.5 text-sm">
          <TeamName
            name={pick.home.name}
            logo={pick.home.logo_url}
            size={22}
            strong
            className="min-w-0"
          />
          {score ? (
            <MatchScore home={score.home} away={score.away} />
          ) : (
            <span className="text-caption text-subtle-foreground">{t("common.vs")}</span>
          )}
          <TeamName
            name={pick.away.name}
            logo={pick.away.logo_url}
            size={22}
            strong
            reverse
            className="min-w-0"
          />
        </div>

        <div className="mt-3 border-t border-border/70 px-4 py-3">
          <div
            className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] font-semibold uppercase tracking-wider text-gold"
            title={t("match.picks.prematchHelp")}
          >
            <History aria-hidden className="h-3 w-3" />
            <span>{t("match.picks.prematchBadge")}</span>
            <span className="font-medium normal-case tracking-normal text-muted-foreground">
              · {t("match.picks.takenAt", { time: formatTime(pick.taken_at) })}
            </span>
          </div>
          <div className="mt-1.5 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-caption uppercase tracking-wider text-subtle-foreground">
                {marketName(pick.market_key)}
              </div>
              <div
                className="mt-0.5 truncate font-display text-[0.95rem] font-semibold"
                data-testid="pick-selection"
              >
                {label}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <OddsPill odds={pick.odds_taken} best={false} size="md" />
              {pick.bookmaker ? (
                <span className="max-w-[8rem] truncate text-caption text-muted-foreground">
                  {pick.bookmaker}
                </span>
              ) : null}
            </div>
          </div>
          <ProbCompare model={pick.p_model} market={pick.p_market} className="mt-3" />
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <EvBadge ev={pick.ev} />
            <span className="numeric text-caption text-muted-foreground">
              {t("common.edge")} {fmtSignedPct(pick.edge)}
            </span>
            {pick.evaluations > 1 ? (
              <span className="text-caption text-muted-foreground">
                {t("match.picks.evaluations", { count: pick.evaluations })}
              </span>
            ) : null}
          </div>
        </div>
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-caption text-subtle-foreground">{t("match.picks.stateNow")}</span>
          {result ? (
            <>
              <ResultBadge status={result} />
              <Units value={pick.profit_units} className="text-xs" />
            </>
          ) : (
            <MatchStateBadge match={pick} />
          )}
        </div>
        {pick.near_close_odds !== null && pick.line_value !== null ? (
          <span
            className="numeric text-caption text-muted-foreground"
            data-testid="started-pick-line-value"
          >
            {t("match.picks.closeOdds", { odds: fmtOdds(pick.near_close_odds) })} ·{" "}
            {t("match.picks.clv", { value: fmtSignedPct(pick.line_value) })}
          </span>
        ) : null}
      </div>
    </article>
  );
}
