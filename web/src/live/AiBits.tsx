/**
 * Pieces shared by the AI V2 screens - Capa de decisión IA, IA e investigación and Evolución - so the shadow
 * line, the budget bar, the costs, the learning notes and the proposals read the same wherever they appear.
 */
import type { ReactNode } from "react";
import { t, translateOr } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { KeyValue, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { live } from "@/lib/api/v1/queries";
import type {
  AiBudgetAlert,
  AiCostPeriod,
  LearningNote,
  Proposal,
} from "@/lib/api/v1/types_ai_layer";
import {
  barPercent,
  bogotaDateTime,
  budgetMarkers,
  evidenceSummary,
  levelLabel,
  levelRows,
  probText,
  ratioOf,
  thresholdText,
  toNum,
  usd,
  type EvidenceItem,
} from "./aiModel";

const STAT_TONE = {
  default: "text-foreground",
  positive: "text-positive",
  negative: "text-negative",
  warning: "text-warning",
  muted: "text-muted-foreground",
} as const;

export type StatTone = keyof typeof STAT_TONE;

const LEVEL_TONE: Record<string, BadgeTone> = {
  L1: "info",
  L2: "brand",
  L3: "warning",
  web: "neutral",
};

/** One line: everything the AI decides is in evaluation (shadow) - or, honestly, that it is enforced. */
export function ShadowBanner() {
  const q = useLiveQuery(live.aiOverview);
  const o = q.data?.data ?? null;
  if (!o) return null;
  if (o.enforcement.enforced) return <WarningBanner>{t("ai.v2.enforcedLine")}</WarningBanner>;
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-md border border-primary/25 bg-primary/8 px-3 py-2 text-xs"
      data-testid="ai-shadow-line"
    >
      <StatusBadge tone="brand">{t("ai.v2.shadowBadge")}</StatusBadge>
      <span className="min-w-0 text-foreground/85">{t("ai.v2.shadowLine")}</span>
    </div>
  );
}

/** A grid of figures (a <dl>): two columns on a phone, more as the page widens. */
export function StatGrid({
  children,
  className,
  testId,
}: {
  children: ReactNode;
  className?: string | undefined;
  testId?: string | undefined;
}) {
  return (
    <dl
      className={cn("grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4", className)}
      data-testid={testId}
    >
      {children}
    </dl>
  );
}

/** A labelled figure in a tile, inside a <StatGrid>. */
export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: StatTone;
}) {
  return (
    <div className="min-w-0 rounded-md border border-border bg-card px-2.5 py-2">
      <dt className="text-caption uppercase tracking-wider text-subtle-foreground">{label}</dt>
      <dd className={cn("numeric mt-0.5 text-base font-semibold wrap-anywhere", STAT_TONE[tone])}>
        {value}
      </dd>
      {hint ? <dd className="mt-0.5 text-caption text-muted-foreground">{hint}</dd> : null}
    </div>
  );
}

/** Small explanatory or empty-state text. */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-xs text-subtle-foreground", className)}>{children}</p>;
}

/** A small uppercase heading inside a card. */
export function SubTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-caption font-medium uppercase tracking-wider text-subtle-foreground">
      {children}
    </h3>
  );
}

/** A plain date input (a Bogotá day, "YYYY-MM-DD"). Clearing it keeps the day it had. */
export function DayInput({
  value,
  onChange,
  label,
  max,
}: {
  value: string;
  onChange: (day: string) => void;
  label: string;
  max?: string | undefined;
}) {
  return (
    <label className="inline-flex items-center gap-2 text-caption uppercase tracking-wider text-subtle-foreground">
      {label}
      <input
        type="date"
        value={value}
        max={max}
        onChange={(e) => {
          if (e.target.value) onChange(e.target.value);
        }}
        className="h-8 rounded-md border border-border bg-card px-2 text-xs normal-case tracking-normal text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
    </label>
  );
}

/** L1 · económico, L2 · intermedio, L3 · fuerte, Web. */
export function LevelBadge({ level }: { level: string }) {
  return (
    <StatusBadge tone={LEVEL_TONE[level] ?? "neutral"} dot={false}>
      {levelLabel(level)}
    </StatusBadge>
  );
}

