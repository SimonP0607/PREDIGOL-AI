/**
 * One of the day's picks as PrediGol recorded it, the way a reader sees it (plan de Inicio, 2.3), top to bottom: league and
 * time, the teams, the market and the selection, the reference odds (no bookmaker: they are a reference, not an offer), what
 * PrediGol and the market give it, its
 * state and result, the lines of why (no «Nivel»: plan PICKS, D4), and «Más sobre este pick», which opens the match on that pick. It stays on the page
 * after kick-off. The model, the review, the expected value, the stage and the time it was chosen are the match's and the
 * owner's: in the evaluation set the owner finds them folded under «Auditoría».
 */
import { Hint } from "@/components/system/Hint";
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Snowflake } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtPct } from "@/lib/i18n/format";
import type { DailyItem } from "@/lib/api/v1/types_records";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { EvBadge, Kickoff, OddsPill } from "@/product/shared/Bits";
import { PriceNowLine } from "@/product/shared/PriceNowLine";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { AiNote } from "./AiNote";
import { CorrectionNote } from "./CorrectionNote";
import { DecisionChain } from "./DecisionChain";
import { formatTime } from "@/lib/time";
import { isLivePhase, matchPhaseOf } from "@/product/matches/status";
import { MatchStateBadge, OriginLabel, ResultBadge, Units } from "./Badges";
import { hasStarted } from "./model";
import { whyLines } from "./cardWhy";
import { pickableOfItem } from "./pickable";
import { useAuth } from "@/lib/auth/AuthProvider";
import { SelectablePrice } from "@/product/odds/SelectablePrice";
import { RiskChips } from "@/product/shared/PickWhy";
import { UserStatusBadge } from "@/product/shared/UserStatusBadge";
import { track } from "@/lib/track";

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
  evaluation = false,
  className,
}: {
  item: DailyItem;
  compact?: boolean;
  /** From the evaluation set: the owner finds the model, the review and the publication under «Auditoría». */
  evaluation?: boolean;
  className?: string | undefined;
}) {
  const admin = useAuth().showAdmin;
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
  const why = whyLines(item);
  const model = Number(item.p_model);
  const market = Number(item.p_market);
  const search = { s: "resumen", pick: item.pick_id } as const;
  const open = () => track("pick_opened", { pick_id: item.pick_id });
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
        search={search}
        onClick={open}
        className="block flex-1 rounded-t-xl focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-4 pt-3.5">
          <CompetitionTag
            name={m.competition.name}
            logo={m.competition.logo_url}
            flag={m.competition.flag_url}
            country={m.competition.country}
            className="min-w-[9rem] flex-1"
          />
          <Kickoff at={m.kickoff_at} className="ml-auto shrink-0" />
        </div>
        {/* Home above away, every name whole, the goals on the right (mobile UX audit: one line cut
            "Gainare Tot…" even at desktop widths). */}
        <div className="flex items-start gap-2.5 px-4 pt-2.5">
          <span
            aria-label={`#${item.rank}`}
            className={cn(
              "numeric mt-px flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
              item.rank === 1
                ? "bg-gold text-gold-foreground"
                : "bg-elevated text-muted-foreground",
            )}
          >
            {item.rank}
          </span>
          <Matchup
            home={{ name: m.home.name, logo: m.home.logo_url }}
            away={{ name: m.away.name, logo: m.away.logo_url }}
            score={
              m.score_home !== null && m.score_away !== null
                ? { home: m.score_home, away: m.score_away }
                : liveScore
            }
            live={!!liveScore && !(m.score_home !== null && m.score_away !== null)}
            className="flex-1"
          />
        </div>

        <div className="mt-3 border-t border-border/70 px-4 pb-3 pt-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <OriginLabel origin="predigol" />
              <div className="mt-1 text-caption uppercase tracking-wider text-subtle-foreground">
                {marketName(item.market_key)}
              </div>
              <div
                className="mt-0.5 break-words font-display text-[0.95rem] font-semibold leading-snug"
                data-testid="pick-selection"
              >
                {label}
              </div>
              {/* Plan UX, B3: its state when it entered the set, in words (the one table). */}
              <UserStatusBadge state={item} className="mt-1.5" />
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <OddsPill odds={item.odds} best={!settled} size={compact ? "md" : "lg"} />
              <span
                className="text-caption text-muted-foreground"
                data-testid="pick-reference-odds"
              >
                {t("records.card.referenceOdds")}
              </span>
              <PriceNowLine now={item.price_now} />
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            {Number.isFinite(model) && Number.isFinite(market) ? (
              <p className="numeric text-xs font-medium" data-testid="pick-probs">
                {t("records.card.probs", { model: fmtPct(model, 0), market: fmtPct(market, 0) })}
              </p>
            ) : null}
          </div>
          <ul className="mt-2 space-y-1" data-testid="pick-why-lines">
            {why.map((line) => (
              <li key={line} className="text-xs leading-snug text-muted-foreground">
                {line}
              </li>
            ))}
          </ul>
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
        {!started ? <SelectablePrice sel={pickableOfItem(item)} save size="sm" /> : null}
      </div>
      <div className="border-t border-border/70 px-4 py-2">
        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: String(m.fixture_id) }}
          search={search}
          onClick={open}
          data-testid="pick-more"
          className="tap-y relative -mx-1 inline-flex min-h-9 items-center gap-0.5 rounded-md px-1 text-xs font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {t("records.card.more")}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </div>
      {/* The owner's, in the evaluation set only: what a reader never sees on a pick (plan de Inicio, 2.3). */}
      {admin && evaluation ? (
        <details
          className="border-t border-border/70 px-4 py-2.5 text-caption"
          data-testid="pick-audit"
        >
          <summary className="cursor-pointer text-xs font-semibold text-info">
            {t("records.card.audit")}
          </summary>
          <div className="mt-2.5 space-y-3">
            {item.ai ? <AiNote ai={item.ai} compact={compact} /> : null}
            {item.ai?.decision ? <RiskChips risks={item.ai.risks} /> : null}
            <DecisionChain
              model={item.model}
              ai={item.ai}
              aiLatest={item.ai_latest}
              evaluation={evaluation}
              admin={admin}
            />
            <div
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5"
              data-testid="daily-item-figures"
            >
              <GlossaryTerm term="expectedValue" className="no-underline">
                <EvBadge ev={item.ev} hint={false} />
              </GlossaryTerm>
              <Hint text={t("records.frozenHelp")} className="no-underline">
                <span
                  className="inline-flex items-center gap-1 text-caption text-muted-foreground"
                  data-testid="daily-item-stage"
                >
                  <Snowflake aria-hidden className="h-3 w-3" />
                  {t(`records.stage.${item.stage}`)}
                </span>
              </Hint>
              <span
                className="text-caption text-muted-foreground"
                data-testid="daily-item-selected-at"
              >
                {t("records.selectedAt", { time: formatTime(item.selected_at) })}
              </span>
              {item.bookmaker ? (
                <span className="text-caption text-muted-foreground">{item.bookmaker}</span>
              ) : null}
            </div>
          </div>
        </details>
      ) : null}
      <CorrectionNote
        corrections={item.corrections}
        record="result"
        className="border-t border-border/70 px-4 py-2.5"
      />
    </article>
  );
}
