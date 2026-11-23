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
import {
  BarChart3,
  CalendarX2,
  ChevronDown,
  ChevronRight,
  Flag,
  Newspaper,
  Shirt,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { Card, EmptyState } from "@/product/shared/States";
import { useNews } from "@/product/news/useNews";
import { headline } from "@/product/news/news";
import { AnalysisBlock } from "./AnalysisBlock";
import { CalendarBlock } from "./CalendarBlock";
import type { MatchCtx } from "./context";
import { AbsencesBlock, FormBlock, H2HBlock, LineupsTeaser, StandingsBlock } from "./ContextBlocks";
import { EventsBlock } from "./EventsTimeline";
import { ForecastBlock } from "./ForecastBlock";
import { IntelligenceBlock } from "./IntelligenceBlock";
import { KEY_STATS, statRows } from "./model";
import { PicksTab, UpcomingPicks } from "./PicksTab";
import { useWidePicks } from "./picks";
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
 * tablet, the head to head then taking the whole second row; one on a phone. The columns follow the width of the
 * container, not the screen's (AP-P01): the column beside a side panel is about 650 px wide at a 1280 px screen, where three
 * columns made the texts a cascade of letters. One column under 40 rem, two from 40, three from 64.
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
    <div className="@container">
      <div
        className="grid grid-cols-1 items-start gap-4 @[40rem]:grid-cols-2 @[64rem]:grid-cols-3"
        data-testid="deepen-row-context"
      >
        <div className="min-w-0">{form}</div>
        <div className="min-w-0">{table}</div>
        <div className="min-w-0 @[40rem]:col-span-2 @[64rem]:col-span-1">{h2h}</div>
      </div>
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
      <div className="@container">
        <div
          className="grid grid-cols-1 items-start gap-4 @[40rem]:grid-cols-2"
          data-testid="deepen-row-squads"
        >
          <div className="min-w-0">{blocks.absences}</div>
          <div className="min-w-0">{blocks.lineups}</div>
        </div>
      </div>
    </div>
  );
}

/**
 * «Profundizar», before kick-off (plan de cierre UX, 2.2; plan maestro unificado, sheet P03): a card of three rows - form,
 * table and head to head, which opens here with rest, calendar, absences and the line-ups; the line-ups and absences, with
 * whether they are confirmed, and the match's news with how many there are, each opening its own tab. Closed until the
 * reader opens it; the first row is the fold's own button.
 */
export function DeepenSection({ ctx }: { ctx: MatchCtx }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const news = useNews(ctx.fixtureId);
  const newsCount =
    news.status === "success" && news.envelope.status === "ok"
      ? (news.envelope.data?.items.length ?? 0)
      : null;
  const lineups = ctx.center.data?.lineups;
  const confirmed = lineups?.status === "ok" && lineups.data.length > 0;
  const row =
    "flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring";
  return (
    <section data-testid="match-deepen" aria-labelledby={`${panelId}-title`} className="space-y-3">
      <h2 id={`${panelId}-title`} className="font-display text-lg font-semibold tracking-tight">
        {t("match.deepen.title")}
      </h2>
      <Card as="div" className="divide-y divide-border overflow-hidden p-0">
        <div>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={open ? panelId : undefined}
            onClick={() => setOpen((v) => !v)}
            className={row}
          >
            <BarChart3 aria-hidden className="h-4 w-4 shrink-0 text-primary" />
            <span className="min-w-0 flex-1 text-sm font-semibold">
              {t("match.deepen.rows.context")}
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
            <div id={panelId} className="border-t border-border p-4">
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
            </div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => ctx.goTo("lineups")}
          className={row}
          data-testid="deepen-lineups"
        >
          <Shirt aria-hidden className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 flex-1 text-sm font-semibold">
            {t("match.deepen.rows.lineups")}
          </span>
          <span
            className={cn(
              "shrink-0 rounded-full px-2 py-0.5 text-micro font-semibold",
              confirmed
                ? "bg-positive-soft text-positive"
                : "bg-foreground/[0.07] text-muted-foreground",
            )}
          >
            {confirmed ? t("match.deepen.confirmed") : t("match.deepen.pending")}
          </span>
          <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
        <button
          type="button"
          onClick={() => ctx.goTo("news")}
          className={row}
          data-testid="deepen-news"
        >
          <Newspaper aria-hidden className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 flex-1 text-sm font-semibold">
            {t("match.deepen.rows.news")}
          </span>
          {newsCount !== null && newsCount > 0 ? (
            <span className="numeric flex h-6 min-w-6 shrink-0 items-center justify-center rounded-full bg-elevated px-1.5 text-xs font-semibold">
              {newsCount}
            </span>
          ) : null}
          <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
      </Card>
    </section>
  );
}