/** "LLM" when a language model wrote it, "Reglas" when the rules did. */
export function EngineBadge({ engine }: { engine: string }) {
  if (engine === "llm") return <StatusBadge tone="brand">{t("ai.v2.engine.llm")}</StatusBadge>;
  return (
    <StatusBadge tone="neutral">
      {engine === "rules" ? t("ai.v2.engine.rules") : engine}
    </StatusBadge>
  );
}

/**
 * The month's spend against its budget: the bar, its markers at 50 / 70 / 85 / 95 / 100 % and, under it, each
 * threshold - with the date of the alert recorded this month when it was crossed.
 */
export function MonthBar({
  spent,
  budget,
  alerts,
}: {
  spent: number | string | null | undefined;
  budget: number | string | null | undefined;
  alerts: readonly AiBudgetAlert[];
}) {
  const ratio = ratioOf(spent, budget);
  const width = barPercent(ratio);
  const markers = budgetMarkers(ratio, alerts);
  const share = t("ai.layer.budgetCard.barValue", { share: probText(ratio, 0) });
  const fill =
    ratio === null
      ? "bg-muted-foreground/40"
      : ratio >= 1
        ? "bg-negative"
        : ratio >= 0.85
          ? "bg-warning"
          : "bg-primary";
  return (
    <div className="space-y-2" data-testid="ai-month-bar">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-caption">
        <span className="uppercase tracking-wider text-subtle-foreground">
          {t("ai.layer.budgetCard.bar")}
        </span>
        <span className="numeric text-muted-foreground">{share}</span>
      </div>
      <div
        role="progressbar"
        aria-label={t("ai.layer.budgetCard.bar")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(width)}
        aria-valuetext={share}
        className="relative h-2.5 rounded-full bg-muted"
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", fill)}
          style={{ width: `${width}%` }}
        />
        {markers.map((m) => (
          <span
            key={m.threshold}
            aria-hidden
            className={cn(
              "absolute -bottom-1 -top-1 w-0.5 -translate-x-1/2 rounded-full",
              m.crossed ? (m.threshold >= 100 ? "bg-negative" : "bg-warning") : "bg-border-strong",
            )}
            style={{ left: `${Math.min(100, m.threshold)}%` }}
          />
        ))}
      </div>
      <ul className="flex flex-wrap gap-1.5" aria-label={t("ai.v2.alerts.title")}>
        {markers.map((m) => (
          <li
            key={m.threshold}
            title={
              m.alert
                ? t("ai.v2.alerts.reached", {
                    threshold: thresholdText(m.threshold),
                    when: bogotaDateTime(m.alert.at),
                    spent: usd(m.alert.spent_usd),
                    budget: usd(m.alert.budget_usd),
                  })
                : t("ai.v2.alerts.pending", { threshold: thresholdText(m.threshold) })
            }
          >
            <StatusBadge
              tone={m.crossed ? (m.threshold >= 100 ? "negative" : "warning") : "neutral"}
              dot={m.crossed}
            >
              <span className="numeric">{thresholdText(m.threshold)}</span>
              {m.alert ? <span className="normal-case">{bogotaDateTime(m.alert.at)}</span> : null}
            </StatusBadge>
          </li>
        ))}
      </ul>
      {alerts.length === 0 ? <Note>{t("ai.v2.alerts.none")}</Note> : null}
    </div>
  );
}

