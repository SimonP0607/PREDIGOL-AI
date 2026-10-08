/**
 * Resumen, by the match's state:
 * before kick-off - picks, best prices, form, table, head to head, absences, line-ups;
 * in play        - events, key figures, in-play prices, then the context folded away;
 * after          - result, events, key figures, then the context folded away.
 */
import { useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, CalendarX2, ChevronDown, Flag, Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import type { PickCard as PickCardData } from "@/lib/api/v1/types_product";
import { PickCard } from "@/product/shared/PickCard";
import { ShadowBadge } from "@/product/shared/Bits";
import { Card, EmptyState, ErrorState, SkeletonBlock } from "@/product/shared/States";
import { AnalysisBlock } from "./AnalysisBlock";
import type { MatchCtx } from "./context";
import { AbsencesBlock, FormBlock, H2HBlock, LineupsTeaser, StandingsBlock } from "./ContextBlocks";
import { EventsBlock } from "./EventsTimeline";
import { KEY_STATS, statRows } from "./model";
import { LiveOddsBlock, QuickPricesBlock } from "./prices";
import { Block, CenterSection, MoreButton, StatBars, TeamsLegend } from "./ui";

// ── Picks ───────────────────────────────────────────────────────────────────

const PICKS_SHOWN = 2;

/** Qualified picks for this match (the admin's labelled shadow preview when it is on). */
function PicksBlock({ ctx }: { ctx: MatchCtx }) {
  const preview = usePreviewParam();
  const q = useQuery(live.productPicks({ hours: 168 }, preview));
  const [all, setAll] = useState(false);
  const board = q.data?.data;
  const id = Number(ctx.fixtureId);
  const seen = new Set<number>();
  const picks: PickCardData[] = [...(board?.top ?? []), ...(board?.picks ?? [])].filter((p) => {
    if (p.fixture_id !== id || seen.has(p.pick_id)) return false;
    seen.add(p.pick_id);
    return true;
  });
  // Keep the board's own order (value now first, then expected value).
  const order = new Map((board?.picks ?? []).map((p, i) => [p.pick_id, i]));
  picks.sort((a, b) => (order.get(a.pick_id) ?? -1) - (order.get(b.pick_id) ?? -1));
  const rankOf = new Map((board?.top ?? []).map((p, i) => [p.pick_id, i + 1]));
  const shadow = board?.source === "shadow_preview";
  const shown = all ? picks : picks.slice(0, PICKS_SHOWN);

  return (
    <Block
      title={t("match.picks.title")}
      icon={<Target />}
      right={shadow ? <ShadowBadge /> : null}
      className={cn(shadow && "border-info/40")}
    >
      {q.isPending ? (
        <SkeletonBlock className="h-32" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-5" />
      ) : picks.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-empty-state>
          {shadow ? t("match.picks.noneShadow") : t("match.picks.none")}
        </p>
      ) : (
        <div className="space-y-2">
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-1">
            {shown.map((p) => (
              <PickCard key={p.pick_id} pick={p} rank={rankOf.get(p.pick_id)} shadow={shadow} />
            ))}
          </div>
          {picks.length > PICKS_SHOWN ? (
            <MoreButton expanded={all} onClick={() => setAll((v) => !v)}>
              {all ? t("match.picks.showLess") : t("match.picks.showAll", { count: picks.length })}
            </MoreButton>
          ) : null}
        </div>
      )}
    </Block>
  );
}

// ── Result and key figures ──────────────────────────────────────────────────

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-elevated/40 px-3 py-2">
      <dt className="truncate text-caption text-muted-foreground">{label}</dt>
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
        <PicksBlock ctx={ctx} />
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
        </div>
        <div className="min-w-0 space-y-4">
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
          <EventsBlock ctx={ctx} />
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
  const postponed = ctx.phase === "postponed";
  return (
    <div className="space-y-4">
      <Card>
        <EmptyState
          icon={<CalendarX2 aria-hidden className="h-6 w-6" />}
          title={postponed ? t("match.notPlayed.postponed") : t("match.notPlayed.cancelled")}
          body={postponed ? t("match.notPlayed.postponedBody") : t("match.notPlayed.cancelledBody")}
        />
      </Card>
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
      return <NotPlayed ctx={ctx} />;
    default:
      return <AfterMatch ctx={ctx} />;
  }
}
