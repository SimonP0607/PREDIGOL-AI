/**
 * One leg of a parlay, laid out the same wherever a parlay is shown in full: the match (a link to it), the
 * selection, why it is there (REVIEW point 15) and its price - a price chosen the Cuotas way while the match has not
 * started (REVIEW point 18), the price as taken once it has.
 */
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { CompetitionTag, TeamName } from "@/components/football/Logos";
import { EvBadge, Kickoff, OddsPill } from "@/product/shared/Bits";
import { marketName } from "@/product/shared/markets";
import { SelectablePrice } from "@/product/odds/SelectablePrice";
import { MatchScore } from "@/product/records/DailyItemCard";
import { hasStarted } from "@/product/records/model";
import { LegWhy } from "./LegWhy";
import { legLabel, pickableOfView, type LegView } from "./legs";

export function LegNumber({ n }: { n: number }) {
  return (
    <span
      aria-hidden
      className="numeric flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold-soft text-[0.65rem] font-semibold text-gold-strong"
    >
      {n}
    </span>
  );
}

/** The price, chosen the Cuotas way before kick-off; as it was taken after. */
export function LegPrice({ leg, size = "md" }: { leg: LegView; size?: "sm" | "md" }) {
  const started = hasStarted({ kickoff_at: leg.kickoff_at, status_group: leg.status_group });
  return started ? (
    <OddsPill odds={leg.odds} size={size} />
  ) : (
    <SelectablePrice sel={pickableOfView(leg)} size={size} />
  );
}

export function LegRow({
  leg,
  state,
  status,
}: {
  leg: LegView;
  /** The leg's result or the match's state, for a recorded parlay. */
  state?: ReactNode;
  /** data-status, for the records' tests. */
  status?: string | undefined;
}) {
  return (
    <li data-testid="parlay-leg" data-status={status} className="px-4 py-4 sm:px-5">
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(leg.fixture_id) }}
        className="-mx-2 block rounded-lg px-2 py-1 transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2 text-caption">
            <LegNumber n={leg.n} />
            <CompetitionTag
              name={leg.competition.name}
              logo={leg.competition.logo_url}
              flag={leg.competition.flag_url}
              country={leg.competition.country}
              className="min-w-0"
            />
          </div>
          <Kickoff at={leg.kickoff_at} className="shrink-0" />
        </div>
        <div className="mt-2.5 grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 text-sm">
          <TeamName name={leg.home.name} logo={leg.home.logo_url} size={22} strong />
          {leg.score ? (
            <MatchScore home={leg.score.home} away={leg.score.away} />
          ) : (
            <span className="text-caption text-subtle-foreground">{t("common.vs")}</span>
          )}
          <TeamName name={leg.away.name} logo={leg.away.logo_url} size={22} strong reverse />
        </div>
      </Link>
      <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-2">
        <div className="min-w-0">
          <div className="text-caption uppercase tracking-wider text-subtle-foreground">
            {marketName(leg.market_key)}
          </div>
          <div
            className="mt-0.5 font-display text-[0.95rem] font-semibold leading-snug"
            data-testid="parlay-leg-selection"
          >
            {legLabel(leg)}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <EvBadge ev={leg.why.ev} />
            {state}
          </div>
        </div>
        <div className={cn("flex flex-col items-end gap-1")}>
          <LegPrice leg={leg} />
          {leg.bookmaker ? (
            <span className="max-w-[7rem] truncate text-caption text-muted-foreground">
              {leg.bookmaker}
            </span>
          ) : null}
        </div>
        <LegWhy why={leg.why} frozen={leg.frozen} className="col-span-2 mt-1" />
      </div>
    </li>
  );
}
