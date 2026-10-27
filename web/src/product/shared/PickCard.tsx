/**
 * One pick as the product shows it: the match, the selection, the best price now and
 * the two numbers that justify it (model vs market, expected value) - nothing more.
 * Research fields (model version, lineage, rule) live in the Admin Console.
 */
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtSignedPp } from "@/lib/i18n/format";
import type { PickCard as PickCardData } from "@/lib/api/v1/types_product";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { Hint } from "@/components/system/Hint";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { track } from "@/lib/track";
import { WhyPickButton } from "@/product/picks/WhyPick";
import { EvBadge, Freshness, Kickoff, OddsPill, ProbCompare, ShadowBadge } from "./Bits";
import { gateReason, marketName, selectionLabel } from "./markets";
import { UserStatusBadge } from "./UserStatusBadge";

export function PickCard({
  pick,
  rank,
  shadow = false,
  compact = false,
  className,
  actions,
  why,
}: {
  pick: PickCardData;
  /** 1-5 for the Top 5. */
  rank?: number | undefined;
  /** Built from the admin's shadow preview: labelled, never a recommendation. */
  shadow?: boolean;
  compact?: boolean;
  className?: string | undefined;
  /** Save / add to parlay: below the card's link, never inside it. */
  actions?: ReactNode;
  /** Why the reader is shown it (plan UX, B2): «Sigues a Nacional», «Tu liga» - one line under the teams. */
  why?: ReactNode;
}) {
  const label = selectionLabel({
    market_key: pick.market_key,
    selection: pick.selection,
    line: pick.line,
    home: pick.home.name,
    away: pick.away.name,
  });
  return (
    <div
      data-testid="pick-card"
      className={cn(
        "group flex flex-col rounded-xl border bg-card transition-colors hover:border-border-strong",
        pick.value_now ? "border-border" : "border-border/60 opacity-80",
        rank === 1 && pick.value_now && "gold-ring",
        className,
      )}
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(pick.fixture_id) }}
        onClick={() => track("pick_opened", { pick_id: pick.pick_id })}
        className="block flex-1 rounded-xl focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <div
          className={cn(
            "flex items-center justify-between gap-2 px-4",
            compact ? "pt-3" : "pt-3.5",
          )}
        >
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

        <div className="flex items-start gap-2.5 px-4 pt-2.5">
          {rank ? (
            <span
              aria-label={`#${rank}`}
              className={cn(
                "numeric mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                rank === 1 ? "bg-gold text-gold-foreground" : "bg-elevated text-muted-foreground",
              )}
            >
              {rank}
            </span>
          ) : null}
          {/* Home above away, every name whole (mobile UX audit). */}
          <Matchup
            home={{ name: pick.home.name, logo: pick.home.logo_url }}
            away={{ name: pick.away.name, logo: pick.away.logo_url }}
            className="flex-1"
          />
        </div>
        {why ? <div className="flex min-w-0 px-4 pt-1.5">{why}</div> : null}

        <div
          className={cn(
            "mt-3 border-t border-border/70 px-4",
            compact ? "pb-2 pt-3" : "pb-2.5 pt-3.5",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-caption uppercase tracking-wider text-subtle-foreground">
                {marketName(pick.market_key)}
              </div>
              <div
                className="mt-0.5 break-words font-display text-[0.95rem] font-semibold leading-snug"
                data-testid="pick-selection"
              >
                {label}
              </div>
              {/* Plan UX, B3: the state a reader is shown, in words (the one table). */}
              <UserStatusBadge state={pick} className="mt-1.5" />
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <OddsPill odds={pick.best_odds} best={pick.value_now} size={compact ? "md" : "lg"} />
              {pick.bookmaker ? (
                <span className="max-w-[8rem] truncate text-caption text-muted-foreground">
                  {pick.bookmaker}
                </span>
              ) : null}
            </div>
          </div>

          {!compact ? (
            <ProbCompare model={pick.p_model} market={pick.p_market} className="mt-3" />
          ) : null}
          {!pick.value_now && pick.value_reason ? (
            <p className="mt-2 text-caption text-warning">{gateReason(pick.value_reason)}</p>
          ) : null}
        </div>
      </Link>
      {/* The figures with their help, beside the card's link and not inside it (plan UX, A1, defect F16): a tap, a
          hover or the keyboard opens each definition without opening the match. */}
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 pb-2"
        data-testid="pick-card-figures"
      >
        <GlossaryTerm term="expectedValue" className="no-underline">
          <EvBadge ev={pick.ev} hint={false} />
        </GlossaryTerm>
        {pick.edge !== null ? (
          <GlossaryTerm term="edge" className="numeric text-caption text-muted-foreground">
            {t("common.edge")} {fmtSignedPp(pick.edge)}
          </GlossaryTerm>
        ) : null}
        <Hint text={t(`common.freshnessLevel.${pick.freshness}`)} className="ml-auto no-underline">
          <Freshness at={pick.price_at} level={pick.freshness} hint={false} />
        </Hint>
      </div>
      <div className={cn("flex px-4", compact ? "pb-3" : "pb-3.5")}>
        <WhyPickButton pickId={pick.pick_id} />
      </div>
      {actions ? <div className="border-t border-border/70 px-4 py-2.5">{actions}</div> : null}
    </div>
  );
}
