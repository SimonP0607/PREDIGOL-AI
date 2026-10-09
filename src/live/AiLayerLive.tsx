/**
 * La capa de decisión IA (Admin Console). On top: the month's budget (adaptive daily budget, projection,
 * the 70/85/95/100 % alerts), the models of each level as configured (never a key), today's efficiency and
 * the experimental comparison (model alone, model + rules, model + AI, market) - everything in shadow until
 * the owner's switch AND a passed gate. Then the mode, the last cycles and the owner's "run now", and the
 * views: the reviews with their whole audit trail, the evidence with its sources, what it costs (measured,
 * per unit, per level, and simulated per provider), the AI's own shadow evaluation and its memory.
 */
import { useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { t, translateOr } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { int } from "@/lib/format";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  AiClaim,
  AiComparisonRow,
  AiCostPeriod,
  AiDecision,
  AiEfficiency,
  AiOverview,
  AiReviewDetail,
  EvidenceStatus,
  ShadowArm,
  ShadowReportRow,
} from "@/lib/api/v1/types_ai_layer";
import {
  LevelBadge,
  MonthBar,
  Note,
  ShadowBanner,
  Stat,
  StatGrid,
  SubTitle,
  type StatTone,
} from "./AiBits";
import {
  DECISION_TONE,
  EVIDENCE_TONE,
  LEVELS,
  budgetTone,
  fixedText,
  gateTone,
  levelLabel,
  levelRows,
  pct,
  probText,
  ratioOf,
  sampleCounts,
  signedText,
  toNum,
  usd,
} from "./aiModel";
import { utcDateTime } from "./format";

const TABS = ["reviews", "evidence", "costs", "shadow", "memory"] as const;
type Tab = (typeof TABS)[number];
const DECISIONS: AiDecision[] = ["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"];
const STATUSES: EvidenceStatus[] = ["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"];
const ARMS = ["model", "model_ai", "approved", "downgraded", "rejected", "abstained"] as const;
const COMPARISON_ARMS = ["model", "model_rules", "model_ai", "market"] as const;
const CLAIM_GROUPS = [
  "positive_evidence",
  "negative_evidence",
  "uncertainties",
  "contradictions",
] as const;
const SELECT =
  "h-8 rounded-md border border-border bg-card px-2 text-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";
/** The comparison grid: the arm, then nine figures. */
const COMPARE_GRID = "grid grid-cols-[minmax(8.5rem,1.5fr)_repeat(9,minmax(4.25rem,1fr))]";

function percent(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined ? "—" : `${localFixed(100 * n, digits)} %`;
}

// ── budget, models, efficiency, comparison (above the views) ─────────────────

/**
 * Presupuesto mensual, gastado hoy y este mes, lo que queda, el presupuesto de hoy (adaptable, con su objetivo
 * blando y su tope), la proyección del mes al ritmo de los últimos 7 días, el estado y la barra del mes.
 */
function BudgetCard({ o }: { o: AiOverview }) {
  const b = o.budget;
  const p = o.projection;
  const monthly = toNum(b.monthly_budget_usd);
  const spentMonth = toNum(b.spent_month_usd);
  const remaining =
    toNum(b.remaining_month_usd) ??
    (monthly !== null && spentMonth !== null ? Math.max(0, monthly - spentMonth) : null);
  const share = p ? (p.projected_share ?? ratioOf(p.projected_month_usd, monthly)) : null;
  const projectionTone: StatTone =
    share === null ? "default" : share > 1 ? "negative" : share >= 0.85 ? "warning" : "default";
  const daysLeft = b.days_left ?? p?.days_left;
  const help = translateOr(`ai.layer.budgetCard.stateHelp.${b.state}`, "");
  const load = toNum(b.load);
  return (
    <Panel
      title={t("ai.layer.budgetCard.title")}
      subtitle={
        daysLeft === undefined
          ? t("ai.layer.budgetCard.subtitleShort")
          : t("ai.layer.budgetCard.subtitle", { days: localInt(daysLeft) })
      }
    >
      <div className="space-y-4" data-testid="ai-budget-card">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <StatusBadge tone={budgetTone(b.state)}>
            {translateOr(`ai.layer.budget.${b.state}`, b.state)}
          </StatusBadge>
          {help ? <span className="text-xs text-muted-foreground">{help}</span> : null}
        </div>
        <StatGrid className="lg:grid-cols-3">
          <Stat label={t("ai.layer.budgetCard.monthly")} value={usd(b.monthly_budget_usd)} />
          <Stat label={t("ai.layer.budgetCard.spentToday")} value={usd(b.spent_today_usd)} />
          <Stat label={t("ai.layer.budgetCard.spentMonth")} value={usd(b.spent_month_usd)} />
          <Stat label={t("ai.layer.budgetCard.remaining")} value={usd(remaining)} />
          <Stat
            label={t("ai.layer.budgetCard.today")}
            value={usd(b.daily_budget_usd)}
            hint={t("ai.layer.budgetCard.todayHint", {
              target: usd(b.daily_target_usd ?? o.settings.daily_target_usd),
              cap: usd(b.daily_cap_usd),
            })}
          />
          <Stat
            label={t("ai.layer.budgetCard.projection")}
            value={usd(p?.projected_month_usd)}
            tone={projectionTone}
            hint={
              share === null
                ? t("ai.layer.budgetCard.projectionNone")
                : t("ai.layer.budgetCard.projectionHint", { share: probText(share, 0) })
            }
          />
        </StatGrid>
        <MonthBar spent={b.spent_month_usd} budget={b.monthly_budget_usd} alerts={o.alerts ?? []} />
        {b.pace_usd !== undefined && load !== null ? (
          <Note>
            {t("ai.layer.budgetCard.adaptive", {
              pace: usd(b.pace_usd),
              load: localFixed(load, 2),
            })}
          </Note>
        ) : null}
      </div>
    </Panel>
  );
}

