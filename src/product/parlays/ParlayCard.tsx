/**
 * A parlay as the product shows it: its selections, then what they add up to - the
 * combined price, the chance that every one of them wins, the expected value and the
 * risk. When too few selections pass the value filter there is no parlay: the card says
 * so (and, in full, why) and never pads it with selections that have no value.
 *
 * `compact` is the Home block (one line per selection); `full` is the Parlays page
 * (competition, model vs market and expected value for every selection).
 *
 * The card is a size container (`@container`): legs and summary lay out by the card's
 * own width, so it reads well full-width and in a half column alike.
 */
import { Link } from "@tanstack/react-router";
import { Clock, ListX } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtInt, fmtOdds, fmtPct, fmtSignedPct, toNumber } from "@/lib/i18n/format";
import { formatKickoff, formatRelative } from "@/lib/time";
import type { Parlay, ParlayLeg } from "@/lib/api/v1/types_product";
import { CompetitionTag, TeamLogo, TeamName } from "@/components/football/Logos";
import {
  EvBadge,
  Kickoff,
  OddsPill,
  ProbCompare,
  RiskBadge,
  ShadowBadge,
} from "@/product/shared/Bits";
import { gateReason, marketName, selectionLabel } from "@/product/shared/markets";
import { PARLAY_ICON, parlayScope, parlayTitle } from "./parlayText";

type Variant = "compact" | "full";

const LEG_LINK =
  "block transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none";

function legLabel(leg: ParlayLeg): string {
  return selectionLabel({
    market_key: leg.market_key,
    selection: leg.selection,
    line: leg.line,
    home: leg.home.name,
    away: leg.away.name,
  });
}

function LegNumber({ n }: { n: number }) {
  return (
    <span
      aria-hidden
      className="numeric flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold-soft text-[0.65rem] font-semibold text-gold-strong"
    >
      {n}
    </span>
  );
}

// Class strings with `text-caption` are not passed through cn(): tailwind-merge takes the
// custom size for a colour and drops it when a text colour follows.
function Bookmaker({ name, narrow = false }: { name: string | null; narrow?: boolean }) {
  if (!name) return null;
  return (
    <span
      className={`${narrow ? "max-w-[5.5rem]" : "max-w-[7rem]"} truncate text-caption text-muted-foreground`}
    >
      {name}
    </span>
  );
}

/** Home: the selection first, then when and which match - one tap opens the match. */
function CompactLeg({ leg, n }: { leg: ParlayLeg; n: number }) {
  return (
    <li>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(leg.fixture_id) }}
        data-testid="parlay-leg"
        className={cn(LEG_LINK, "flex items-center gap-3 px-4 py-2.5 sm:px-5")}
      >
        <LegNumber n={n} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold" data-testid="parlay-leg-selection">
            {legLabel(leg)}
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-caption text-muted-foreground">
            <span className="numeric shrink-0">{formatKickoff(leg.kickoff_at)}</span>
            <span aria-hidden className="text-subtle-foreground">
              ·
            </span>
            <span className="flex shrink-0 items-center gap-0.5">
              <TeamLogo src={leg.home.logo_url} name={leg.home.name} size={14} />
              <TeamLogo src={leg.away.logo_url} name={leg.away.name} size={14} />
            </span>
            <span className="truncate">
              {leg.home.name} – {leg.away.name}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-0.5">
          <OddsPill odds={leg.odds} size="sm" />
          <Bookmaker name={leg.bookmaker} narrow />
        </div>
      </Link>
    </li>
  );
}

