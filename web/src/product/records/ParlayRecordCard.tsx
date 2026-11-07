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
import { GlossaryTerm } from "@/components/system/GlossaryTerm";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtOdds, fmtPct, toNumber } from "@/lib/i18n/format";
import { countLegs } from "./model";
import { formatDate, formatKickoff, formatRelative } from "@/lib/time";
import type { ParlayRecord, ParlayRecordLeg, RecordKind } from "@/lib/api/v1/types_records";
import { TeamLogo } from "@/components/football/Logos";
import { PARLAY_ICON, parlayTitle } from "@/product/parlays/parlayText";
import { LegNumber, LegPrice, LegRow } from "@/product/parlays/LegRow";
import { legLabel, viewOfRecord } from "@/product/parlays/legs";
import { EvaluationBadge, ParlayOutcomeBadge, RecordState, Units } from "./Badges";
import { CorrectionNote } from "./CorrectionNote";
import { dayRange, groupByDay } from "./parlayDays";

type Variant = "compact" | "full";

function CompactLeg({ leg }: { leg: ParlayRecordLeg }) {
  const m = leg.match;
  const view = viewOfRecord(leg);
  return (
    <li
      data-testid="parlay-leg"
      data-status={leg.status}
      className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-elevated/40 sm:px-5 pointer-coarse:py-1.5"
    >
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(m.fixture_id) }}
        className="flex min-w-0 flex-1 items-center gap-3 rounded-md focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-11"
      >
        <LegNumber n={leg.leg_no} />
        <div className="min-w-0 flex-1">
          {/* The selection and the match whole, on two lines if need be (mobile UX audit). */}
          <div
            className="break-words text-sm font-semibold leading-snug"
            data-testid="parlay-leg-selection"
          >
            {legLabel(view)}
          </div>
          <div className="mt-0.5 flex min-w-0 items-start gap-1.5 text-caption text-muted-foreground">
            <span className="numeric shrink-0">{formatKickoff(m.kickoff_at)}</span>
            <span aria-hidden className="text-subtle-foreground">
              ·
            </span>
            <span className="mt-px flex shrink-0 items-center gap-0.5">
              <TeamLogo src={m.home.logo_url} name={m.home.name} size={14} />
              <TeamLogo src={m.away.logo_url} name={m.away.name} size={14} />
            </span>
            <span className="min-w-0 break-words">
              {m.home.name} – {m.away.name}
            </span>
          </div>
        </div>
      </Link>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <LegPrice leg={view} size="sm" />
        <RecordState status={leg.status} match={m} hidePending />
      </div>
    </li>
  );
}

const STAT_LABEL = "text-label leading-tight text-subtle-foreground";

function Summary({ parlay }: { parlay: ParlayRecord }) {
  const p = toNumber(parlay.p_all_low);
  const settled = ["WON", "LOST", "VOID", "PARTIAL_VOID"].includes(parlay.status);
  const legs = countLegs(parlay.legs);
  const standing = [
    legs.won > 0 ? t("records.parlay.legsWon", { count: legs.won }) : null,
    legs.lost > 0 ? t("records.parlay.legsLost", { count: legs.lost }) : null,
    legs.pending > 0 ? t("records.parlay.legsPending", { count: legs.pending }) : null,
    legs.void > 0 ? t("records.parlay.legsVoid", { count: legs.void }) : null,
  ].filter((x): x is string => x !== null);
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
            <ParlayOutcomeBadge status={parlay.status} progress={parlay.progress} />
            {settled ? <Units value={parlay.profit_units} className="text-sm" /> : null}
          </dd>
          {legs.pending < legs.total ? (
            <dd
              className="mt-1 text-caption text-muted-foreground"
              data-testid="parlay-legs-standing"
            >
              {standing.join(" · ")}
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
      <CorrectionNote corrections={parlay.corrections} record="parlay" className="mt-3" />
    </div>
  );
}

/**
 * No parlay, honestly (plan UX, A9): why - nothing yet passes all the rules, or nothing that passes them grows together,
 * or the day ended without one - and what a parlay is. Never padded.
 */
function NoParlay({ state, min }: { state: "none" | "building" | "void"; min: number }) {
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
        <p className="mt-1 text-sm text-muted-foreground">
          {t(`records.parlay.${state}.body`, { min })}
        </p>
        <p className="mt-3 text-caption text-subtle-foreground">
          {t("parlays.empty.never")}{" "}
          <GlossaryTerm term="parlay">{t("parlays.empty.what")}</GlossaryTerm>
        </p>
      </div>
    </div>
  );
}

function scope(parlay: ParlayRecord | null, kind: RecordKind): string {
  if (parlay && parlay.legs.length > 0) {
    const count = t("parlays.legs", { count: parlay.legs.length });
    // A multi-day parlay says its span before anything else (plan de Inicio, 2.4).
    const span = kind === "multiday" ? dayRange(groupByDay(parlay.legs)) : null;
    return span ? `${count} · ${span}` : count;
  }
  const min = parlay?.min_legs ?? (kind === "daily" ? 2 : 3);
  const max = parlay?.max_legs ?? (kind === "daily" ? 5 : 7);
  return t("parlays.legsRange", { min, max });
}

/** The day a run of legs is played, over them, in a multi-day parlay. */
function DayHeading({ at, count }: { at: string; count: number }) {
  return (
    <li
      data-testid="parlay-day"
      className="flex items-center justify-between gap-2 bg-elevated/50 px-4 py-1.5 sm:px-5"
    >
      <h3 className="text-label text-subtle-foreground">{formatDate(at)}</h3>
      <span className="numeric text-caption text-subtle-foreground">
        {t("parlays.legs", { count })}
      </span>
    </li>
  );
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
        </div>
      </header>
      {built ? (
        <>
          <ol
            aria-label={t("parlays.legsList")}
            className="mt-3 flex-1 divide-y divide-border/60 border-t border-border/60"
          >
            {(kind === "multiday"
              ? groupByDay(parlay.legs)
              : [{ day: "", at: "", legs: parlay.legs }]
            ).flatMap((group) => [
              kind === "multiday" ? (
                <DayHeading key={`day-${group.day}`} at={group.at} count={group.legs.length} />
              ) : null,
              ...group.legs.map((leg) =>
                variant === "compact" ? (
                  <CompactLeg key={leg.leg_no} leg={leg} />
                ) : (
                  <LegRow
                    key={leg.leg_no}
                    leg={viewOfRecord(leg)}
                    status={leg.status}
                    state={<RecordState status={leg.status} match={leg.match} />}
                  />
                ),
              ),
            ])}
          </ol>
          <Summary parlay={parlay} />
        </>
      ) : (
        <NoParlay state={state} min={parlay?.min_legs ?? (kind === "daily" ? 2 : 3)} />
      )}
      {footer}
    </article>
  );
}