/** The models of each level and the search API, as the server is configured (never a key), and the caps. */
function StackCard({ o }: { o: AiOverview }) {
  const rows = o.stack ?? [];
  const s = o.settings;
  const caps = [
    t("ai.layer.stack.capReviews", { n: int(s.max_llm_reviews_per_day) }),
    t("ai.layer.stack.capDeep", { n: int(s.max_deep_per_day) }),
    ...(s.max_web_first !== undefined && s.max_web_pre !== undefined
      ? [t("ai.layer.stack.capWeb", { first: int(s.max_web_first), pre: int(s.max_web_pre) })]
      : []),
  ];
  return (
    <Panel title={t("ai.layer.stack.title")} subtitle={t("ai.layer.stack.subtitle")}>
      {rows.length === 0 ? (
        <Note>{t("ai.layer.stack.empty")}</Note>
      ) : (
        <ul className="space-y-3" data-testid="ai-stack">
          {rows.map((r) => (
            <li key={`${r.level}-${r.tier}`} className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <LevelBadge level={r.level} />
                <span className="numeric min-w-0 text-xs wrap-anywhere">
                  {r.model
                    ? r.provider && r.provider !== r.model
                      ? `${r.provider} · ${r.model}`
                      : r.model
                    : "—"}
                </span>
                <StatusBadge tone={r.configured ? "positive" : "warning"}>
                  {r.configured
                    ? t("ai.layer.stack.configured")
                    : t("ai.layer.stack.notConfigured")}
                </StatusBadge>
              </div>
              <p className="text-caption text-muted-foreground">{r.role}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 space-y-1.5 border-t border-border pt-3">
        <SubTitle>{t("ai.layer.stack.caps")}</SubTitle>
        <ul className="flex flex-wrap gap-1.5">
          {caps.map((c) => (
            <li key={c}>
              <StatusBadge dot={false}>{c}</StatusBadge>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

/** PARTIDOS CON MERCADO HOY, ANALIZADOS, ANÁLISIS PROFUNDOS, CANDIDATOS, PICKS APROBADOS and what each cost. */
function EfficiencyPanel({ e }: { e: AiEfficiency | undefined }) {
  return (
    <Panel title={t("ai.layer.efficiency.title")} subtitle={t("ai.layer.efficiency.subtitle")}>
      {!e ? (
        <Note>{t("ai.layer.efficiency.empty")}</Note>
      ) : (
        <StatGrid className="xl:grid-cols-6" testId="ai-efficiency">
          <Stat
            label={t("ai.layer.efficiency.withMarket")}
            value={int(e.with_market)}
            hint={t("ai.layer.efficiency.withMarketHint", { total: int(e.matches_today) })}
          />
          <Stat
            label={t("ai.layer.efficiency.analyzed")}
            value={int(e.analyzed)}
            hint={t("ai.layer.efficiency.analyzedHint", {
              llm: int(e.briefs_llm),
              rules: int(e.briefs_rules),
            })}
          />
          <Stat label={t("ai.layer.efficiency.deep")} value={int(e.deep)} />
          <Stat label={t("ai.layer.efficiency.candidates")} value={int(e.candidates)} />
          <Stat
            label={t("ai.layer.efficiency.approved")}
            value={int(e.approved)}
            tone={e.approved > 0 ? "positive" : "default"}
            hint={t("ai.layer.efficiency.approvedHint", {
              caution: int(e.caution),
              rejected: int(e.rejected),
              abstained: int(e.abstained),
            })}
          />
          <Stat label={t("ai.layer.efficiency.cost")} value={usd(e.cost_usd)} />
          <Stat label={t("ai.layer.efficiency.costPerMatch")} value={usd(e.cost_per_match)} />
          <Stat
            label={t("ai.layer.efficiency.costPerCandidate")}
            value={usd(e.cost_per_candidate)}
          />
          <Stat label={t("ai.layer.efficiency.costPerApproved")} value={usd(e.cost_per_approved)} />
          <Stat label={t("ai.layer.efficiency.escalated")} value={int(e.escalated)} />
          <Stat label={t("ai.layer.efficiency.intermediate")} value={int(e.intermediate)} />
          <Stat
            label={t("ai.layer.efficiency.searches")}
            value={int(e.searches)}
            hint={t("ai.layer.efficiency.searchesHint", { news: int(e.news) })}
          />
        </StatGrid>
      )}
    </Panel>
  );
}

function compareCells(r: AiComparisonRow): string[] {
  return [
    int(r.n),
    fixedText(r.logloss, 3),
    fixedText(r.brier, 3),
    probText(r.ece, 1),
    signedText(r.roi, 1),
    signedText(r.clv, 1),
    signedText(r.ev_market, 1),
    probText(r.hit_rate, 1),
    toNum(r.max_drawdown) === null
      ? "—"
      : t("ai.layer.compare.units", { n: fixedText(r.max_drawdown, 2) }),
  ];
}

/**
 * MODELO SOLO / MODELO + REGLAS / MODELO + IA / MERCADO on the same settled selections (shadow). A grid with
 * table semantics: it scrolls inside its own box on a phone.
 */
function ComparisonPanel() {
  const q = useLiveQuery(live.aiComparison);
  const c = q.data?.data ?? null;
  const rank = (arm: string) => {
    const i = (COMPARISON_ARMS as readonly string[]).indexOf(arm);
    return i < 0 ? COMPARISON_ARMS.length : i;
  };
  const rows = c ? [...c.rows].sort((a, b) => rank(a.arm) - rank(b.arm)) : [];
  const sample = sampleCounts(c?.sample);
  const headers = [
    t("ai.layer.compare.cols.n"),
    t("ai.layer.compare.cols.logloss"),
    t("ai.layer.compare.cols.brier"),
    t("ai.layer.compare.cols.ece"),
    t("ai.layer.compare.cols.roi"),
    t("ai.layer.compare.cols.clv"),
    t("ai.layer.compare.cols.ev"),
    t("ai.layer.shadow.hit"),
    t("ai.layer.shadow.drawdown"),
  ];
  return (
    <Panel
      title={t("ai.layer.compare.title")}
      subtitle={t("ai.layer.compare.subtitle")}
      actions={c?.shadow ? <StatusBadge tone="brand">{t("ai.v2.shadowBadge")}</StatusBadge> : null}
    >
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={4} cols={6} /> : null}
      {c ? (
        <div className="space-y-3" data-testid="ai-comparison">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-caption text-subtle-foreground">
            <span>{t("ai.layer.compare.gate")}</span>
            <StatusBadge tone={gateTone(c.verdict)}>
              {translateOr(`ai.layer.gate.${c.verdict ?? "none"}`, c.verdict ?? "—")}
            </StatusBadge>
            {c.window_from && c.window_to ? (
              <span className="numeric">
                {t("ai.layer.shadow.window", { from: c.window_from, to: c.window_to })}
              </span>
            ) : null}
            <span className="numeric">
              {t("ai.layer.compare.sample", {
                selections: int(sample.selections),
                days: int(sample.days),
                rejected: int(sample.rejected),
              })}
            </span>
          </div>
          {rows.every((r) => !r.n) ? <Note>{t("ai.layer.compare.empty")}</Note> : null}
          {rows.length ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <div role="table" aria-label={t("ai.layer.compare.title")} className="min-w-[46rem]">
                <div role="rowgroup">
                  <div role="row" className={`${COMPARE_GRID} border-b border-border bg-card`}>
                    <span
                      role="columnheader"
                      className="px-3 py-2 text-label text-subtle-foreground"
                    >
                      {t("ai.layer.shadow.armLabel")}
                    </span>
                    {headers.map((h) => (
                      <span
                        key={h}
                        role="columnheader"
                        className="px-2 py-2 text-right text-label text-subtle-foreground"
                      >
                        {h}
                      </span>
                    ))}
                  </div>
                </div>
                <div role="rowgroup">
                  {rows.map((r) => (
                    <div
                      key={r.arm}
                      role="row"
                      className={`${COMPARE_GRID} border-b border-border/60 text-xs last:border-0 ${
                        r.arm === "market" ? "bg-elevated/40" : ""
                      }`}
                    >
                      <span role="rowheader" className="px-3 py-2.5 font-medium">
                        {translateOr(`ai.layer.compare.arm.${r.arm}`, r.label)}
                      </span>
                      {compareCells(r).map((v, i) => (
                        <span
                          key={headers[i] ?? i}
                          role="cell"
                          className="numeric px-2 py-2.5 text-right"
                        >
                          {v}
                        </span>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
          <Note>
            {t("ai.layer.compare.marketNote")} {t("ai.layer.compare.evNote")}
          </Note>
        </div>
      ) : null}
    </Panel>
  );
}

// ── status ───────────────────────────────────────────────────────────────────

function RunNow() {
  const qc = useQueryClient();
  const run = useMutation({
    mutationFn: (kind: "analysis" | "learning") => v1.requestAiRun({ kind }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["v1", "ai-layer"] }),
  });
  const requests = useLiveQuery(live.aiRunRequests);
  const rows = requests.data?.data ?? [];
  return (
    <Panel title={t("ai.layer.run.title")} subtitle={t("ai.layer.run.subtitle")}>
      <div className="flex flex-wrap gap-2">
        {(["analysis", "learning"] as const).map((k) => (
          <button
            key={k}
            type="button"
            disabled={run.isPending}
            onClick={() => run.mutate(k)}
            className="h-8 rounded-md border border-primary/40 bg-primary/12 px-3 text-xs text-primary disabled:opacity-50"
          >
            {t(`ai.layer.run.${k}`)}
          </button>
        ))}
      </div>
      {run.isError ? <ApiErrorNotice error={run.error} /> : null}
      {rows.length ? (
        <ul
          className="mt-3 space-y-1 text-caption text-subtle-foreground"
          data-testid="ai-run-requests"
        >
          {rows.slice(0, 6).map((r) => (
            <li key={r.id}>
              #{r.id} · {translateOr(`ai.layer.run.${r.kind}`, r.kind)} ·{" "}
              {utcDateTime(r.requested_at)} ·{" "}
              {translateOr(`ai.layer.run.status.${r.status}`, r.status)}
              {r.error ? ` · ${r.error}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </Panel>
  );
}

/** A label and a chip that wrap onto two lines on a phone instead of cutting the chip. */
function ChipRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border/60 py-1.5 last:border-0">
      <span className="text-caption uppercase tracking-wider text-subtle-foreground">{label}</span>
      {children}
    </div>
  );
}

/** The mode and whether it filters anything; the last cycles and today's counts; the owner's "run now". */
function StatusStrip({ o }: { o: AiOverview | null }) {
  return (
    <div className="grid gap-3 lg:grid-cols-3" data-testid="ai-layer-status">
      {o ? (
        <>
          <Panel bodyClassName="p-3 space-y-1">
            <ChipRow label={t("ai.layer.modeLabel")}>
              <StatusBadge tone="info">
                {translateOr(`ai.layer.mode.${o.settings.mode}`, o.settings.mode)}
              </StatusBadge>
            </ChipRow>
            <ChipRow label={t("ai.layer.enforcement")}>
              <StatusBadge tone={o.enforcement.enforced ? "warning" : "neutral"}>
                {o.enforcement.enforced ? t("ai.layer.enforced") : t("ai.layer.notEnforced")}
              </StatusBadge>
            </ChipRow>
            <p className="text-caption text-subtle-foreground">
              {translateOr(
                `ai.layer.enforcementReason.${o.enforcement.reason}`,
                o.enforcement.reason,
              )}
            </p>
            <KeyValue
              label={t("ai.layer.search")}
              value={
                o.settings.search_configured
                  ? (o.settings.search ?? "—")
                  : t("ai.layer.notConfigured")
              }
            />
          </Panel>
          <Panel bodyClassName="p-3 space-y-1">
            {o.last_cycles.length === 0 ? (
              <p className="text-xs text-subtle-foreground">{t("ai.layer.noCycle")}</p>
            ) : (
              o.last_cycles.map((c) => (
                <KeyValue
                  key={c.id}
                  label={translateOr(`ai.layer.cycle.${c.kind}`, c.kind)}
                  value={`${utcDateTime(c.started_at)} · ${translateOr(
                    `ai.layer.cycleStatus.${c.status}`,
                    c.status,
                  )}`}
                />
              ))
            )}
            {Object.entries(o.today).map(([k, v]) => (
              <KeyValue key={k} label={translateOr(`ai.layer.today.${k}`, k)} value={int(v)} />
            ))}
          </Panel>
        </>
      ) : null}
      <RunNow />
    </div>
  );
}

// ── reviews ──────────────────────────────────────────────────────────────────

function ClaimList({ claims }: { claims: AiClaim[] | undefined }) {
  if (!claims || claims.length === 0)
    return <p className="text-caption text-subtle-foreground">—</p>;
  return (
    <ul className="space-y-1">
      {claims.map((c, i) => (
        <li key={i} className="text-xs">
          <StatusBadge
            tone={c.type === "DATA" ? "positive" : c.type === "NEWS" ? "info" : "neutral"}
          >
            {translateOr(`ai.layer.claimType.${c.type}`, c.type)}
          </StatusBadge>{" "}
          {c.text}
          {c.refs && c.refs.length ? (
            <span className="ml-1 text-caption text-subtle-foreground">[{c.refs.join(", ")}]</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function ReviewDetailView({ d }: { d: AiReviewDetail }) {
  const out = d.output;
  return (
    <div className="space-y-3" data-testid="ai-review-detail">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <StatusBadge tone={DECISION_TONE[d.review.decision]}>
          {t(`ai.layer.decision.${d.review.decision}`)}
        </StatusBadge>
        <span className="font-medium">{d.review.match}</span>
        <span className="text-subtle-foreground">
          {d.review.market_key} · {d.review.selection} · {utcDateTime(d.review.reviewed_at)}
        </span>
      </div>
      {out.reason ? <p className="text-sm">{out.reason}</p> : null}
      <div className="grid gap-3 lg:grid-cols-2">
        {CLAIM_GROUPS.map((g) => (
          <div key={g} className="rounded-md border border-border p-2.5">
            <h4 className="mb-1 text-caption uppercase tracking-wider text-subtle-foreground">
              {t(`ai.layer.claims.${g}`)}
            </h4>
            <ClaimList claims={out[g]} />
          </div>
        ))}
      </div>
      {out.rejected_claims && out.rejected_claims.length ? (
        <div className="rounded-md border border-warning/30 bg-warning-soft/40 p-2.5">
          <h4 className="mb-1 text-caption uppercase tracking-wider text-warning">
            {t("ai.layer.claims.rejected")}
          </h4>
          <ul className="space-y-1 text-xs">
            {out.rejected_claims.map((r, i) => (
              <li key={i}>
                «{r.text}» — {r.why}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title={t("ai.layer.audit.engines")} bodyClassName="p-3">
          {d.components.length === 0 ? (
            <p className="text-caption text-subtle-foreground">—</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {d.components.map((c) => (
                <li key={c.id}>
                  {c.engine} · {c.engine_version} · {c.model ?? "—"} ·{" "}
                  <StatusBadge tone={DECISION_TONE[c.decision]}>
                    {t(`ai.layer.decision.${c.decision}`)}
                  </StatusBadge>{" "}
                  · {c.status}
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title={t("ai.layer.audit.packet")} bodyClassName="p-3 space-y-1">
          {d.packet ? (
            <>
              <KeyValue
                label={t("ai.layer.audit.hash")}
                value={d.packet.packet_hash.slice(0, 16)}
              />
              <KeyValue label={t("ai.layer.audit.asOf")} value={utcDateTime(d.packet.as_of)} />
              <KeyValue
                label={t("ai.layer.audit.tokens")}
                value={localInt(d.packet.approx_tokens)}
              />
              <KeyValue
                label={t("ai.layer.audit.missing")}
                value={d.packet.missing.length ? d.packet.missing.join(", ") : "—"}
              />
              <details className="text-caption text-subtle-foreground">
                <summary className="cursor-pointer">{t("ai.layer.audit.content")}</summary>
                <pre className="mt-1 max-h-72 overflow-auto rounded border border-border bg-card p-2">
                  {JSON.stringify(d.packet.content, null, 2)}
                </pre>
              </details>
            </>
          ) : (
            <p className="text-caption text-subtle-foreground">—</p>
          )}
        </Panel>
      </div>
      <Panel title={t("ai.layer.audit.usage")} bodyClassName="p-0">
        {d.usage.length === 0 ? (
          <p className="p-3 text-caption text-subtle-foreground">{t("ai.layer.audit.noUsage")}</p>
        ) : (
          <TableShell compact>
            <THead>
              <TH>{t("ai.layer.audit.call")}</TH>
              <TH align="right">{t("ai.layer.audit.in")}</TH>
              <TH align="right">{t("ai.layer.audit.out")}</TH>
              <TH align="right">{t("ai.layer.audit.cached")}</TH>
              <TH align="right">{t("ai.layer.audit.cost")}</TH>
            </THead>
            <tbody>
              {d.usage.map((u) => (
                <TRow key={u.id}>
                  <TD className="text-xs">
                    {u.provider}:{u.model} · {u.purpose} · {u.status}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(u.input_tokens)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(u.output_tokens)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(u.cached_tokens)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {usd(u.cost_usd)}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
      {d.evidence.length ? (
        <Panel title={t("ai.layer.audit.evidence")} bodyClassName="p-3">
          <ul className="space-y-1 text-xs">
            {d.evidence.map((e) => (
              <li key={String(e["id"])}>
                <StatusBadge tone={EVIDENCE_TONE[(e["status"] as EvidenceStatus) ?? "OUTDATED"]}>
                  {translateOr(
                    `ai.layer.evidenceStatus.${String(e["status"])}`,
                    String(e["status"]),
                  )}
                </StatusBadge>{" "}
                {String(e["claim"])} · {String(e["source_name"])}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
      <p className="text-caption text-subtle-foreground">
        {t("ai.layer.audit.inputHash")}:{" "}
        <span className="numeric">{d.input_hash.slice(0, 24)}</span>
      </p>
    </div>
  );
}

function ReviewsTab() {
  const [engine, setEngine] = useState<"combined" | "rules" | "llm">("combined");
  const [decision, setDecision] = useState<AiDecision | "">("");
  const [day, setDay] = useState("");
  const [selected, setSelected] = useState(0);
  const q = useLiveQuery(
    live.aiReviews({ engine, decision: decision || undefined, day: day || undefined, limit: 200 }),
  );
  const rows = q.data?.data ?? [];
  const detail = useLiveQuery(live.aiReview(selected));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={engine}
          onChange={(e) => setEngine(e.target.value as typeof engine)}
          className={SELECT}
          aria-label={t("ai.layer.filters.engine")}
        >
          {(["combined", "rules", "llm"] as const).map((x) => (
            <option key={x} value={x}>
              {t(`ai.layer.engine.${x}`)}
            </option>
          ))}
        </select>
        <select
          value={decision}
          onChange={(e) => setDecision(e.target.value as AiDecision | "")}
          className={SELECT}
          aria-label={t("ai.layer.filters.decision")}
        >
          <option value="">{t("ai.layer.filters.all")}</option>
          {DECISIONS.map((x) => (
            <option key={x} value={x}>
              {t(`ai.layer.decision.${x}`)}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={day}
          onChange={(e) => setDay(e.target.value)}
          className={SELECT}
          aria-label={t("ai.layer.filters.day")}
        />
      </div>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={6} cols={6} /> : null}
      {!q.isLoading && rows.length === 0 ? (
        <p className="text-xs text-subtle-foreground">{t("ai.layer.reviews.empty")}</p>
      ) : null}
      {rows.length ? (
        <Panel bodyClassName="p-0">
          <TableShell>
            <THead>
              <TH>{t("ai.layer.reviews.match")}</TH>
              <TH>{t("ai.layer.reviews.selection")}</TH>
              <TH align="right">{t("ai.layer.reviews.odds")}</TH>
              <TH align="right">{t("ai.layer.reviews.model")}</TH>
              <TH align="right">{t("ai.layer.reviews.market")}</TH>
              <TH>{t("ai.layer.reviews.decision")}</TH>
              <TH>{t("ai.layer.reviews.reason")}</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={r.id} onClick={() => setSelected(r.id)} selected={r.id === selected}>
                  <TD className="text-xs">
                    <div className="font-medium">{r.match}</div>
                    <div className="text-caption text-subtle-foreground">
                      {r.competition} · {utcDateTime(r.kickoff_at)}
                    </div>
                  </TD>
                  <TD className="text-xs">
                    {r.market_key} · {r.selection}
                    {Number(r.line) !== 0 ? ` ${r.line}` : ""}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {r.odds ?? "—"}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {pct(r.p_model) ?? "—"}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {pct(r.p_market) ?? "—"}
                  </TD>
                  <TD>
                    <StatusBadge tone={DECISION_TONE[r.decision]}>
                      {t(`ai.layer.decision.${r.decision}`)}
                    </StatusBadge>
                  </TD>
                  <TD className="min-w-[16rem] max-w-[28rem] whitespace-normal break-words text-xs leading-snug text-muted-foreground">
                    {r.reason ?? "—"}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      ) : null}
      {selected ? (
        <Panel title={t("ai.layer.reviews.detail", { id: localInt(selected) })}>
          {detail.isError ? <ApiErrorNotice error={detail.error} /> : null}
          {detail.data?.data ? (
            <ReviewDetailView d={detail.data.data} />
          ) : (
            <TableSkeleton rows={3} cols={3} />
          )}
        </Panel>
      ) : null}
    </div>
  );
}

// ── evidence ─────────────────────────────────────────────────────────────────

function EvidenceTab() {
  const [status, setStatus] = useState<EvidenceStatus | "">("");
  const q = useLiveQuery(live.aiEvidence({ status: status || undefined }));
  const rows = q.data?.data ?? [];
  return (
    <div className="space-y-3">
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value as EvidenceStatus | "")}
        className={SELECT}
        aria-label={t("ai.layer.filters.status")}
      >
        <option value="">{t("ai.layer.filters.all")}</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {t(`ai.layer.evidenceStatus.${s}`)}
          </option>
        ))}
      </select>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {rows.length === 0 && !q.isLoading ? (
        <p className="text-xs text-subtle-foreground">{t("ai.layer.evidence.empty")}</p>
      ) : (
        <Panel bodyClassName="p-0">
          <TableShell>
            <THead>
              <TH>{t("ai.layer.evidence.claim")}</TH>
              <TH>{t("ai.layer.evidence.source")}</TH>
              <TH>{t("ai.layer.evidence.when")}</TH>
              <TH>{t("ai.layer.evidence.status")}</TH>
            </THead>
            <tbody>
              {rows.map((e) => (
                <TRow key={e.id}>
                  <TD className="text-xs">
                    <div>{e.claim}</div>
                    <div className="text-caption text-subtle-foreground">
                      {e.match ?? "—"} · {e.team ?? "—"} ·{" "}
                      {translateOr(`ai.layer.evidenceKind.${e.kind}`, e.kind)}
                    </div>
                  </TD>
                  <TD className="text-xs">
                    {e.source_url ? (
                      <a
                        href={e.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                      >
                        {e.source_name}
                      </a>
                    ) : (
                      e.source_name
                    )}
                    <div className="text-caption text-subtle-foreground">
                      {translateOr(`ai.layer.tierName.${e.source_tier}`, e.source_tier)}
                    </div>
                  </TD>
                  <TD className="text-caption text-subtle-foreground">
                    {e.published_at ? utcDateTime(e.published_at) : "—"}
                    <div>{utcDateTime(e.retrieved_at)}</div>
                  </TD>
                  <TD className="text-xs">
                    <StatusBadge tone={EVIDENCE_TONE[e.status]}>
                      {t(`ai.layer.evidenceStatus.${e.status}`)}
                    </StatusBadge>
                    <div className="text-caption text-subtle-foreground">{e.status_reason}</div>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      )}
    </div>
  );
}

// ── costs ────────────────────────────────────────────────────────────────────

/** The levels reported in any period, in the stack's order (L1, L2, L3, web), then any other. */
function levelsOf(periods: ReadonlyArray<readonly [string, AiCostPeriod]>): string[] {
  const seen = new Set<string>();
  for (const [, p] of periods) for (const r of levelRows(p.by_level)) seen.add(r.key);
  const order: string[] = [...LEVELS];
  return [...seen].sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib) || a.localeCompare(b);
  });
}

function CostsTab() {
  const q = useLiveQuery(live.aiCosts);
  const c = q.data?.data ?? null;
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!c) return <TableSkeleton rows={4} cols={5} />;
  const periods = (["today", "7d", "30d", "month"] as const).map((k) => [k, c.periods[k]] as const);
  const levels = levelsOf(periods);
  const worst = new Map(c.worst_case.map((w) => [w.profile, w]));
  return (
    <div className="space-y-4">
      <Panel
        title={t("ai.layer.costs.measured")}
        subtitle={t("ai.layer.costs.measuredHelp")}
        bodyClassName="p-0"
      >
        <TableShell>
          <THead>
            <TH>{t("ai.layer.costs.period")}</TH>
            <TH align="right">{t("ai.layer.costs.requests")}</TH>
            <TH align="right">{t("ai.layer.costs.tokens")}</TH>
            <TH align="right">{t("ai.layer.costs.searches")}</TH>
            <TH align="right">{t("ai.layer.costs.failed")}</TH>
            <TH align="right">{t("ai.layer.costs.cost")}</TH>
          </THead>
          <tbody>
            {periods.map(([k, p]) => (
              <TRow key={k}>
                <TD className="text-xs">{t(`ai.layer.costs.periods.${k}`)}</TD>
                <TD align="right" className="numeric text-xs">
                  {int(p.requests)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {int(p.input_tokens)} / {int(p.output_tokens)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {int(p.searches)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {int(p.failed)}
                </TD>
                <TD align="right" className="numeric text-xs font-medium">
                  {usd(p.cost_usd)}
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
      <Panel
        title={t("ai.layer.costs.units")}
        subtitle={t("ai.layer.costs.unitsHelp")}
        bodyClassName="p-0"
      >
        <TableShell>
          <THead>
            <TH>{t("ai.layer.costs.period")}</TH>
            <TH align="right">{t("ai.v2.costs.perMatch")}</TH>
            <TH align="right">{t("ai.v2.costs.perAnalysis")}</TH>
            <TH align="right">{t("ai.v2.costs.perSearch")}</TH>
            <TH align="right">{t("ai.v2.costs.perReviewedPick")}</TH>
            <TH align="right">{t("ai.v2.costs.perApproved")}</TH>
            <TH align="right">{t("ai.v2.costs.perSelected")}</TH>
          </THead>
          <tbody>
            {periods.map(([k, p]) => (
              <TRow key={k}>
                <TD className="text-xs">{t(`ai.layer.costs.periods.${k}`)}</TD>
                {[
                  p.cost_per_match,
                  p.cost_per_analysis,
                  p.cost_per_search,
                  p.cost_per_review,
                  p.cost_per_approved,
                  p.cost_per_selected,
                ].map((v, i) => (
                  <TD key={i} align="right" className="numeric text-xs">
                    {usd(v)}
                  </TD>
                ))}
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
      <Panel
        title={t("ai.layer.costs.byLevel")}
        subtitle={t("ai.layer.costs.byLevelHelp")}
        bodyClassName="p-0"
      >
        {levels.length === 0 ? (
          <Note className="p-4">{t("ai.v2.costs.noLevel")}</Note>
        ) : (
          <TableShell>
            <THead>
              <TH>{t("ai.layer.costs.period")}</TH>
              {levels.map((l) => (
                <TH key={l} align="right">
                  {levelLabel(l)}
                </TH>
              ))}
            </THead>
            <tbody>
              {periods.map(([k, p]) => {
                const by = new Map(levelRows(p.by_level).map((r) => [r.key, r]));
                return (
                  <TRow key={k}>
                    <TD className="text-xs">{t(`ai.layer.costs.periods.${k}`)}</TD>
                    {levels.map((l) => {
                      const r = by.get(l);
                      return (
                        <TD key={l} align="right" className="numeric text-xs">
                          {r ? usd(r.cost_usd) : "—"}
                          {r ? (
                            <div className="text-caption text-subtle-foreground">
                              {t("ai.v2.costs.requests", {
                                count: r.requests,
                                n: localInt(r.requests),
                              })}
                            </div>
                          ) : null}
                        </TD>
                      );
                    })}
                  </TRow>
                );
              })}
            </tbody>
          </TableShell>
        )}
      </Panel>
      <Panel
        title={t("ai.layer.costs.simulation")}
        subtitle={t("ai.layer.costs.simulationHelp")}
        bodyClassName="p-0"
      >
        <TableShell>
          <THead>
            <TH>{t("ai.layer.costs.profile")}</TH>
            <TH align="right">{t("ai.layer.costs.day")}</TH>
            <TH align="right">{t("ai.layer.costs.month")}</TH>
            <TH align="right">{t("ai.layer.costs.perMatch")}</TH>
            <TH align="right">{t("ai.layer.costs.worstMonth")}</TH>
          </THead>
          <tbody>
            {c.simulation.map((s) => (
              <TRow key={s.profile}>
                <TD className="text-xs">
                  <div className="font-medium">
                    {translateOr(`ai.layer.profile.${s.profile}`, s.profile)}
                  </div>
                  <div className="text-caption text-subtle-foreground">{s.note}</div>
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(s.day_usd)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(s.month_usd)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(s.per_match_usd)}
                </TD>
                <TD align="right" className="numeric text-xs">
                  {usd(worst.get(s.profile)?.month_usd)}
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
    </div>
  );
}

// ── shadow ───────────────────────────────────────────────────────────────────

function ArmRow({ name, a }: { name: string; a: ShadowArm | undefined }) {
  if (!a || !a.n) return null;
  return (
    <TRow>
      <TD className="text-xs">{t(`ai.layer.shadow.arm.${name}`)}</TD>
      <TD align="right" className="numeric text-xs">
        {localInt(a.n)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {percent(a.hit_rate)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {percent(a.roi)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {percent(a.clv)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {a.logloss_model ?? "—"} / {a.logloss_market ?? "—"}
      </TD>
      <TD align="right" className="numeric text-xs">
        {a.brier_model ?? "—"} / {a.brier_market ?? "—"}
      </TD>
      <TD align="right" className="numeric text-xs">
        {a.max_drawdown ?? "—"}
      </TD>
    </TRow>
  );
}

function ShadowTab() {
  const q = useLiveQuery(live.aiShadow);
  const rows: ShadowReportRow[] = q.data?.data ?? [];
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (q.isLoading) return <TableSkeleton rows={4} cols={6} />;
  if (!rows.length)
    return <p className="text-xs text-subtle-foreground">{t("ai.layer.shadow.empty")}</p>;
  return (
    <div className="space-y-4">
      <WarningBanner tone="info">{t("ai.layer.shadow.help")}</WarningBanner>
      {rows.map((r) => (
        <Panel
          key={r.engine}
          title={t(`ai.layer.engine.${r.engine}`)}
          subtitle={t("ai.layer.shadow.window", { from: r.window_from, to: r.window_to })}
          actions={
            <StatusBadge tone={gateTone(r.verdict)}>
              {t(`ai.layer.gate.${r.verdict ?? "none"}`)}
            </StatusBadge>
          }
          bodyClassName="p-0"
        >
          <TableShell>
            <THead>
              <TH>{t("ai.layer.shadow.armLabel")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.n")}</TH>
              <TH align="right">{t("ai.layer.shadow.hit")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.roi")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.clv")}</TH>
              <TH align="right">{t("ai.layer.shadow.logloss")}</TH>
              <TH align="right">{t("ai.layer.compare.cols.brier")}</TH>
              <TH align="right">{t("ai.layer.shadow.drawdown")}</TH>
            </THead>
            <tbody>
              {ARMS.map((a) => (
                <ArmRow key={a} name={a} a={r.arms[a]} />
              ))}
            </tbody>
          </TableShell>
          {r.checks ? (
            <ul className="flex flex-wrap gap-1.5 p-3">
              {Object.entries(r.checks).map(([k, c]) => (
                <li key={k}>
                  <StatusBadge tone={c.ok ? "positive" : "neutral"}>
                    {translateOr(`ai.layer.shadow.check.${k}`, k)}: {c.ok ? "✓" : "✗"}
                  </StatusBadge>
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
      ))}
    </div>
  );
}

// ── memory ───────────────────────────────────────────────────────────────────

function MemoryTab() {
  const q = useLiveQuery(live.aiMemory());
  const rows = q.data?.data ?? [];
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!rows.length && !q.isLoading)
    return <p className="text-xs text-subtle-foreground">{t("ai.layer.memory.empty")}</p>;
  return (
    <Panel bodyClassName="p-3">
      <ul className="space-y-2">
        {rows.map((m) => (
          <li key={m.id} className="space-y-0.5 border-b border-border pb-2 text-xs last:border-0">
            <div className="flex flex-wrap items-center gap-1.5 text-caption text-subtle-foreground">
              <StatusBadge tone="neutral">
                {translateOr(`ai.layer.memoryKind.${m.kind}`, m.kind)}
              </StatusBadge>
              <span>
                {m.entity_type}:{m.entity_id}
              </span>
              <span>· {utcDateTime(m.created_at)}</span>
              {m.result ? <span>· {m.result}</span> : null}
              <span>· {m.version}</span>
            </div>
            {m.hypothesis ? <p className="text-muted-foreground">{m.hypothesis}</p> : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function AiLayerLive() {
  const q = useLiveQuery(live.aiOverview);
  const [tab, setTab] = useState<Tab>("reviews");
  const o = q.data?.data ?? null;
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.aiLayer.title")}
        description={t("admin.pages.aiLayer.description")}
      />
      <ShadowBanner />
      {o && !o.settings.llm_configured ? (
        <WarningBanner tone="info">
          {t("ai.layer.noModel", { missing: o.settings.missing.join(", ") || "—" })}
        </WarningBanner>
      ) : null}
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {o ? (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <BudgetCard o={o} />
            <StackCard o={o} />
          </div>
          <EfficiencyPanel e={o.efficiency} />
        </>
      ) : q.isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : null}
      <ComparisonPanel />
      <StatusStrip o={o} />
      <SegmentedTabs
        tabs={TABS}
        value={tab}
        onChange={setTab}
        label={t("ai.layer.tabs.label")}
        format={(x) => t(`ai.layer.tabs.${x}`)}
      />
      {tab === "reviews" ? <ReviewsTab /> : null}
      {tab === "evidence" ? <EvidenceTab /> : null}
      {tab === "costs" ? <CostsTab /> : null}
      {tab === "shadow" ? <ShadowTab /> : null}
      {tab === "memory" ? <MemoryTab /> : null}
    </div>
  );
}