/** A period's spend by level (L1 / L2 / L3 / web): what each cost and how many calls. */
export function LevelCosts({ period }: { period: AiCostPeriod }) {
  const rows = levelRows(period.by_level);
  if (!rows.length) return <Note>{t("ai.v2.costs.noLevel")}</Note>;
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {rows.map((r) => (
        <li key={r.key} className="min-w-0 rounded-md border border-border px-2.5 py-2">
          <LevelBadge level={r.key} />
          <div className="numeric mt-1.5 text-sm font-semibold">{usd(r.cost_usd)}</div>
          <div className="text-caption text-subtle-foreground">
            {t("ai.v2.costs.requests", { count: r.requests, n: localInt(r.requests) })}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** A period's unit costs: per match, analysis, search, reviewed pick, approved pick, selected pick. */
export function UnitCosts({ period }: { period: AiCostPeriod }) {
  const rows: Array<[string, number | null | undefined]> = [
    [t("ai.v2.costs.perMatch"), period.cost_per_match],
    [t("ai.v2.costs.perAnalysis"), period.cost_per_analysis],
    [t("ai.v2.costs.perSearch"), period.cost_per_search],
    [t("ai.v2.costs.perReviewedPick"), period.cost_per_review],
    [t("ai.v2.costs.perApproved"), period.cost_per_approved],
    [t("ai.v2.costs.perSelected"), period.cost_per_selected],
  ];
  return (
    <div>
      {rows.map(([label, value]) => (
        <KeyValue key={label} label={label} value={usd(value)} />
      ))}
    </div>
  );
}

/** A few labelled values of an evidence object, as small pills (never a JSON dump). */
export function EvidenceChips({ items, label }: { items: EvidenceItem[]; label?: string }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1">
      {label ? <SubTitle>{label}</SubTitle> : null}
      <ul className="flex flex-wrap gap-1.5">
        {items.map((i) => (
          <li
            key={i.key}
            className="max-w-full rounded border border-border bg-elevated/50 px-1.5 py-0.5 text-caption wrap-anywhere"
          >
            <span className="text-subtle-foreground">{i.label}:</span>{" "}
            <span className="numeric text-foreground">{i.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** QUÉ APRENDIÓ PREDIGOL: one note - its kind, who wrote it (LLM or the rules), its sample and evidence. */
export function NoteCard({ note }: { note: LearningNote }) {
  const items = evidenceSummary(note.evidence, { max: 6 });
  return (
    <li
      className="min-w-0 space-y-1.5 rounded-md border border-border bg-card p-3"
      data-testid="learning-note"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={note.kind === "lesson" ? "brand" : "info"}>
          {translateOr(`ai.v2.noteKind.${note.kind}`, note.kind)}
        </StatusBadge>
        <EngineBadge engine={note.engine} />
        <span className="numeric text-caption text-subtle-foreground">
          {t("ai.v2.sample", { n: localInt(note.n) })}
        </span>
      </div>
      <p className="text-sm font-medium wrap-anywhere">{note.title}</p>
      <p className="text-xs leading-relaxed text-muted-foreground wrap-anywhere">{note.body}</p>
      <EvidenceChips items={items} />
    </li>
  );
}

function Field({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={cn("min-w-0", wide && "sm:col-span-2")}>
      <dt className="text-caption uppercase tracking-wider text-subtle-foreground">{label}</dt>
      <dd className="mt-0.5 text-xs text-foreground wrap-anywhere">{children}</dd>
    </div>
  );
}

/**
 * MEJORAS PROPUESTAS: a hypothesis awaiting the owner - why, on how many matches, its potential impact, what
 * investigating it would cost and its evidence. `children` carries the owner's buttons (Evolución) or a link.
 */
export function ProposalCard({ p, children }: { p: Proposal; children?: ReactNode }) {
  const items = evidenceSummary(p.evidence, {
    omit: ["n_matches", "impact", "investigation_cost"],
    max: 6,
  });
  const n = toNum(p.n_matches);
  return (
    <li
      className="min-w-0 space-y-2.5 rounded-md border border-border bg-card p-3"
      data-testid="proposal"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={p.status === "INVESTIGATING" ? "warning" : "info"}>
          {translateOr(`ai.evolution.status.${p.status}`, p.status)}
        </StatusBadge>
        <StatusBadge tone={p.proposed_by === "ai" ? "brand" : "neutral"}>
          {translateOr(`ai.evolution.by.${p.proposed_by}`, p.proposed_by)}
        </StatusBadge>
        <StatusBadge tone="neutral">
          {translateOr(`ai.evolution.target.${p.target}`, p.target)}
        </StatusBadge>
        <span className="text-caption text-subtle-foreground">
          {bogotaDateTime(p.created_at)} · Bogotá
        </span>
      </div>
      <p className="text-sm font-medium wrap-anywhere">{p.title}</p>
      <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-2">
        <Field label={t("ai.evolution.proposals.hypothesis")} wide>
          {p.hypothesis}
        </Field>
        <Field label={t("ai.evolution.proposals.rationale")} wide>
          {p.rationale || "—"}
        </Field>
        <Field label={t("ai.evolution.proposals.nMatches")}>
          <span className="numeric">{n === null ? "—" : localInt(n)}</span>
        </Field>
        <Field label={t("ai.evolution.proposals.impact")}>{p.impact || "—"}</Field>
        <Field label={t("ai.evolution.proposals.cost")} wide>
          {p.investigation_cost || "—"}
        </Field>
      </dl>
      <EvidenceChips items={items} label={t("ai.evolution.proposals.evidence")} />
      {children}
    </li>
  );
}