/**
 * At a desk, the side column's foot (sheet P11): the line-ups and the news one glance away - whether the line-ups are
 * confirmed and the latest headlines, each opening its tab. A phone reads them in «Profundizar».
 */
export function SidePreviews({ ctx }: { ctx: MatchCtx }) {
  const news = useNews(ctx.fixtureId);
  const items =
    news.status === "success" && news.envelope.status === "ok"
      ? (news.envelope.data?.items ?? []).slice(0, 2)
      : [];
  const lineups = ctx.center.data?.lineups;
  const confirmed = lineups?.status === "ok" && lineups.data.length > 0;
  return (
    <div className="hidden space-y-4 lg:block" data-testid="summary-previews">
      <Block title={t("match.lineups.title")} icon={<Shirt />}>
        <p className="text-sm text-muted-foreground">
          {confirmed ? t("match.lineups.confirmed") : t("match.deepen.lineupsPending")}
        </p>
        <MoreButton onClick={() => ctx.goTo("lineups")}>{t("match.lineups.view")}</MoreButton>
      </Block>
      <Block title={t("match.deepen.rows.news")} icon={<Newspaper />}>
        {items.length > 0 ? (
          <ul className="space-y-2">
            {items.map((i) => (
              <li key={i.id} className="text-sm leading-snug">
                {headline(i)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{t("match.deepen.noNews")}</p>
        )}
        <MoreButton onClick={() => ctx.goTo("news")}>{t("match.deepen.seeNews")}</MoreButton>
      </Block>
    </div>
  );
}

// ── By state ────────────────────────────────────────────────────────────────

const TWO_COLUMNS = "grid items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]";

/**
 * The Resumen before kick-off, in the order it is read on a phone (plan Partidos y Match Center, R1; plan maestro UX/UI
 * 2026, sheets P03 and P11): the reading, the published picks, the forecast, «Profundizar» and the best prices.
 */
export const BEFORE_KICKOFF_ORDER = [
  "picks",
  "intelligence",
  "forecast",
  "prices",
  "deepen",
  "previews",
] as const;
export type BeforeKickoffBlock = (typeof BEFORE_KICKOFF_ORDER)[number];

/** At a desk the picks and the prices are the side column (sheet P11); the rest is the main one. */
export const BEFORE_KICKOFF_SIDE: readonly BeforeKickoffBlock[] = ["picks", "prices", "previews"];

const ORDER: Record<BeforeKickoffBlock, string> = {
  picks: "order-1",
  intelligence: "order-2",
  forecast: "order-3",
  prices: "order-4",
  deepen: "order-5",
  previews: "order-6",
};

const BEFORE_COLUMN =
  "contents lg:@container lg:flex lg:min-w-0 lg:flex-col lg:gap-4 lg:*:order-none";

/**
 * Before kick-off, no block empty (plan Partidos y Match Center, R1-R3): PrediGol Intelligence (one reading and the way to
 * Análisis), the published picks only when there are some, PrediGol's forecast, «Profundizar» folded, and the best
 * current prices. One column on a phone and a tablet, in `BEFORE_KICKOFF_ORDER`; at a desk two (sheet P11), the picks and
 * the prices in a side column of 400 px. The analysed markets' cards are the owner's, in Avanzado. Apart from the blocks
 * so that a test can check the order.
 */
export function BeforeKickoffLayout({ blocks }: { blocks: Record<BeforeKickoffBlock, ReactNode> }) {
  const cell = (key: BeforeKickoffBlock) => (
    <div key={key} data-block={key} className={cn("min-w-0 empty:hidden", ORDER[key])}>
      {blocks[key]}
    </div>
  );
  return (
    <div
      className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,1fr)_25rem] lg:items-start"
      data-testid="summary-before"
    >
      <div className={BEFORE_COLUMN} data-testid="summary-main">
        {BEFORE_KICKOFF_ORDER.filter((k) => !BEFORE_KICKOFF_SIDE.includes(k)).map(cell)}
      </div>
      <aside className={BEFORE_COLUMN} data-testid="summary-side">
        {BEFORE_KICKOFF_SIDE.map(cell)}
      </aside>
    </div>
  );
}

export interface OrderedBlock {
  key: string;
  node: ReactNode;
  /** Its place on a phone, where both columns read as one. */
  order: number;
}

const ORDER_CLASS = [
  "order-1",
  "order-2",
  "order-3",
  "order-4",
  "order-5",
  "order-6",
  "order-7",
  "order-8",
  "order-9",
];

/**
 * Two columns at a desk and one on a phone in the sheet's order (sheets P09 and P10, UX-145): the same trick as before
 * kick-off - the columns are `contents` on a phone, so each block takes its own place, and flex columns at a desk.
 */
export function OrderedColumns({
  main,
  side,
  testId,
}: {
  main: readonly OrderedBlock[];
  side: readonly OrderedBlock[];
  testId: string;
}) {
  const cell = (b: OrderedBlock) => (
    <div
      key={b.key}
      data-block={b.key}
      className={cn("min-w-0 empty:hidden", ORDER_CLASS[b.order - 1])}
    >
      {b.node}
    </div>
  );
  return (
    <div
      className="flex flex-col gap-4 lg:grid lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] lg:items-start"
      data-testid={testId}
    >
      <div className={BEFORE_COLUMN}>{main.map(cell)}</div>
      <aside className={BEFORE_COLUMN}>{side.map(cell)}</aside>
    </div>
  );
}

function BeforeKickoff({ ctx }: { ctx: MatchCtx }) {
  return (
    <BeforeKickoffLayout
      blocks={{
        intelligence: <IntelligenceBlock ctx={ctx} picks={false} />,
        picks: <UpcomingPicks ctx={ctx} />,
        forecast: <ForecastBlock ctx={ctx} />,
        deepen: <DeepenSection ctx={ctx} />,
        prices: <QuickPricesBlock ctx={ctx} />,
        previews: <SidePreviews ctx={ctx} />,
      }}
    />
  );
}

/**
 * In play (sheet P09): on a phone the pick first - as it was taken, with what the match is doing -, then minute by minute,
 * the live figures, the pre-match reading as a reference and the in-play prices. At a desk the events and the reading on
 * the left, the picks, figures and prices at the side (three picks or more take the main column's top).
 */
function InPlay({ ctx }: { ctx: MatchCtx }) {
  const wide = useWidePicks(ctx);
  const picks: OrderedBlock = { key: "picks", node: <PicksTab ctx={ctx} />, order: 1 };
  return (
    <div className="space-y-4">
      <OrderedColumns
        testId="summary-live"
        main={[
          ...(wide ? [picks] : []),
          { key: "events", node: <EventsBlock ctx={ctx} />, order: 2 },
          { key: "analysis", node: <AnalysisBlock ctx={ctx} variant="reference" />, order: 4 },
        ]}
        side={[
          ...(wide ? [] : [picks]),
          { key: "stats", node: <KeyStatsBlock ctx={ctx} />, order: 3 },
          { key: "odds", node: <LiveOddsBlock ctx={ctx} />, order: 5 },
        ]}
      />
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
