/**
 * Resumen, by the match's state (plan UX, A9; section 25: what matters first):
 * before kick-off - four blocks, full width, none empty (plan Partidos y Match Center, R1-R3): PrediGol Intelligence - ONE
 *                   reading of the match (the chronicle's first stretch, or the structured reading as a short text), the
 *                   picks PrediGol published only when there are some, and the way to the whole Análisis; PrediGol's
 *                   forecast; then, folded under «Profundizar», what is read to go deeper - form, table and head to head,
 *                   rest and calendar, absences and line-ups; and the best current prices last. The analysed markets'
 *                   cards and the AI's reading of the day are the owner's, in Avanzado;
 * in play        - the match events first, then the day's reading as it was written before kick-off, the picks as they
 *                  were taken with what the match is doing, key figures and in-play prices; the context folded away;
 * after          - result, events, the pre-match reading and key figures; the context folded away (what happened put
 *                  together, the forecast against the result and how the picks ended are the Postpartido's);
 * not played     - what happened (postponed, cancelled, abandoned, awarded) and the picks.
 */
import { Fragment, useId, useState, type ReactNode } from "react";
import { BarChart3, CalendarX2, ChevronDown, Flag } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { Card, EmptyState } from "@/product/shared/States";
import { AnalysisBlock } from "./AnalysisBlock";
import { CalendarBlock } from "./CalendarBlock";
import type { MatchCtx } from "./context";
import { AbsencesBlock, FormBlock, H2HBlock, LineupsTeaser, StandingsBlock } from "./ContextBlocks";
import { EventsBlock } from "./EventsTimeline";
import { ForecastBlock } from "./ForecastBlock";
import { IntelligenceBlock } from "./IntelligenceBlock";
import { KEY_STATS, statRows } from "./model";
import { PicksTab } from "./PicksTab";
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

export function ResultBlock({ ctx }: { ctx: MatchCtx }) {
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

/**
 * Form, table and head to head side by side (plan Partidos y Match Center, D1): aligned at the top and each as tall as what it
 * holds (`items-start`), never stretched to the tallest with half a card empty. Three columns on a desktop; two on a
 * tablet, the head to head then taking the whole second row; one on a phone.
 */
export function ContextRow({
  form,
  table,
  h2h,
}: {
  form: ReactNode;
  table: ReactNode;
  h2h: ReactNode;
}) {
  return (
    <div
      className="grid items-start gap-4 md:grid-cols-2 lg:grid-cols-3"
      data-testid="deepen-row-context"
    >
      <div className="min-w-0">{form}</div>
      <div className="min-w-0">{table}</div>
      <div className="min-w-0 md:col-span-2 lg:col-span-1">{h2h}</div>
    </div>
  );
}

function ContextGrid({ ctx }: { ctx: MatchCtx }) {
  return (
    <ContextRow
      form={<FormBlock ctx={ctx} />}
      table={<StandingsBlock ctx={ctx} />}
      h2h={<H2HBlock ctx={ctx} />}
    />
  );
}

/** A section that folds under its title (a 44 px row); its content is not drawn until it is opened. */
function Fold({
  title,
  subtitle,
  testId,
  open: initiallyOpen = false,
  children,
}: {
  title: string;
  subtitle: string;
  testId?: string;
  open?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const panelId = useId();
  return (
    <section data-testid={testId}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 text-left transition-colors hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <span>
          <span className="block font-display text-[0.95rem] font-semibold tracking-tight">
            {title}
          </span>
          <span className="block text-caption text-muted-foreground">{subtitle}</span>
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
          {children}
        </div>
      ) : null}
    </section>
  );
}

/** Form, table and head to head, folded away once the match is under way. */
function ContextSection({ ctx, open }: { ctx: MatchCtx; open?: boolean }) {
  return (
    <Fold
      title={t("match.context.title")}
      subtitle={t("match.context.subtitle")}
      {...(open === undefined ? {} : { open })}
    >
      <ContextGrid ctx={ctx} />
    </Fold>
  );
}

/** What «Profundizar» holds, by row. */
export interface DeepenBlocks {
  form: ReactNode;
  table: ReactNode;
  h2h: ReactNode;
  calendar: ReactNode;
  absences: ReactNode;
  lineups: ReactNode;
}

/**
 * «Profundizar» opened, in three rows with no gaps (plan Partidos y Match Center, D1): 1) form, table and head to head,
 * aligned at the top; 2) rest and calendar across the whole width, a team in each column; 3) absences and line-ups in two
 * columns. On a tablet two columns, on a phone one. Apart from the blocks so that a test can check the rows.
 */