/** Parlays page: everything that justifies the selection, laid out as a row on desktop. */
function FullLeg({ leg, n }: { leg: ParlayLeg; n: number }) {
  return (
    <li>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(leg.fixture_id) }}
        data-testid="parlay-leg"
        className={cn(LEG_LINK, "px-4 py-4 sm:px-5")}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2 text-caption">
            <LegNumber n={n} />
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

        {/* Phones: teams, then selection | price, then model vs market.
            Wide card: one row - teams (stacked), selection, model vs market, price. */}
        <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-3 @4xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,1fr)_7.5rem] @4xl:items-center @4xl:gap-x-8">
          <div className="col-span-2 grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 text-sm @4xl:col-span-1 @4xl:col-start-1 @4xl:row-start-1 @4xl:grid-cols-1 @4xl:gap-1.5">
            <TeamName name={leg.home.name} logo={leg.home.logo_url} size={22} strong />
            <span className="text-caption text-subtle-foreground @4xl:hidden">
              {t("common.vs")}
            </span>
            <TeamName
              name={leg.away.name}
              logo={leg.away.logo_url}
              size={22}
              strong
              reverse
              className="@4xl:flex-row @4xl:text-left"
            />
          </div>

          <div className="min-w-0 @4xl:col-start-2 @4xl:row-start-1">
            <div className="text-caption uppercase tracking-wider text-subtle-foreground">
              {marketName(leg.market_key)}
            </div>
            <div
              className="mt-0.5 font-display text-[0.95rem] font-semibold leading-snug"
              data-testid="parlay-leg-selection"
            >
              {legLabel(leg)}
            </div>
            <div className="mt-1.5">
              <EvBadge ev={leg.ev} />
            </div>
          </div>

          <div className="flex flex-col items-end gap-1 @4xl:col-start-4 @4xl:row-start-1">
            <OddsPill odds={leg.odds} />
            <Bookmaker name={leg.bookmaker} />
          </div>

          <div className="col-span-2 min-w-0 @4xl:col-span-1 @4xl:col-start-3 @4xl:row-start-1">
            <ProbCompare model={leg.p_model} market={leg.p_market} />
          </div>
        </div>
      </Link>
    </li>
  );
}

const STAT_LABEL = "text-label leading-tight text-subtle-foreground";

/**
 * Combined odds (the headline, in gold), the chance all legs win and the expected value,
 * then risk and price age. Labels share a grid row so the figures line up even when a
 * label wraps on a phone.
 */
