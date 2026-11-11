/**
 * IA e investigación (Admin Console): the AI's own day, read-only, in cards and chips - the views plan F13 gathered into two pages (see adminAi.ts).
 *
 * OPERACIÓN holds
 *   TodayTab     today's matches with a market (Bogotá): the passes done, the L1 brief, the reviewed selections
 *   ResearchTab  per match, the web searches and the evidence with its source, level, status and dates
 *   SourcesTab   which domains brought useful evidence, over 7 or 30 days
 * APRENDIZAJE holds
 *   CloseTab     the close of each day: the picks settled, the post-mortems and the revisions
 *
 * What a day's results taught and the improvements awaiting the owner are in Aprendizaje > Lo aprendido (the owner decides there); the costs are
 * one view with the rest of the AI's costs (AiCosts). The post-mortems and the memory are in Aprendizaje too. Nothing here calls a model or changes
 * anything: everything was stored by the worker.
 */
import { useState, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronDown, ExternalLink } from "lucide-react";
import { t, translateOr } from "@/lib/i18n";
import { formatOdds, localInt } from "@/lib/i18n/format";
import { int } from "@/lib/format";
import { shiftDay } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  AiClaim,
  AiDayBrief,
  AiDayFixture,
  AiPassRow,
  AiResearchEvidence,
  AiResearchRow,
  AiToday,
  EvidenceStatus,
} from "@/lib/api/v1/types_ai_layer";
import { Choice, DayInput, EngineBadge, Note, Stat, StatGrid, SubTitle, Toolbar } from "./AiBits";
import {
  EVIDENCE_TONE,
  PASSES,
  STALE_ODDS_MINUTES,
  bogotaDateTime,
  bogotaTime,
  dayLabel,
  decisionLabel,
  decisionTone,
  edgePoints,
  minutesText,
  passLabel,
  pointsText,
  probText,
  reasonLabel,
  selectionText,
  teamsOf,
  usd,
} from "./aiModel";
import { DailyReviewPanel } from "./DailyReviewPanel";
import { Fact } from "./shared";

const EVIDENCE_STATUSES: EvidenceStatus[] = [
  "CONFIRMED",
  "PROBABLE",
  "RUMOR",
  "CONTRADICTORY",
  "OUTDATED",
];
const SOURCE_DAYS = [7, 30] as const;
const UNCERTAINTY_TONE: Record<string, BadgeTone> = {
  low: "positive",
  medium: "neutral",
  high: "warning",
};
const QUALITY_TONE: Record<string, BadgeTone> = {
  good: "positive",
  fair: "neutral",
  poor: "warning",
};
const INJURY_TONE: Record<string, BadgeTone> = {
  out: "negative",
  doubtful: "warning",
  returns: "positive",
  starts: "positive",
};
// ── small pieces ─────────────────────────────────────────────────────────────

/** A card that opens: the summary always visible, the detail on demand. */
function Fold({
  summary,
  children,
  testId,
}: {
  summary: ReactNode;
  children: ReactNode;
  testId: string;
}) {
  return (
    <details className="group min-w-0 rounded-md border border-border bg-card" data-testid={testId}>
      <summary className="flex cursor-pointer list-none items-start gap-3 rounded-md px-3 py-2.5 transition-colors hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <span className="block min-w-0 flex-1">{summary}</span>
        <ChevronDown
          aria-hidden
          className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="space-y-4 border-t border-border px-3 py-3">{children}</div>
    </details>
  );
}

function Loading({ show }: { show: boolean }) {
  return show ? <TableSkeleton rows={4} cols={4} /> : null;
}

function ClaimList({ claims }: { claims: AiClaim[] }) {
  return (
    <ul className="space-y-1">
      {claims.map((c, i) => (
        <li key={i} className="flex flex-wrap items-start gap-1.5 text-xs">
          <StatusBadge
            tone={c.type === "DATA" ? "positive" : c.type === "NEWS" ? "info" : "neutral"}
            dot={false}
          >
            {translateOr(`ai.layer.claimType.${c.type}`, c.type)}
          </StatusBadge>
          <span className="min-w-0 flex-1 wrap-anywhere">{c.text}</span>
        </li>
      ))}
    </ul>
  );
}

// ── HOY ──────────────────────────────────────────────────────────────────────

