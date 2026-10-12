/**
 * Resumen, by the match's state (REVIEW PREDIGOL, point 4 - the picks have their own tab now):
 * before kick-off - PrediGol Intelligence first, the way to the match's picks, the best prices, form,
 *                   table, absences, line-ups and head to head;
 * in play        - the match events first, then the day's reading as it was written before kick-off,
 *                  key figures and in-play prices; the context folded away;
 * after          - result, the way to the picks and how they ended, events, the pre-match reading and
 *                  key figures; the context folded away;
 * not played     - what happened (postponed, cancelled, abandoned, awarded) and the way to the picks.
 */
import { useId, useState, type ReactNode } from "react";
import { BarChart3, CalendarX2, ChevronDown, Flag } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { Card, EmptyState } from "@/product/shared/States";
import { AnalysisBlock } from "./AnalysisBlock";
import type { MatchCtx } from "./context";
import { AbsencesBlock, FormBlock, H2HBlock, LineupsTeaser, StandingsBlock } from "./ContextBlocks";
import { EventsBlock } from "./EventsTimeline";
import { KEY_STATS, statRows } from "./model";
import { PicksTeaser } from "./PicksTab";
import { LiveOddsBlock, QuickPricesBlock } from "./prices";
import { Block, CenterSection, MoreButton, StatBars, TeamsLegend } from "./ui";

// ── Result and key figures ──────────────────────────────────────────────────

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-elevated/40 px-3 py-2">
      <dt className="break-words text-caption leading-tight text-muted-foreground">{label}</dt>
      <dd className="numeric mt-0.5 text-base font-semibold">{value}</dd>
    </div>
  );
}

function ResultBlock({ ctx }: { ctx: MatchCtx }) {
  const s = ctx.match.score;
  // Awaiting its result: what was seen in play is not a final score yet.
  const score = ctx.phase === "finished" ? ctx.score : s ? { home: s.home, away: s.away } : null;
  return (
    <Block title={t("match.result.title")} icon={<Flag />}>
      {!score ? (
        <p className="text-sm text-muted-foreground">{t("match.result.pending")}</p>
      ) : (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Fact label={t("match.result.fullTime")} value={`${score.home}–${score.away}`} />
          <Fact
            label={t("match.result.halfTime")}
            value={
              s && s.ht_home !== null && s.ht_away !== null ? `${s.ht_home}–${s.ht_away}` : "—"
            }
          />
          {s && s.et_home !== null && s.et_away !== null ? (
            <Fact label={t("match.result.extraTime")} value={`${s.et_home}–${s.et_away}`} />
          ) : null}
          {s && s.pen_home !== null && s.pen_away !== null ? (
            <Fact label={t("match.result.penalties")} value={`${s.pen_home}–${s.pen_away}`} />
          ) : null}
          <Fact label={t("match.result.totalGoals")} value={score.home + score.away} />
          <Fact
            label={t("match.result.btts")}
            value={score.home > 0 && score.away > 0 ? t("common.yes") : t("common.no")}
          />
        </dl>
      )}
    </Block>
  );
}

function KeyStatsBlock({ ctx }: { ctx: MatchCtx }) {
  const { home, away } = ctx.match;
  return (
    <Block
      title={t("match.stats.key")}
      icon={<BarChart3 />}
      right={<MoreButton onClick={() => ctx.goTo("stats")}>{t("match.stats.all")}</MoreButton>}
    >
      <CenterSection center={ctx.center} pick={(c) => c.statistics}>
        {(lines) => (
          <div className="space-y-4">
            <TeamsLegend home={home} away={away} />
            <StatBars rows={statRows(lines, KEY_STATS)} />
          </div>
        )}
      </CenterSection>
    </Block>
  );
}

// ── Context ─────────────────────────────────────────────────────────────────

function ContextGrid({ ctx }: { ctx: MatchCtx }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <FormBlock ctx={ctx} />
      <StandingsBlock ctx={ctx} />
      <H2HBlock ctx={ctx} />
    </div>
  );
}

