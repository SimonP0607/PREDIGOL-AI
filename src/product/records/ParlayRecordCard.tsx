/**
 * PrediGol's daily or multi-day parlay as recorded: built once from the legs worth combining,
 * frozen, followed to the end (BUILDING -> READY -> ACTIVE -> WON / LOST / VOID /
 * PARTIAL_VOID). No record, a parlay still being looked for and a day without one each say
 * so plainly - never a padded parlay.
 *
 * `compact` is Home (one line per leg); `full` is the Parlays page.
 */
import { Link } from "@tanstack/react-router";
import { Clock, ListX, Search } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtInt, fmtOdds, fmtPct, toNumber } from "@/lib/i18n/format";
import { formatKickoff, formatRelative } from "@/lib/time";
import type { ParlayRecord, ParlayRecordLeg, RecordKind } from "@/lib/api/v1/types_records";
import { CompetitionTag, TeamLogo, TeamName } from "@/components/football/Logos";
import { EvBadge, Kickoff, OddsPill } from "@/product/shared/Bits";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { PARLAY_ICON, parlayTitle } from "@/product/parlays/parlayText";
import { EvaluationBadge, ParlayStatusBadge, ResultBadge, Units } from "./Badges";
import { MatchScore } from "./DailyItemCard";

type Variant = "compact" | "full";

function legLabel(leg: ParlayRecordLeg): string {
  return selectionLabel({
    market_key: leg.market_key,
    selection: leg.selection,
    line: leg.line,
    home: leg.match.home.name,
    away: leg.match.away.name,
  });
}

const LEG_LINK =
  "block transition-colors hover:bg-elevated/50 focus-visible:bg-elevated/60 focus-visible:outline-none";

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

function CompactLeg({ leg }: { leg: ParlayRecordLeg }) {
  const m = leg.match;
  return (
    <li>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(m.fixture_id) }}
        data-testid="parlay-leg"
        data-status={leg.status}
        className={cn(LEG_LINK, "flex items-center gap-3 px-4 py-2.5 sm:px-5")}
      >
        <LegNumber n={leg.leg_no} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold" data-testid="parlay-leg-selection">
            {legLabel(leg)}
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-caption text-muted-foreground">
            <span className="numeric shrink-0">{formatKickoff(m.kickoff_at)}</span>
            <span aria-hidden className="text-subtle-foreground">
              ·
            </span>
            <span className="flex shrink-0 items-center gap-0.5">
              <TeamLogo src={m.home.logo_url} name={m.home.name} size={14} />
              <TeamLogo src={m.away.logo_url} name={m.away.name} size={14} />
            </span>
            <span className="truncate">
              {m.home.name} – {m.away.name}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <OddsPill odds={leg.odds} size="sm" />
          {leg.status !== "PENDING" ? <ResultBadge status={leg.status} /> : null}
        </div>
      </Link>
    </li>
  );
}

function FullLeg({ leg }: { leg: ParlayRecordLeg }) {
  const m = leg.match;
  return (
    <li>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(m.fixture_id) }}
        data-testid="parlay-leg"
        data-status={leg.status}
        className={cn(LEG_LINK, "px-4 py-4 sm:px-5")}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2 text-caption">
            <LegNumber n={leg.leg_no} />
            <CompetitionTag
              name={m.competition.name}
              logo={m.competition.logo_url}
              flag={m.competition.flag_url}
              country={m.competition.country}
              className="min-w-0"
            />
          </div>
          <Kickoff at={m.kickoff_at} className="shrink-0" />
        </div>
        <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-2">
          <div className="col-span-2 grid min-w-0 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 text-sm">
            <TeamName name={m.home.name} logo={m.home.logo_url} size={22} strong />
            {m.score_home !== null && m.score_away !== null ? (
              <MatchScore home={m.score_home} away={m.score_away} />
            ) : (
              <span className="text-caption text-subtle-foreground">{t("common.vs")}</span>
            )}
            <TeamName name={m.away.name} logo={m.away.logo_url} size={22} strong reverse />
          </div>
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
              <EvBadge ev={leg.ev} />
              <ResultBadge status={leg.status} />
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <OddsPill odds={leg.odds} />
            {leg.bookmaker ? (
              <span className="max-w-[7rem] truncate text-caption text-muted-foreground">
                {leg.bookmaker}
              </span>
            ) : null}
          </div>
        </div>
      </Link>
    </li>
  );
}

const STAT_LABEL = "text-label leading-tight text-subtle-foreground";