function DayHeader({ d }: { d: AiToday }) {
  const opened = d.plan?.stages["opened"];
  return (
    <Panel
      title={t("ai.research.today.title")}
      subtitle={t("ai.research.today.subtitle", { day: dayLabel(d.day) })}
    >
      <StatGrid className="xl:grid-cols-7" testId="ai-today-header">
        <Stat label={t("ai.research.today.withMarket")} value={int(d.totals.with_market)} />
        <Stat
          label={t("ai.research.today.withoutMarket")}
          value={int(d.without_market)}
          tone="muted"
        />
        <Stat label={t("ai.research.today.passes")} value={int(d.totals.passes)} />
        <Stat
          label={t("ai.research.today.escalated")}
          value={int(d.totals.escalated)}
          tone={d.totals.escalated > 0 ? "warning" : "default"}
        />
        <Stat
          label={t("ai.research.today.staleOdds")}
          value={int(d.totals.stale_odds)}
          tone={d.totals.stale_odds > 0 ? "warning" : "default"}
        />
        <Stat label={t("ai.research.today.cost")} value={usd(d.totals.cost_usd)} />
        <Stat
          label={t("ai.research.today.planOpened")}
          value={opened ? bogotaTime(opened.created_at) : t("ai.research.today.planNotOpened")}
          tone={opened ? "default" : "muted"}
        />
      </StatGrid>
    </Panel>
  );
}

/** One pass done: "PRIMERA (00:05) · 00:09 · US$ 0,0123" (amber when it escalated the match). */
function PassChip({ p }: { p: AiPassRow }) {
  const reasons = p.reasons.map(reasonLabel).join(" · ");
  return (
    <span title={reasons || undefined}>
      <StatusBadge
        tone={p.status !== "ok" ? "negative" : p.escalated ? "warning" : "info"}
        className="normal-case tracking-normal"
      >
        <span className="uppercase tracking-wider">{passLabel(p.pass)}</span>
        <span aria-hidden className="opacity-60">
          ·
        </span>
        <span className="numeric">{bogotaTime(p.at)}</span>
        <span aria-hidden className="opacity-60">
          ·
        </span>
        <span className="numeric">{usd(p.cost_usd)}</span>
      </StatusBadge>
    </span>
  );
}

function sortedPasses(passes: AiPassRow[]): AiPassRow[] {
  const order: string[] = [...PASSES];
  const rank = (p: string) => (order.indexOf(p) < 0 ? order.length : order.indexOf(p));
  return [...passes].sort((a, b) => rank(a.pass) - rank(b.pass) || a.at.localeCompare(b.at));
}