/** Form, table and head to head, folded away once the match is under way. */
function ContextSection({ ctx, open: initiallyOpen = false }: { ctx: MatchCtx; open?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const panelId = useId();
  return (
    <section>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 text-left transition-colors hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <span>
          <span className="block font-display text-[0.95rem] font-semibold tracking-tight">
            {t("match.context.title")}
          </span>
          <span className="block text-caption text-muted-foreground">
            {t("match.context.subtitle")}
          </span>
        </span>
        <ChevronDown
          aria-hidden
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open ? (
        <div id={panelId} className="mt-4">
          <ContextGrid ctx={ctx} />
        </div>
      ) : null}
    </section>
  );
}

// ── By state ────────────────────────────────────────────────────────────────

const TWO_COLUMNS = "grid items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]";

function BeforeKickoff({ ctx }: { ctx: MatchCtx }) {
  // Phones and tablets read in order of use; wide screens balance the two columns.
  const lineups = <LineupsTeaser ctx={ctx} />;
  const form = <FormBlock ctx={ctx} />;
  const table = <StandingsBlock ctx={ctx} />;
  const absences = <AbsencesBlock ctx={ctx} />;
  return (
    <div className={TWO_COLUMNS}>
      <div className="min-w-0 space-y-4">
        <AnalysisBlock ctx={ctx} />
        <PicksTeaser ctx={ctx} />
        <QuickPricesBlock ctx={ctx} />
        <div className="space-y-4 lg:hidden">
          <div className="grid items-start gap-4 md:grid-cols-2">
            {form}
            {table}
          </div>
          <div className="grid items-start gap-4 md:grid-cols-2">
            {lineups}
            {absences}
          </div>
        </div>
        <H2HBlock ctx={ctx} />
      </div>
      <div className="hidden min-w-0 space-y-4 lg:block">
        {lineups}
        {form}
        {table}
        {absences}
      </div>
    </div>
  );
}

function InPlay({ ctx }: { ctx: MatchCtx }) {
  return (
    <div className="space-y-4">
      <div className={TWO_COLUMNS}>
        <div className="min-w-0 space-y-4">
          <EventsBlock ctx={ctx} />
          <AnalysisBlock ctx={ctx} variant="reference" />
        </div>
        <div className="min-w-0 space-y-4">
          <PicksTeaser ctx={ctx} />
          <KeyStatsBlock ctx={ctx} />
          <LiveOddsBlock ctx={ctx} />
        </div>
      </div>
      <ContextSection ctx={ctx} />
    </div>
  );
}

function AfterMatch({ ctx }: { ctx: MatchCtx }) {
  return (
    <div className="space-y-4">
      <div className={TWO_COLUMNS}>
        <div className="min-w-0 space-y-4">
          <ResultBlock ctx={ctx} />
          <PicksTeaser ctx={ctx} />
          <EventsBlock ctx={ctx} />
          <AnalysisBlock ctx={ctx} variant="reference" />
        </div>
        <div className="min-w-0 space-y-4">
          <KeyStatsBlock ctx={ctx} />
        </div>
      </div>
      <ContextSection ctx={ctx} />
    </div>
  );
}

function NotPlayed({ ctx }: { ctx: MatchCtx }) {
  const key =
    ctx.phase === "postponed" || ctx.phase === "abandoned" || ctx.phase === "not_played"
      ? ctx.phase
      : "cancelled";
  return (
    <div className="space-y-4">
      <Card>
        <EmptyState
          icon={<CalendarX2 aria-hidden className="h-6 w-6" />}
          title={t(`match.notPlayed.${key}`)}
          body={t(`match.notPlayed.${key}Body`)}
        />
      </Card>
      <PicksTeaser ctx={ctx} />
      <ContextSection ctx={ctx} open />
    </div>
  );
}

export function SummaryTab({ ctx }: { ctx: MatchCtx }) {
  switch (ctx.phase) {
    case "scheduled":
      return <BeforeKickoff ctx={ctx} />;
    case "live":
      return <InPlay ctx={ctx} />;
    case "postponed":
    case "cancelled":
    case "abandoned":
    case "not_played":
      return <NotPlayed ctx={ctx} />;
    default:
      return <AfterMatch ctx={ctx} />;
  }
}