export function DeepenLayout({ blocks }: { blocks: DeepenBlocks }) {
  return (
    <div className="min-w-0 space-y-4" data-testid="deepen-layout">
      <ContextRow form={blocks.form} table={blocks.table} h2h={blocks.h2h} />
      <div className="min-w-0" data-testid="deepen-row-calendar">
        {blocks.calendar}
      </div>
      <div className="grid items-start gap-4 md:grid-cols-2" data-testid="deepen-row-squads">
        <div className="min-w-0">{blocks.absences}</div>
        <div className="min-w-0">{blocks.lineups}</div>
      </div>
    </div>
  );
}

/**
 * «Profundizar», before kick-off (plan de cierre UX, 2.2): everything that is read to go deeper once the match is
 * understood - form, table and head to head, then rest and calendar, absences and the line-ups - folded, closed until the
 * reader opens it. The line-ups and the prices keep their link to the tab that shows them in full.
 */
export function DeepenSection({ ctx }: { ctx: MatchCtx }) {
  return (
    <Fold
      title={t("match.deepen.title")}
      subtitle={t("match.deepen.subtitle")}
      testId="match-deepen"
    >
      <DeepenLayout
        blocks={{
          form: <FormBlock ctx={ctx} />,
          table: <StandingsBlock ctx={ctx} />,
          h2h: <H2HBlock ctx={ctx} />,
          calendar: <CalendarBlock ctx={ctx} />,
          absences: <AbsencesBlock ctx={ctx} />,
          lineups: <LineupsTeaser ctx={ctx} />,
        }}
      />
    </Fold>
  );
}

// ── By state ────────────────────────────────────────────────────────────────

const TWO_COLUMNS = "grid items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]";

/** The Resumen before kick-off, in the order it is read (plan Partidos y Match Center, R1). */
export const BEFORE_KICKOFF_ORDER = ["intelligence", "forecast", "deepen", "prices"] as const;
export type BeforeKickoffBlock = (typeof BEFORE_KICKOFF_ORDER)[number];

/**
 * Before kick-off, four blocks, each full width and none empty (plan Partidos y Match Center, R1-R3): PrediGol Intelligence
 * (one reading, the published picks only when there are some, the way to Análisis), PrediGol's forecast, «Profundizar»
 * folded, and the best current prices last. The analysed markets' cards are the owner's, in Avanzado. Apart from the
 * blocks so that a test can check the order.
 */
export function BeforeKickoffLayout({ blocks }: { blocks: Record<BeforeKickoffBlock, ReactNode> }) {
  return (
    <div className="space-y-4" data-testid="summary-before">
      {BEFORE_KICKOFF_ORDER.map((key) => (
        <Fragment key={key}>{blocks[key]}</Fragment>
      ))}
    </div>
  );
}

function BeforeKickoff({ ctx }: { ctx: MatchCtx }) {
  return (
    <BeforeKickoffLayout
      blocks={{
        intelligence: <IntelligenceBlock ctx={ctx} />,
        forecast: <ForecastBlock ctx={ctx} />,
        deepen: <DeepenSection ctx={ctx} />,
        prices: <QuickPricesBlock ctx={ctx} />,
      }}
    />
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
          <PicksTab ctx={ctx} />
          <KeyStatsBlock ctx={ctx} />
          <LiveOddsBlock ctx={ctx} />
        </div>
      </div>
      <ContextSection ctx={ctx} />
    </div>
  );
}

function AfterMatch({ ctx, underPostmatch }: { ctx: MatchCtx; underPostmatch: boolean }) {
  return (
    <div className="space-y-4">
      <div className={TWO_COLUMNS}>
        <div className="min-w-0 space-y-4">
          {/* the Postpartido, on top of this Resumen since decision 11, already opens with the result */}
          {underPostmatch ? null : <ResultBlock ctx={ctx} />}
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
      <PicksTab ctx={ctx} />
      <ContextSection ctx={ctx} open />
    </div>
  );
}

export function SummaryTab({
  ctx,
  underPostmatch = false,
}: {
  ctx: MatchCtx;
  /** The page shows the Postpartido above (a match that is over): what it already says is not said twice. */
  underPostmatch?: boolean;
}) {
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
      return <AfterMatch ctx={ctx} underPostmatch={underPostmatch} />;
  }
}
