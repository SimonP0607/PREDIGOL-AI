/**
 * What the AI costs, in one place (plan F13: it was in three pages - PrediGol Intelligence, the AI decision layer and AI and research - with
 * the budget three times). The month's budget with its projection and alerts, the models of each level and the caps, the pace of the last
 * days, today's efficiency, what each unit costs (the AI layer's, per period; PrediGol Intelligence's, over the last seven days), what each
 * period and each level and each model cost, and the simulation per provider profile. Reading only.
 */
import { t, translateOr } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { int } from "@/lib/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { AiCostPeriod, AiCosts, AiEfficiency, AiOverview } from "@/lib/api/v1/types_ai_layer";
import { LevelBadge, MonthBar, Note, Stat, StatGrid, SubTitle, type StatTone } from "./AiBits";
import {
  LEVELS,
  budgetTone,
  dayShort,
  levelLabel,
  levelRows,
  probText,
  ratioOf,
  toNum,
  usd,
} from "./aiModel";

const PERIODS = ["today", "7d", "30d", "month"] as const;

// ── the budget, the models and today's efficiency ────────────────────────────

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

// ── the pace of the last days ────────────────────────────────────────────────

/** The run rate and what each of the last days cost (the projection itself is in the budget card). */
function SpendPace({ c }: { c: AiCosts }) {
  const p = c.projection;
  // the API sends an empty projection ({}) when it has none
  const runRate = toNum(p?.run_rate_usd);
  const lastDays = p?.last_days ?? [];
  return (
    <Panel title={t("ai.research.costs.pace")}>
      <div className="space-y-3" data-testid="ai-costs-pace">
        <StatGrid>
          <Stat
            label={t("ai.research.costs.runRate")}
            value={runRate === null ? "—" : t("ai.research.costs.perDay", { value: usd(runRate) })}
          />
        </StatGrid>
        {lastDays.length ? (
          <section className="space-y-1.5">
            <SubTitle>{t("ai.research.costs.lastDays")}</SubTitle>
            <ul className="flex flex-wrap gap-1.5">
              {lastDays.map((d) => (
                <li
                  key={d.day}
                  className="rounded border border-border bg-elevated/50 px-1.5 py-0.5 text-caption"
                >
                  <span className="text-subtle-foreground">{dayShort(d.day)}</span>{" "}
                  <span className="numeric text-foreground">{usd(d.cost_usd)}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <Note>{t("ai.research.costs.noDays")}</Note>
        )}
      </div>
    </Panel>
  );
}

// ── what PrediGol Intelligence costs per unit ────────────────────────────────

/** Per match, candidate, pick, research and post-mortem over the last seven closed days, and per day. */
function IntelUnitCosts() {
  const q = useLiveQuery(live.intelCosts);
  const c = q.data?.data;
  return (
    <Panel title={t("intel.costs.title")} subtitle={t("intel.costs.subtitle")}>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {c ? (
        <StatGrid className="lg:grid-cols-3" testId="intel-costs">
          <Stat label={t("intel.costs.perMatch")} value={usd(c.per_match_usd)} />
          <Stat label={t("intel.costs.perCandidate")} value={usd(c.per_candidate_usd)} />
          <Stat label={t("intel.costs.perPick")} value={usd(c.per_pick_usd)} />
          <Stat label={t("intel.costs.perResearch")} value={usd(c.per_research_usd)} />
          <Stat label={t("intel.costs.perPostmortem")} value={usd(c.per_postmortem_usd)} />
          <Stat label={t("intel.costs.perDay")} value={usd(c.per_day_usd)} />
        </StatGrid>
      ) : q.isLoading ? (
        <TableSkeleton rows={2} cols={3} />
      ) : null}
    </Panel>
  );
}

// ── the periods ──────────────────────────────────────────────────────────────

/** The models reported in any period, the dearest over the four periods first. */
function modelsOf(periods: ReadonlyArray<readonly [string, AiCostPeriod]>): string[] {
  const spent = new Map<string, number>();
  for (const [, p] of periods)
    for (const m of p.by_model)
      spent.set(m.key, (spent.get(m.key) ?? 0) + (toNum(m.cost_usd) ?? 0));
  return [...spent.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([k]) => k);
}

/** Measured, per unit, per level, per model and simulated: the tables of the periods (today, 7 days, 30 days, the month). */
function PeriodTables({ c }: { c: AiCosts }) {
  const periods = PERIODS.map((k) => [k, c.periods[k]] as const);
  const levels = levelsOf(periods);
  const models = modelsOf(periods);
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
        title={t("ai.research.costs.byModel")}
        subtitle={t("ai.layer.costs.byModelHelp")}
        bodyClassName="p-0"
      >
        {models.length === 0 ? (
          <Note className="p-4">{t("ai.research.costs.noModel")}</Note>
        ) : (
          <TableShell>
            <THead>
              <TH>{t("ai.layer.costs.period")}</TH>
              {models.map((m) => (
                <TH key={m} align="right">
                  <span className="wrap-anywhere">{m}</span>
                </TH>
              ))}
            </THead>
            <tbody>
              {periods.map(([k, p]) => {
                const by = new Map(p.by_model.map((r) => [r.key, r]));
                return (
                  <TRow key={k}>
                    <TD className="text-xs">{t(`ai.layer.costs.periods.${k}`)}</TD>
                    {models.map((m) => {
                      const r = by.get(m);
                      return (
                        <TD key={m} align="right" className="numeric text-xs">
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

// ── the view ─────────────────────────────────────────────────────────────────

/** COSTES: the budget, the models, the pace, the efficiency of today and everything the periods cost. */
export function CostsView() {
  const overview = useLiveQuery(live.aiOverview);
  const costs = useLiveQuery(live.aiCosts);
  const o = overview.data?.data ?? null;
  const c = costs.data?.data ?? null;
  return (
    <div className="space-y-4" data-testid="ai-costs">
      {overview.isError ? <ApiErrorNotice error={overview.error} /> : null}
      {o ? (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <BudgetCard o={o} />
            <StackCard o={o} />
          </div>
          <EfficiencyPanel e={o.efficiency} />
        </>
      ) : overview.isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : null}
      {costs.isError ? <ApiErrorNotice error={costs.error} /> : null}
      {c ? <SpendPace c={c} /> : null}
      <IntelUnitCosts />
      {c ? <PeriodTables c={c} /> : costs.isLoading ? <TableSkeleton rows={4} cols={5} /> : null}
    </div>
  );
}