function Summary({ parlay }: { parlay: ParlayRecord }) {
  const p = toNumber(parlay.p_all_low);
  const settled = ["WON", "LOST", "VOID", "PARTIAL_VOID"].includes(parlay.status);
  const won = parlay.legs.filter((l) => l.status === "WIN" || l.status === "HALF_WIN").length;
  return (
    <div
      className="border-t border-gold/20 bg-gold-soft/30 px-4 py-4 sm:px-5"
      data-testid="parlay-summary"
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        <div className="col-span-2 sm:col-span-1">
          <dt className={STAT_LABEL}>{t("parlays.combinedOdds")}</dt>
          <dd
            className="numeric mt-1.5 text-[2rem] font-semibold leading-none tracking-tight text-gold-strong"
            data-testid="parlay-combined-odds"
          >
            {fmtOdds(parlay.combined_odds)}
          </dd>
        </div>
        <div className="mt-3 sm:mt-0">
          <dt className={STAT_LABEL} title={t("records.parlay.pAllLowHelp")}>
            {t("records.parlay.pAllLow")}
          </dt>
          <dd className="numeric mt-1.5 text-lg font-semibold leading-none">
            {fmtPct(p, p !== null && p < 0.01 ? 2 : 1)}
          </dd>
        </div>
        <div className="mt-3 sm:mt-0">
          <dt className={STAT_LABEL}>{t("records.labels.result")}</dt>
          <dd className="mt-1.5 flex flex-wrap items-center gap-2">
            <ParlayStatusBadge status={parlay.status} />
            {settled ? <Units value={parlay.profit_units} className="text-sm" /> : null}
          </dd>
          {parlay.legs.some((l) => l.status !== "PENDING") ? (
            <dd className="mt-1 text-caption text-muted-foreground">
              {t("records.parlay.legsResult", {
                won: fmtInt(won),
                total: fmtInt(parlay.legs.length),
              })}
            </dd>
          ) : null}
        </div>
      </dl>
      {parlay.ready_at ? (
        <p className="mt-3 inline-flex items-center gap-1 text-caption text-muted-foreground">
          <Clock aria-hidden className="h-3 w-3" />
          {parlay.settled_at
            ? t("records.parlay.settledAt", { when: formatRelative(parlay.settled_at) })
            : t("records.parlay.builtAt", { when: formatRelative(parlay.ready_at) })}
        </p>
      ) : null}
    </div>
  );
}

function NoParlay({ state }: { state: "none" | "building" | "void" }) {
  const Icon = state === "building" ? Search : ListX;
  return (
    <div
      data-empty-state
      data-testid={`parlay-${state}`}
      className="flex flex-1 items-start gap-3 px-4 pb-5 pt-4 sm:px-5"
    >
      <span
        aria-hidden
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-gold/30 bg-gold-soft text-gold"
      >
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0 pt-0.5">
        <p className="font-display text-sm font-bold uppercase tracking-wider text-foreground">
          {t(`records.parlay.${state}.title`)}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{t(`records.parlay.${state}.body`)}</p>
        <p className="mt-3 text-caption text-subtle-foreground">{t("parlays.empty.never")}</p>
      </div>
    </div>
  );
}

function scope(parlay: ParlayRecord | null, kind: RecordKind): string {
  if (parlay && parlay.legs.length > 0) return t("parlays.legs", { count: parlay.legs.length });
  const min = parlay?.min_legs ?? (kind === "daily" ? 2 : 3);
  const max = parlay?.max_legs ?? (kind === "daily" ? 5 : 7);
  return t("parlays.legsRange", { min, max });
}

export function ParlayRecordCard({
  kind,
  parlay,
  evaluation = false,
  variant = "full",
  showTitle = true,
  className,
  footer,
}: {
  kind: RecordKind;
  parlay: ParlayRecord | null;
  evaluation?: boolean;
  variant?: Variant;
  showTitle?: boolean;
  className?: string | undefined;
  footer?: ReactNode;
}) {
  const built = parlay !== null && parlay.legs.length > 0;
  const state: "none" | "building" | "void" =
    parlay === null ? "none" : parlay.status === "BUILDING" ? "building" : "void";
  const title = parlayTitle(kind);
  const Icon = PARLAY_ICON[kind];
  return (
    <article
      aria-label={title}
      data-testid={`parlay-record-${kind}`}
      data-status={parlay?.status ?? "NONE"}
      className={cn(
        "@container flex flex-col overflow-hidden rounded-xl border",
        built
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
            {scope(parlay, kind)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {evaluation ? <EvaluationBadge /> : null}
          {parlay ? <ParlayStatusBadge status={parlay.status} /> : null}
        </div>
      </header>
      {built ? (
        <>
          <ol
            aria-label={t("parlays.legsList")}
            className="mt-3 flex-1 divide-y divide-border/60 border-t border-border/60"
          >
            {parlay.legs.map((leg) =>
              variant === "compact" ? (
                <CompactLeg key={leg.leg_no} leg={leg} />
              ) : (
                <FullLeg key={leg.leg_no} leg={leg} />
              ),
            )}
          </ol>
          <Summary parlay={parlay} />
        </>
      ) : (
        <NoParlay state={state} />
      )}
      {footer}
    </article>
  );
}