function BriefBlock({ b, match }: { b: AiDayBrief | null; match: string }) {
  if (!b) return <Note>{t("ai.research.today.noBrief")}</Note>;
  const teams = teamsOf(match);
  const side = (s: string) =>
    s === "home" ? (teams?.home ?? t("common.home")) : (teams?.away ?? t("common.away"));
  return (
    <section className="space-y-2.5" data-testid="ai-brief">
      <div className="flex flex-wrap items-center gap-1.5">
        <SubTitle>{t("ai.research.today.brief")}</SubTitle>
        <EngineBadge engine={b.engine} />
        {b.model ? (
          <span className="numeric text-caption text-muted-foreground wrap-anywhere">
            {b.model}
          </span>
        ) : null}
        <span className="text-caption text-subtle-foreground">
          {passLabel(b.pass)} · {bogotaTime(b.created_at)}
        </span>
      </div>
      {b.summary ? <p className="text-sm leading-relaxed wrap-anywhere">{b.summary}</p> : null}
      {b.uncertainty || b.data_quality ? (
        <div className="flex flex-wrap gap-1.5">
          {b.uncertainty ? (
            <StatusBadge tone={UNCERTAINTY_TONE[b.uncertainty] ?? "neutral"}>
              {translateOr(`ai.v2.uncertainty.${b.uncertainty}`, b.uncertainty)}
            </StatusBadge>
          ) : null}
          {b.data_quality ? (
            <StatusBadge tone={QUALITY_TONE[b.data_quality] ?? "neutral"}>
              {translateOr(`ai.v2.quality.${b.data_quality}`, b.data_quality)}
            </StatusBadge>
          ) : null}
        </div>
      ) : null}
      {b.reasons.length ? (
        <div className="space-y-1">
          <SubTitle>{t("ai.research.today.reasons")}</SubTitle>
          <ul className="flex flex-wrap gap-1.5">
            {b.reasons.map((r) => (
              <li key={r}>
                <StatusBadge tone="warning" dot={false}>
                  {reasonLabel(r)}
                </StatusBadge>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {b.injuries.length ? (
        <div className="space-y-1">
          <SubTitle>{t("ai.research.today.injuries")}</SubTitle>
          <ul className="space-y-1">
            {b.injuries.map((i, k) => (
              <li key={`${i.player}-${k}`} className="flex flex-wrap items-center gap-1.5 text-xs">
                <StatusBadge tone={INJURY_TONE[i.status] ?? "neutral"} dot={false}>
                  {translateOr(`ai.v2.injury.${i.status}`, i.status)}
                </StatusBadge>
                <span className="wrap-anywhere">{i.player}</span>
                <span className="text-caption text-subtle-foreground">{side(i.side)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {b.changes.length ? (
        <div className="space-y-1">
          <SubTitle>{t("ai.research.today.changes")}</SubTitle>
          <ClaimList claims={b.changes} />
        </div>
      ) : null}
      {b.context.length ? (
        <details className="group">
          <summary className="cursor-pointer list-none text-caption font-medium uppercase tracking-wider text-subtle-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
            {t("ai.research.today.context")} ({localInt(b.context.length)})
          </summary>
          <div className="mt-1.5">
            <ClaimList claims={b.context} />
          </div>
        </details>
      ) : null}
    </section>
  );
}

function SelectionsBlock({ f }: { f: AiDayFixture }) {
  if (!f.selections.length) return <Note>{t("ai.research.today.noSelections")}</Note>;
  return (
    <section className="space-y-1.5">
      <SubTitle>{t("ai.research.today.selections")}</SubTitle>
      <ul className="divide-y divide-border/60 rounded-md border border-border">
        {f.selections.map((s) => {
          const edge = edgePoints(s.edge, s.p_model, s.p_market);
          return (
            <li key={s.review_id} className="space-y-1 px-3 py-2" data-testid="ai-day-selection">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="min-w-0 text-xs font-medium wrap-anywhere">
                  {selectionText(s.market, s.selection, s.line, f.match)}
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  {s.by_llm ? (
                    <StatusBadge tone="brand" dot={false}>
                      {t("ai.v2.engine.llm")}
                    </StatusBadge>
                  ) : null}
                  <StatusBadge tone={decisionTone(s.decision)}>
                    {decisionLabel(s.decision)}
                  </StatusBadge>
                </span>
              </div>
              <dl className="grid grid-cols-4 gap-x-2">
                <Fact label={t("ai.research.today.odds")} value={formatOdds(s.odds)} />
                <Fact label={t("ai.research.today.model")} value={probText(s.p_model)} />
                <Fact label={t("ai.research.today.market")} value={probText(s.p_market)} />
                <Fact
                  label={t("ai.research.today.edge")}
                  value={
                    <span
                      className={cn(
                        edge !== null && edge > 0 && "text-positive",
                        edge !== null && edge < 0 && "text-negative",
                      )}
                    >
                      {pointsText(edge)}
                    </span>
                  }
                />
              </dl>
              {s.reason ? (
                <p
                  className="line-clamp-2 text-caption text-muted-foreground wrap-anywhere"
                  title={s.reason}
                >
                  {s.reason}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function FixtureCard({ f }: { f: AiDayFixture }) {
  const stale = f.odds_age_minutes !== null && f.odds_age_minutes > STALE_ODDS_MINUTES;
  const escalated = Boolean(f.brief?.escalate) || f.passes.some((p) => p.escalated);
  const passes = sortedPasses(f.passes);
  const tally = new Map<string, number>();
  for (const s of f.selections) tally.set(s.decision, (tally.get(s.decision) ?? 0) + 1);
  return (
    <Fold
      testId="ai-day-fixture"
      summary={
        <span className="block space-y-1.5">
          <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <span className="min-w-0 text-sm font-medium wrap-anywhere">{f.match}</span>
            <span className="numeric text-xs text-muted-foreground">
              {bogotaTime(f.kickoff_at)}
            </span>
          </span>
          <span className="block text-caption text-subtle-foreground wrap-anywhere">
            {f.competition}
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            {f.important ? (
              <StatusBadge tone="brand">{t("ai.research.today.important")}</StatusBadge>
            ) : null}
            {escalated ? (
              <StatusBadge tone="warning">{t("ai.research.today.escalate")}</StatusBadge>
            ) : null}
            {stale ? (
              <StatusBadge tone="warning">
                {t("ai.research.today.staleChip", { age: minutesText(f.odds_age_minutes) })}
              </StatusBadge>
            ) : null}
            {passes.length ? (
              passes.map((p) => <PassChip key={`${p.pass}-${p.at}`} p={p} />)
            ) : (
              <StatusBadge dot={false}>
                {t(
                  Date.parse(f.kickoff_at) <= Date.now()
                    ? "ai.research.today.noPassesPast"
                    : "ai.research.today.noPasses",
                )}
              </StatusBadge>
            )}
            {[...tally].map(([d, n]) => (
              <StatusBadge key={d} tone={decisionTone(d)}>
                {decisionLabel(d)} <span className="numeric">{localInt(n)}</span>
              </StatusBadge>
            ))}
            <span className="numeric text-caption text-muted-foreground">
              {t("ai.research.today.matchCost", { cost: usd(f.cost_usd) })}
            </span>
          </span>
        </span>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <BriefBlock b={f.brief} match={f.match} />
        <SelectionsBlock f={f} />
      </div>
      <Link
        to="/matches/$fixtureId"
        params={{ fixtureId: String(f.fixture_id) }}
        className="tap-y relative inline-flex text-xs font-medium text-primary hover:underline"
      >
        {t("ai.research.today.openMatch")} →
      </Link>
    </Fold>
  );
}

export function TodayTab({
  day,
  onDay,
  max,
}: {
  day: string;
  onDay: (d: string) => void;
  max: string;
}) {
  const q = useLiveQuery(live.aiToday(day));
  const d = q.data?.data ?? null;
  return (
    <div className="space-y-3">
      <Toolbar>
        <DayInput value={day} onChange={onDay} label={t("ai.research.day")} max={max} />
      </Toolbar>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <Loading show={q.isLoading} />
      {d ? (
        <>
          <DayHeader d={d} />
          {d.fixtures.length === 0 ? (
            <Note>{t("ai.research.today.empty")}</Note>
          ) : (
            <ul className="space-y-2" data-testid="ai-today-fixtures">
              {d.fixtures.map((f) => (
                <li key={f.fixture_id}>
                  <FixtureCard f={f} />
                </li>
              ))}
            </ul>
          )}
        </>
      ) : null}
    </div>
  );
}

// ── INVESTIGACIONES ──────────────────────────────────────────────────────────

function EvidenceCard({ e }: { e: AiResearchEvidence }) {
  const dates: Array<[string, string]> = [
    [
      t("ai.research.investigations.published"),
      e.published_at ? bogotaDateTime(e.published_at) : "—",
    ],
    [t("ai.research.investigations.retrieved"), bogotaDateTime(e.retrieved_at)],
    [
      t("ai.research.investigations.lastSeen"),
      e.last_seen_at ? bogotaDateTime(e.last_seen_at) : "—",
    ],
  ];
  return (
    <li
      className="min-w-0 space-y-1.5 rounded-md border border-border p-2.5"
      data-testid="ai-evidence"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={EVIDENCE_TONE[e.status] ?? "neutral"}>
          {translateOr(`ai.layer.evidenceStatus.${e.status}`, e.status)}
        </StatusBadge>
        <StatusBadge dot={false}>
          {translateOr(`ai.layer.evidenceKind.${e.kind}`, e.kind)}
        </StatusBadge>
        <StatusBadge dot={false}>
          {translateOr(`ai.research.investigations.origin.${e.origin}`, e.origin)}
        </StatusBadge>
        {e.team || e.player ? (
          <span className="text-caption text-muted-foreground wrap-anywhere">
            {[e.team, e.player].filter(Boolean).join(" · ")}
          </span>
        ) : null}
      </div>
      <p className="text-xs leading-relaxed wrap-anywhere">{e.claim}</p>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption">
        {e.url ? (
          <a
            href={e.url}
            target="_blank"
            rel="noopener noreferrer"
            title={e.title ?? undefined}
            className="inline-flex min-w-0 items-center gap-1 font-medium text-primary hover:underline wrap-anywhere"
          >
            {e.source}
            <ExternalLink aria-hidden className="h-3 w-3 shrink-0" />
            <span className="sr-only">{t("ai.research.investigations.newTab")}</span>
          </a>
        ) : (
          <span className="font-medium text-foreground/85">{e.source}</span>
        )}
        {e.domain ? (
          <span className="numeric text-subtle-foreground wrap-anywhere">{e.domain}</span>
        ) : null}
        <StatusBadge dot={false}>{translateOr(`ai.layer.tierName.${e.tier}`, e.tier)}</StatusBadge>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-caption text-subtle-foreground">
        <dl className="flex flex-wrap gap-x-3 gap-y-0.5">
          {dates.map(([label, value]) => (
            <div key={label} className="flex gap-1">
              <dt>{label}:</dt>
              <dd className="numeric text-muted-foreground">{value}</dd>
            </div>
          ))}
        </dl>
        <span className="numeric text-muted-foreground">
          {t("ai.research.investigations.seen", {
            count: e.seen_count,
            n: localInt(e.seen_count),
          })}
        </span>
      </div>
      {e.status_reason ? (
        <p className="text-caption text-subtle-foreground wrap-anywhere">{e.status_reason}</p>
      ) : null}
    </li>
  );
}

function ResearchCard({ r }: { r: AiResearchRow }) {
  const byStatus = new Map<string, number>();
  for (const e of r.evidence) byStatus.set(e.status, (byStatus.get(e.status) ?? 0) + 1);
  return (
    <Fold
      testId="ai-research-row"
      summary={
        <span className="block space-y-1.5">
          <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <span className="min-w-0 text-sm font-medium wrap-anywhere">{r.match}</span>
            <span className="numeric text-xs text-muted-foreground">
              {bogotaDateTime(r.kickoff_at)}
            </span>
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            <StatusBadge dot={false}>
              {t("ai.research.investigations.searchCount", {
                count: r.searches.length,
                n: localInt(r.searches.length),
              })}
            </StatusBadge>
            <StatusBadge tone="info" dot={false}>
              {t("ai.research.investigations.evidenceCount", {
                count: r.evidence.length,
                n: localInt(r.evidence.length),
              })}
            </StatusBadge>
            {EVIDENCE_STATUSES.filter((s) => byStatus.get(s)).map((s) => (
              <StatusBadge key={s} tone={EVIDENCE_TONE[s]}>
                {t(`ai.layer.evidenceStatus.${s}`)}{" "}
                <span className="numeric">{localInt(byStatus.get(s) ?? 0)}</span>
              </StatusBadge>
            ))}
            <span className="numeric text-caption text-muted-foreground">
              {t("ai.research.today.matchCost", { cost: usd(r.cost_usd) })}
            </span>
          </span>
        </span>
      }
    >
      <section className="space-y-1.5">
        <SubTitle>{t("ai.research.investigations.searches")}</SubTitle>
        {r.searches.length === 0 ? (
          <Note>{t("ai.research.investigations.noSearches")}</Note>
        ) : (
          <ul className="space-y-1">
            {r.searches.map((s, i) => (
              <li key={`${s.at}-${i}`} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="numeric text-muted-foreground">{bogotaTime(s.at)}</span>
                <StatusBadge tone={s.status === "ok" ? "positive" : "negative"}>
                  {translateOr(`ai.research.investigations.searchStatus.${s.status}`, s.status)}
                </StatusBadge>
                <span className="numeric text-muted-foreground">{usd(s.cost_usd)}</span>
                {s.error ? (
                  <span className="min-w-0 text-caption text-negative wrap-anywhere">
                    {s.error}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="space-y-1.5">
        <SubTitle>{t("ai.research.investigations.evidence")}</SubTitle>
        {r.evidence.length === 0 ? (
          <Note>{t("ai.research.investigations.noEvidence")}</Note>
        ) : (
          <ul className="space-y-2">
            {r.evidence.map((e) => (
              <EvidenceCard key={e.id} e={e} />
            ))}
          </ul>
        )}
      </section>
    </Fold>
  );
}

export function ResearchTab({
  day,
  onDay,
  max,
}: {
  day: string;
  onDay: (d: string) => void;
  max: string;
}) {
  const q = useLiveQuery(live.aiResearch(day));
  const rows = q.data?.data ?? [];
  return (
    <div className="space-y-3">
      <Toolbar>
        <DayInput value={day} onChange={onDay} label={t("ai.research.day")} max={max} />
      </Toolbar>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <Loading show={q.isLoading} />
      {q.isSuccess && rows.length === 0 ? (
        <Note>{t("ai.research.investigations.empty")}</Note>
      ) : null}
      {rows.length ? (
        <ul className="space-y-2" data-testid="ai-research">
          {rows.map((r) => (
            <li key={r.fixture_id}>
              <ResearchCard r={r} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ── APRENDIZAJE ──────────────────────────────────────────────────────────────

// ── FUENTES ──────────────────────────────────────────────────────────────────

export function SourcesTab() {
  const [days, setDays] = useState<(typeof SOURCE_DAYS)[number]>(7);
  const q = useLiveQuery(live.aiSources(days));
  const rows = q.data?.data ?? [];
  return (
    <div className="space-y-3">
      <Toolbar>
        <Choice
          label={t("ai.research.sources.period")}
          value={String(days)}
          onChange={(v) => setDays(v === "30" ? 30 : 7)}
        >
          <option value="7">{t("ai.research.sources.last7")}</option>
          <option value="30">{t("ai.research.sources.last30")}</option>
        </Choice>
      </Toolbar>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <Panel
        title={t("ai.research.sources.title")}
        subtitle={t("ai.research.sources.subtitle")}
        bodyClassName="p-0"
      >
        {q.isLoading ? <TableSkeleton rows={5} cols={6} /> : null}
        {q.isSuccess && rows.length === 0 ? (
          <Note className="p-4">{t("ai.research.sources.empty")}</Note>
        ) : null}
        {rows.length ? (
          <TableShell>
            <THead>
              <TH>{t("ai.research.sources.cols.domain")}</TH>
              <TH>{t("ai.research.sources.cols.tier")}</TH>
              <TH align="right">{t("ai.research.sources.cols.results")}</TH>
              <TH align="right">{t("ai.research.sources.cols.useful")}</TH>
              <TH align="right">{t("ai.research.sources.cols.discarded")}</TH>
              <TH align="right">{t("ai.research.sources.cols.cost")}</TH>
              <TH align="right">{t("ai.research.sources.cols.utility")}</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={r.domain}>
                  <TD className="numeric whitespace-nowrap text-xs">{r.domain}</TD>
                  <TD className="whitespace-nowrap text-xs">
                    {translateOr(`ai.layer.tierName.${r.tier}`, r.tier)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {int(r.results)}
                  </TD>
                  <TD align="right" className="numeric text-xs text-positive">
                    {int(r.useful)}
                  </TD>
                  <TD align="right" className="numeric text-xs text-muted-foreground">
                    {int(r.discarded)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {usd(r.cost_usd)}
                  </TD>
                  <TD align="right" className="numeric text-xs font-medium">
                    {probText(r.utility, 0)}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        ) : null}
      </Panel>
    </div>
  );
}

// ── the page ─────────────────────────────────────────────────────────────────

/** CIERRE DIARIO: the closed days, newest first, and one day's close with its revisions. */
export function CloseTab({
  day,
  onDay,
  max,
}: {
  day: string;
  onDay: (d: string) => void;
  max: string;
}) {
  const q = useLiveQuery(live.aiDailyReviews(30));
  const days = q.data?.data ?? [];
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2.2fr)]">
      <Panel title={t("ai.dailyReview.history")}>
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {q.isSuccess && days.length === 0 ? <Note>{t("ai.dailyReview.historyEmpty")}</Note> : null}
        <ul className="space-y-1" data-testid="daily-review-history">
          {days.map((d) => (
            <li key={d.day}>
              <button
                type="button"
                onClick={() => onDay(d.day)}
                className={cn(
                  "w-full rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-elevated",
                  d.day === day ? "border-primary/50 bg-primary/5" : "border-border",
                )}
              >
                <span className="numeric font-medium">{d.day}</span>{" "}
                {d.complete ? null : (
                  <span className="text-warning">· {t("ai.dailyReview.open", { count: 1 })}</span>
                )}
                <span className="block text-muted-foreground">
                  {t("ai.dailyReview.historyRow", {
                    played: d.played,
                    matches: d.matches,
                    won: d.daily_won,
                    lost: d.daily_lost,
                    pending: d.daily_pending,
                    pnl: `${d.daily_pnl_units > 0 ? "+" : ""}${d.daily_pnl_units.toFixed(2)} u`,
                    cost: usd(d.ai_usd),
                  })}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
      <DailyReviewPanel
        day={day}
        onDay={onDay}
        max={max}
        title={day === shiftDay(max, -1) ? t("ai.dailyReview.yesterday") : undefined}
      />
    </div>
  );
}