function Summary({ parlay }: { parlay: Parlay }) {
  const p = toNumber(parlay.probability_all_win);
  const ev = toNumber(parlay.expected_value);
  const oneIn = p !== null && p > 0 && p < 0.5 ? Math.round(1 / p) : null;
  return (
    <div
      className="border-t border-gold/20 bg-gold-soft/30 px-4 py-4 sm:px-5"
      data-testid="parlay-summary"
    >
      <dl className="grid grid-cols-2 gap-x-4 @lg:grid-cols-[auto_auto_auto] @lg:justify-start @lg:gap-x-10">
        <dt
          className={`${STAT_LABEL} col-span-2 @lg:col-span-1 @lg:col-start-1 @lg:row-start-1 @lg:self-end`}
        >
          {t("parlays.combinedOdds")}
        </dt>
        <dd
          className="numeric col-span-2 mb-4 mt-1.5 text-[2rem] font-semibold leading-none tracking-tight text-gold-strong @lg:col-span-1 @lg:col-start-1 @lg:row-start-2 @lg:mb-0"
          data-testid="parlay-combined-odds"
        >
          {fmtOdds(parlay.combined_odds)}
        </dd>

        <dt
          className={`${STAT_LABEL} col-start-1 row-start-3 self-end @lg:col-start-2 @lg:row-start-1`}
        >
          {t("parlays.probAll")}
        </dt>
        <dd className="numeric col-start-1 row-start-4 mt-1.5 self-end text-lg font-semibold leading-none @lg:col-start-2 @lg:row-start-2">
          {fmtPct(p, p !== null && p < 0.01 ? 2 : 1)}
        </dd>
        {oneIn ? (
          <dd className="numeric col-start-1 row-start-5 mt-1 text-caption text-muted-foreground @lg:col-start-2 @lg:row-start-3">
            {t("parlays.oneIn", { n: fmtInt(oneIn) })}
          </dd>
        ) : null}

        <dt
          className={`${STAT_LABEL} col-start-2 row-start-3 self-end @lg:col-start-3 @lg:row-start-1`}
        >
          {t("parlays.expectedValue")}
        </dt>
        <dd
          className={cn(
            "numeric col-start-2 row-start-4 mt-1.5 self-end text-lg font-semibold leading-none @lg:col-start-3 @lg:row-start-2",
            ev === null ? "text-muted-foreground" : ev > 0 ? "text-positive" : "text-negative",
          )}
        >
          {fmtSignedPct(ev)}
        </dd>
      </dl>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <RiskBadge risk={parlay.risk} />
        {parlay.prices_as_of ? (
          <span className="inline-flex items-center gap-1 text-caption text-muted-foreground">
            <Clock aria-hidden className="h-3 w-3" />
            {t("parlays.pricesAsOf", { when: formatRelative(parlay.prices_as_of) })}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** No parlay: how far the value filter got, and (in full) what left the rest out. */
function NoParlay({ parlay, variant }: { parlay: Parlay; variant: Variant }) {
  const required = parlay.required_legs;
  const eligible = parlay.eligible_legs;
  const short = eligible < required;
  const reasons = Object.entries(parlay.rejections)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4);
  return (
    <div
      data-empty-state
      data-testid="no-valid-parlay"
      className="flex flex-1 flex-col justify-center px-4 pb-5 pt-4 sm:px-5"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-gold/30 bg-gold-soft text-gold"
        >
          <ListX className="h-5 w-5" />
        </span>
        <div className="min-w-0 pt-0.5">
          <p className="font-display text-sm font-bold uppercase tracking-wider text-foreground">
            {t("parlays.empty.title")}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {short
              ? t("parlays.empty.progress", {
                  eligible: fmtInt(eligible),
                  required: fmtInt(required),
                })
              : t("parlays.empty.notIndependent", {
                  eligible: fmtInt(eligible),
                  required: fmtInt(required),
                })}
          </p>
        </div>
      </div>

      {short && required > 0 && required <= 12 ? (
        <div aria-hidden className="mt-4 flex gap-1.5">
          {Array.from({ length: required }, (_, i) => (
            <span
              key={i}
              className={cn(
                "h-1.5 flex-1 rounded-full",
                i < eligible ? "bg-gold" : "bg-border-strong/80",
              )}
            />
          ))}
        </div>
      ) : null}

      {variant === "full" && reasons.length > 0 ? (
        <div className="mt-5">
          <p className="text-label text-subtle-foreground">{t("parlays.empty.reasons")}</p>
          <ul className="mt-2 divide-y divide-border/60 overflow-hidden rounded-lg border border-border/70 bg-background/30">
            {reasons.map(([code, n]) => (
              <li
                key={code}
                className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                data-testid="parlay-rejection"
              >
                <span className="min-w-0 text-muted-foreground">{gateReason(code)}</span>
                <span className="numeric shrink-0 font-semibold">{fmtInt(n)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-4 text-caption text-subtle-foreground">{t("parlays.empty.never")}</p>
    </div>
  );
}

export function ParlayCard({
  parlay,
  variant = "full",
  showTitle = true,
  className,
}: {
  parlay: Parlay;
  variant?: Variant;
  /** Off where a section header above already names it (Home). */
  showTitle?: boolean;
  className?: string | undefined;
}) {
  const ok = parlay.status === "ok" && parlay.legs.length > 0;
  const shadow = parlay.source === "shadow_preview";
  const title = parlayTitle(parlay.kind);
  const Icon = PARLAY_ICON[parlay.kind];
  return (
    <article
      aria-label={title}
      data-testid={`parlay-card-${parlay.kind}`}
      data-status={parlay.status}
      className={cn(
        "@container flex flex-col overflow-hidden rounded-xl border",
        ok
          ? "gold-ring bg-gradient-to-b from-gold-soft via-card to-card"
          : "border-gold/25 bg-gradient-to-b from-gold-soft/50 to-card",
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 px-4 pt-4 sm:px-5">
        <div className="min-w-0">
          {showTitle ? (
            <h2 className="flex items-center gap-2 font-display text-lg font-semibold tracking-tight">
              <Icon aria-hidden className="h-5 w-5 shrink-0 text-gold" />
              <span className="truncate">{title}</span>
            </h2>
          ) : null}
          <p
            className={showTitle ? "mt-0.5 text-xs text-muted-foreground" : "text-label text-gold"}
          >
            {parlayScope(parlay)}
          </p>
        </div>
        {shadow ? <ShadowBadge className="shrink-0" /> : null}
      </header>

      {ok ? (
        <>
          <ol
            aria-label={t("parlays.legsList")}
            className="mt-3 flex-1 divide-y divide-border/60 border-t border-border/60"
          >
            {parlay.legs.map((leg, i) =>
              variant === "compact" ? (
                <CompactLeg key={leg.pick_id} leg={leg} n={i + 1} />
              ) : (
                <FullLeg key={leg.pick_id} leg={leg} n={i + 1} />
              ),
            )}
          </ol>
          <Summary parlay={parlay} />
        </>
      ) : (
        <NoParlay parlay={parlay} variant={variant} />
      )}
    </article>
  );
}
