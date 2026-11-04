/**
 * What the AI costs, in one place (plan F13: it was in three pages - PrediGol Intelligence, the AI decision layer and AI and research - with
 * the budget three times). The month's budget with its projection and alerts, the models of each level and the caps, the pace of the last
 * days, today's efficiency, what each unit costs (the AI layer's, per period; PrediGol Intelligence's, over the last seven days), what each
 * period and each level and each model cost, and the simulation per provider profile. Reading only.
 */
import type { ReactNode } from "react";
import { t, translateOr } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { int } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  AiCostPeriod,
  AiCosts,
  AiEfficiency,
  AiEnvelopes,
  AiOverview,
  AiSwitchState,
  AiUserView,
} from "@/lib/api/v1/types_ai_layer";
import { LevelBadge, MonthBar, Note, Stat, StatGrid, SubTitle, type StatTone } from "./AiBits";
import {
  LEVELS,
  barPercent,
  bogotaDateTime,
  budgetTone,
  dayShort,
  envelopesOf,
  levelLabel,
  levelRows,
  probText,
  ratioOf,
  shareTone,
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

/**
 * The readers' AI (plan UX, A11): the narrative's switch, its OWN budget - apart from the one above, which it never touches - and
 * what it wrote today. With the budget at 0 it never spends; the owner approves it (P8).
 */
export function UserAiCard({ u }: { u: AiUserView }) {
  const b = u.budget;
  const today = u.today;
  const funded = (toNum(b.monthly_budget_usd) ?? 0) > 0;
  const state = funded ? b.state : "none";
  return (
    <Panel title={t("ai.layer.userAi.title")} subtitle={t("ai.layer.userAi.subtitle")}>
      <div className="space-y-4" data-testid="ai-user-card">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <StatusBadge
            tone={u.mode === "on" ? "positive" : u.mode === "shadow" ? "warning" : "neutral"}
          >
            {t(`ai.layer.userAi.mode.${u.mode}`)}
          </StatusBadge>
          <StatusBadge tone={state === "none" ? "neutral" : budgetTone(state)}>
            {translateOr(`ai.layer.userAi.state.${state}`, state)}
          </StatusBadge>
          <span className="text-xs text-muted-foreground">
            {t(`ai.layer.userAi.modeHelp.${u.mode}`)}
          </span>
        </div>
        <StatGrid className="lg:grid-cols-3">
          <Stat label={t("ai.layer.budgetCard.monthly")} value={usd(b.monthly_budget_usd)} />
          <Stat label={t("ai.layer.budgetCard.spentToday")} value={usd(b.spent_today_usd)} />
          <Stat label={t("ai.layer.budgetCard.spentMonth")} value={usd(b.spent_month_usd)} />
          <Stat label={t("ai.layer.userAi.written")} value={localInt(today.ok ?? 0)} />
          <Stat
            label={t("ai.layer.userAi.refused")}
            value={localInt((today.rejected ?? 0) + (today.failed ?? 0))}
            hint={t("ai.layer.userAi.refusedHint")}
          />
          <Stat
            label={t("ai.layer.userAi.translations")}
            value={localInt(today.translations ?? 0)}
          />
        </StatGrid>
        {funded ? (
          <MonthBar spent={b.spent_month_usd} budget={b.monthly_budget_usd} alerts={[]} />
        ) : null}
        <Note>{t("ai.layer.userAi.apart")}</Note>
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

// ── the three envelopes, the savings and the switches (Phase 0 of the AI master plan) ──────

/** A thin bar: how much of an envelope is spent. */
function EnvelopeBar({ share, label }: { share: number | null; label: string }) {
  const fill =
    share === null
      ? "bg-muted-foreground/40"
      : share >= 1
        ? "bg-negative"
        : share >= 0.85
          ? "bg-warning"
          : "bg-primary";
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(barPercent(share))}
      aria-valuetext={probText(share, 0)}
      className="h-2 rounded-full bg-muted"
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-500", fill)}
        style={{ width: `${barPercent(share)}%` }}
      />
    </div>
  );
}

/** One envelope: its name, its state, the bar of what is spent and its figures. */
function EnvelopeBox({
  id,
  title,
  badge,
  share,
  workspace,
  children,
}: {
  id: string;
  title: string;
  badge?: ReactNode;
  share: number | null;
  workspace?: string | undefined;
  children: ReactNode;
}) {
  return (
    <section
      className="min-w-0 space-y-3 rounded-md border border-border p-3"
      data-testid={`ai-envelope-${id}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <h3 className="text-sm font-medium">{title}</h3>
        {badge}
      </div>
      {workspace ? (
        <p className="text-caption text-muted-foreground">
          {t("ai.layer.envelopes.workspace", { name: workspace })}
        </p>
      ) : null}
      <EnvelopeBar share={share} label={t("ai.layer.envelopes.bar", { name: title })} />
      {children}
    </section>
  );
}

/** Claude of the production workspace against US$185: spent, projected, what the open batches hold and the reserve. */
function ProductionBox({ p }: { p: AiEnvelopes["production"] }) {
  return (
    <EnvelopeBox
      id="production"
      title={t("ai.layer.envelopes.production")}
      share={p.share}
      workspace={p.workspace}
      badge={
        <StatusBadge tone={budgetTone(p.state)}>
          {translateOr(`ai.layer.budget.${p.state}`, p.state)}
        </StatusBadge>
      }
    >
      <StatGrid className="sm:grid-cols-2 lg:grid-cols-2">
        <Stat
          label={t("ai.layer.envelopes.spent")}
          value={usd(p.spent_usd)}
          hint={t("ai.layer.envelopes.spentHint", {
            share: probText(p.share, 0),
            budget: usd(p.budget_usd),
          })}
        />
        <Stat label={t("ai.layer.envelopes.today")} value={usd(p.spent_today_usd)} />
        <Stat
          label={t("ai.layer.envelopes.projection")}
          value={usd(p.projected_usd)}
          tone={shareTone(p.projection_share)}
          hint={t("ai.layer.envelopes.projectionHint", { share: probText(p.projection_share, 0) })}
        />
        <Stat
          label={t("ai.layer.envelopes.reserved")}
          value={usd(p.reserved_for_batches_usd)}
          hint={t("ai.layer.envelopes.reservedHint")}
        />
        <Stat
          label={t("ai.layer.envelopes.reserve")}
          value={usd(p.reserve_usd)}
          hint={t("ai.layer.envelopes.reserveHint", { locked: usd(p.reserve_locked_usd) })}
        />
      </StatGrid>
      {p.limit.active ? (
        <WarningBanner>
          {t("ai.layer.envelopes.limit", { time: bogotaDateTime(p.limit.until) })}
        </WarningBanner>
      ) : null}
    </EnvelopeBox>
  );
}

/** Claude of the LAB workspace: it runs a day whole or not at all, and yields to production. */
function LabBox({ l }: { l: AiEnvelopes["lab"] }) {
  return (
    <EnvelopeBox
      id="lab"
      title={t("ai.layer.envelopes.lab")}
      share={l.share}
      workspace={l.workspace}
      badge={
        <StatusBadge tone={l.allowed ? "positive" : "neutral"}>
          {translateOr(`ai.layer.envelopes.labReason.${l.reason}`, l.reason)}
        </StatusBadge>
      }
    >
      <StatGrid className="sm:grid-cols-2 lg:grid-cols-2">
        <Stat
          label={t("ai.layer.envelopes.spent")}
          value={usd(l.spent_usd)}
          hint={t("ai.layer.envelopes.spentHint", {
            share: probText(l.share, 0),
            budget: usd(l.budget_usd),
          })}
        />
        <Stat label={t("ai.layer.envelopes.today")} value={usd(l.spent_today_usd)} />
        <Stat
          label={t("ai.layer.envelopes.allocation")}
          value={usd(l.allocation_usd)}
          hint={t("ai.layer.envelopes.allocationHint")}
        />
        <Stat
          label={t("ai.layer.envelopes.reserved")}
          value={usd(l.reserved_for_batches_usd)}
          hint={t("ai.layer.envelopes.reservedHint")}
        />
      </StatGrid>
      {l.limit.active ? (
        <WarningBanner>
          {t("ai.layer.envelopes.limit", { time: bogotaDateTime(l.limit.until) })}
        </WarningBanner>
      ) : null}
    </EnvelopeBox>
  );
}

/** Exa: every web search, its own money. */
function ExaBox({ x }: { x: AiEnvelopes["exa"] }) {
  return (
    <EnvelopeBox
      id="exa"
      title={t("ai.layer.envelopes.exa")}
      share={x.share}
      badge={
        <StatusBadge tone={x.allowed ? "positive" : "warning"}>
          {translateOr(`ai.layer.envelopes.exaReason.${x.reason}`, x.reason)}
        </StatusBadge>
      }
    >
      <StatGrid className="sm:grid-cols-2 lg:grid-cols-2">
        <Stat
          label={t("ai.layer.envelopes.spent")}
          value={usd(x.spent_usd)}
          hint={t("ai.layer.envelopes.spentHint", {
            share: probText(x.share, 0),
            budget: usd(x.budget_usd),
          })}
        />
        <Stat label={t("ai.layer.envelopes.today")} value={usd(x.spent_today_usd)} />
        <Stat label={t("ai.layer.envelopes.searches")} value={int(x.searches)} />
      </StatGrid>
    </EnvelopeBox>
  );
}

/** Production and the LAB together against the joint ceiling Claude may not pass. */
function JointBox({ c }: { c: AiEnvelopes["claude"] }) {
  return (
    <EnvelopeBox id="claude" title={t("ai.layer.envelopes.joint")} share={c.share}>
      <StatGrid className="sm:grid-cols-2 lg:grid-cols-2">
        <Stat
          label={t("ai.layer.envelopes.spent")}
          value={usd(c.spent_usd)}
          hint={t("ai.layer.envelopes.spentHint", {
            share: probText(c.share, 0),
            budget: usd(c.ceiling_usd),
          })}
        />
        <Stat label={t("ai.layer.envelopes.ceiling")} value={usd(c.ceiling_usd)} />
        <Stat
          label={t("ai.layer.envelopes.projection")}
          value={usd(c.projected_usd)}
          tone={shareTone(c.projection_share)}
          hint={t("ai.layer.envelopes.projectionHint", { share: probText(c.projection_share, 0) })}
        />
      </StatGrid>
    </EnvelopeBox>
  );
}

/** Claude of production, Claude of the LAB and Exa against their own envelopes, the joint ceiling, and each of the last 14 days. */
function EnvelopesCard({ e }: { e: AiEnvelopes }) {
  const days = [...e.days].reverse();
  return (
    <Panel title={t("ai.layer.envelopes.title")} subtitle={t("ai.layer.envelopes.subtitle")}>
      <div className="space-y-4" data-testid="ai-envelopes">
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-4">
          <ProductionBox p={e.production} />
          <LabBox l={e.lab} />
          <ExaBox x={e.exa} />
          <JointBox c={e.claude} />
        </div>
        <section className="space-y-1.5">
          <SubTitle>{t("ai.layer.envelopes.days")}</SubTitle>
          <Note>{t("ai.layer.envelopes.daysHelp")}</Note>
          <TableShell>
            <THead>
              <TH>{t("ai.layer.envelopes.day")}</TH>
              <TH align="right">{t("ai.layer.envelopes.production")}</TH>
              <TH align="right">{t("ai.layer.envelopes.lab")}</TH>
              <TH align="right">{t("ai.layer.envelopes.exa")}</TH>
            </THead>
            <tbody>
              {days.map((d) => (
                <TRow key={d.day}>
                  <TD className="text-xs">{dayShort(d.day)}</TD>
                  <TD align="right" className="numeric text-xs">
                    {usd(d.production_usd)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {usd(d.lab_usd)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {usd(d.exa_usd)}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </section>
      </div>
    </Panel>
  );
}

/** What the cache and the batches saved this month, and what was reused instead of paid again. */
function SavingsCard({ e }: { e: AiEnvelopes }) {
  const s = e.savings.month;
  const r = e.reuse;
  const b = e.batch;
  const total = toNum(s.total_usd);
  return (
    <Panel title={t("ai.layer.savings.title")} subtitle={t("ai.layer.savings.subtitle")}>
      <div className="space-y-4" data-testid="ai-savings">
        <StatGrid className="sm:grid-cols-2 lg:grid-cols-2">
          <Stat
            label={t("ai.layer.savings.total")}
            value={usd(s.total_usd)}
            tone={total === null ? "default" : total < 0 ? "negative" : "positive"}
          />
          <Stat
            label={t("ai.layer.savings.cache")}
            value={usd(s.cache_usd)}
            hint={
              s.read_share === null
                ? undefined
                : t("ai.layer.savings.cacheHint", { share: probText(s.read_share, 0) })
            }
          />
          <Stat
            label={t("ai.layer.savings.batch")}
            value={usd(s.batch_usd)}
            hint={
              s.batch_share === null
                ? undefined
                : t("ai.layer.savings.batchHint", { share: probText(s.batch_share, 0) })
            }
          />
          <Stat
            label={t("ai.layer.savings.writes")}
            value={int(s.write_tokens)}
            hint={t("ai.layer.savings.writesHint")}
          />
        </StatGrid>
        <section className="space-y-2">
          <SubTitle>{t("ai.layer.savings.reuse")}</SubTitle>
          <StatGrid className="sm:grid-cols-2 lg:grid-cols-2">
            <Stat
              label={t("ai.layer.savings.briefs")}
              value={int(r.briefs_reused)}
              hint={t("ai.layer.savings.briefsHint", {
                material: int(r.briefs_reused_material),
                paid: int(r.briefs_paid),
              })}
            />
            <Stat
              label={t("ai.layer.savings.reviews")}
              value={int(r.reviews_reused)}
              hint={t("ai.layer.savings.reviewsHint", { batched: int(r.reviews_batched) })}
            />
            <Stat
              label={t("ai.layer.savings.batches")}
              value={int(b.open_batches)}
              hint={t("ai.layer.savings.batchesHint", {
                items: int(b.open_items),
                ended: int(b.ended_batches),
              })}
            />
            <Stat
              label={t("ai.layer.savings.lost")}
              value={int(b.lost_batches)}
              tone={b.lost_batches > 0 ? "warning" : "default"}
              hint={t("ai.layer.savings.lostHint")}
            />
          </StatGrid>
        </section>
      </div>
    </Panel>
  );
}

const SWITCH_NAMES = [
  "cache",
  "brief_material",
  "budget_v3",
  "batch",
  "native_schema",
  "cache_layout",
] as const;

/** Why a switch is on or off, from what the server says (its mode, whether it is in force, and its gate) - not from the server's English. */
function switchWhy(name: (typeof SWITCH_NAMES)[number], s: AiSwitchState): string {
  if (s.mode === "off") return t("ai.layer.switches.why.ownerOff");
  if (name === "cache_layout") {
    return s.on ? t("ai.layer.switches.why.passed") : t("ai.layer.switches.why.layout");
  }
  if (s.mode === "on") return t("ai.layer.switches.why.forced");
  if (s.on) {
    return s.gate ? t("ai.layer.switches.why.passed") : t("ai.layer.switches.why.default");
  }
  return t("ai.layer.switches.why.waiting");
}

/** The five optimisations of Phase 0 and the shared match block: whether each is in force, why, and the evidence it rests on. */
function SwitchesCard({ e }: { e: AiEnvelopes }) {
  const gates = e.switches.gates;
  return (
    <Panel title={t("ai.layer.switches.title")} subtitle={t("ai.layer.switches.subtitle")}>
      <ul className="space-y-3" data-testid="ai-switches">
        {SWITCH_NAMES.map((name) => {
          const s = e.switches[name];
          const gate = s.gate ? gates[s.gate] : undefined;
          return (
            <li key={name} className="min-w-0 space-y-1" data-testid={`ai-switch-${name}`}>
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-medium">{t(`ai.layer.switches.names.${name}`)}</span>
                <StatusBadge tone={s.on ? "positive" : "neutral"}>
                  {s.on ? t("ai.layer.switches.on") : t("ai.layer.switches.off")}
                </StatusBadge>
              </div>
              <p className="text-caption text-muted-foreground">{switchWhy(name, s)}</p>
              {s.gate ? (
                <p className="text-caption text-subtle-foreground">
                  {t("ai.layer.switches.evidence")}:{" "}
                  {gate?.passed
                    ? t("ai.layer.switches.passedOn", { date: bogotaDateTime(gate.at) })
                    : gate?.at
                      ? t("ai.layer.switches.failedOn", { date: bogotaDateTime(gate.at) })
                      : t("ai.layer.switches.none")}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

/** The three envelopes, what the cache and the batches saved, and the switches: Phase 0 of the AI master plan. */
export function EnvelopesBody({ e }: { e: AiEnvelopes }) {
  return (
    <>
      <EnvelopesCard e={e} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <SavingsCard e={e} />
        <SwitchesCard e={e} />
      </div>
    </>
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
  const envelopes = o ? envelopesOf(o) : null;
  return (
    <div className="space-y-4" data-testid="ai-costs">
      {overview.isError ? <ApiErrorNotice error={overview.error} /> : null}
      {o ? (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <BudgetCard o={o} />
            <StackCard o={o} />
          </div>
          {o.user_ai ? <UserAiCard u={o.user_ai} /> : null}
          {envelopes ? (
            <EnvelopesBody e={envelopes} />
          ) : (
            <Panel title={t("ai.layer.envelopes.title")}>
              <Note>{t("ai.layer.envelopes.empty")}</Note>
            </Panel>
          )}
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
