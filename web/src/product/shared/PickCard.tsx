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
import { ExplainButton } from "@/product/explain/ExplainSheet";
import { WhyPickButton } from "@/product/picks/WhyPick";
import {
  ASK_BUTTON,
  EvBadge,
  Freshness,
  Kickoff,
  OddsPill,
  ProbCompare,
  ShadowBadge,
  TAG,
} from "./Bits";
import { gateReason, marketName, selectionLabel } from "./markets";
import { PickWhyLine } from "./PickWhy";
import { onGoldCard } from "./userStatus";
import { UserStatusBadge } from "./UserStatusBadge";

export function PickCard({
  pick,
  rank,
  shadow = false,
  compact = false,
  className,
  actions,
  why,
  autoOpenWhy = false,
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
  /** The explanation opens by itself: the reader came from «Más sobre este pick» (plan de Inicio, 2.3). */
  autoOpenWhy?: boolean;
}) {
  const label = selectionLabel({
    market_key: pick.market_key,
    selection: pick.selection,
    line: pick.line,
    home: pick.home.name,
    away: pick.away.name,
  });
  // «Noche de partido» (the system's sheet 4, plan maestro UX/UI 2026, PR-13): what PrediGol recommends is drawn on the
  // gold card, its seal first. The rule is the one the seal already follows; the card adds no state of its own.
  const recommended = onGoldCard(pick);
  return (
    <div
      data-testid="pick-card"
      data-recommended={recommended || undefined}
      className={cn(
        "group flex flex-col rounded-feature transition-colors",
        recommended ? "surface-gold hairline-gold" : "card-surface hover:border-border-strong",
        !pick.value_now && "opacity-80",
        className,
      )}
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(pick.fixture_id) }}
        onClick={() => track("pick_opened", { pick_id: pick.pick_id })}
        className="block flex-1 rounded-feature focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {/* The seal and the hour share the first line; the hour drops below when a narrow card cannot hold both. */}
        <div className="flex flex-wrap items-start gap-x-2 gap-y-1.5 px-4 pt-4">
          <div className="flex min-w-0 items-start gap-2">
            {rank ? (
              <span
                aria-label={`#${rank}`}
                className="numeric flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gold text-xs font-extrabold leading-none text-gold-foreground"
              >
                {rank}
              </span>
            ) : null}
            {/* Plan UX, B3: the state a reader is shown, in words (the one table). */}
            <UserStatusBadge state={pick} />
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-1.5 pt-0.5">
            {shadow ? <ShadowBadge compact /> : null}
            <Kickoff at={pick.kickoff_at} />
          </div>
        </div>

        <div className="px-4 pt-2.5">
          {/* The league whole, on its own line (plan PICKS, U1: the name broke letter by letter beside «SHADOW»). */}
          <CompetitionTag
            name={pick.competition.name}
            logo={pick.competition.logo_url}
            flag={pick.competition.flag_url}
            country={pick.competition.country}
          />
          {/* Home above away, every name whole (mobile UX audit). */}
          <Matchup
            home={{ name: pick.home.name, logo: pick.home.logo_url }}
            away={{ name: pick.away.name, logo: pick.away.logo_url }}
            className="mt-2"
          />
        </div>
        {why ? <div className="flex min-w-0 px-4 pt-1.5">{why}</div> : null}

        <div className={cn("px-4", compact ? "pb-2 pt-3" : "pb-2.5 pt-3.5")}>
          <div className="flex items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="text-overline text-muted-foreground">
                {marketName(pick.market_key)}
              </div>
              <div
                className={cn("mt-1 break-words", compact ? "text-subheading" : "text-heading")}
                data-testid="pick-selection"
              >
                {label}
              </div>
            </div>
            {/* Reference odds: no bookmaker for a reader (plan PICKS, D6); the owner finds it in the audit. */}
            <OddsPill odds={pick.best_odds} best={pick.value_now} size={compact ? "md" : "lg"} />
          </div>

          {!compact ? (
            <ProbCompare model={pick.p_model} market={pick.p_market} className="mt-3.5" />
          ) : (
            <PickWhyLine model={pick.p_model} market={pick.p_market} className="mt-2.5" />
          )}
          {!pick.value_now && pick.value_reason ? (
            <p className="mt-2 text-caption text-warning">{gateReason(pick.value_reason)}</p>
          ) : null}
        </div>
      </Link>
      {/* The figures with their help, beside the card's link and not inside it (plan UX, A1, defect F16): a tap, a
          hover or the keyboard opens each definition without opening the match. */}
      <div
        className="flex flex-wrap items-center gap-x-2 gap-y-1.5 px-4 pb-2.5"
        data-testid="pick-card-figures"
      >
        <GlossaryTerm term="expectedValue" className="no-underline">
          <EvBadge ev={pick.ev} hint={false} />
        </GlossaryTerm>
        {pick.edge !== null ? (
          <GlossaryTerm term="edge" className={cn(TAG, "no-underline")}>
            {t("common.edge")} {fmtSignedPp(pick.edge)}
          </GlossaryTerm>
        ) : null}
        <Hint text={t(`common.freshnessLevel.${pick.freshness}`)} className="ml-auto no-underline">
          <Freshness at={pick.price_at} level={pick.freshness} hint={false} />
        </Hint>
      </div>
      <div className={cn("flex flex-wrap gap-2 px-4", compact ? "pb-3" : "pb-3.5")}>
        <WhyPickButton pickId={pick.pick_id} autoOpen={autoOpenWhy} className={ASK_BUTTON} />
        <ExplainButton
          entity="pick"
          itemId={pick.pick_id}
          testId="explain-pick"
          className={ASK_BUTTON}
        />
      </div>
      {actions ? <div className="border-t border-border/70 px-4 py-2.5">{actions}</div> : null}
    </div>
  );
}
