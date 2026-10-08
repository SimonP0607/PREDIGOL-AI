/**
 * Evolución - the owner's decision center. What the AI layer did today (matches analysed, news, injuries,
 * line-ups, market moves, reviews and their decisions, cost), what results taught (findings, errors), and
 * the hypotheses waiting for the owner: RECHAZAR, INVESTIGAR or APROBAR EXPERIMENTO. An approved experiment
 * goes through backtest and shadow; only a DONE experiment whose gate passed can be PROMOTED, by the owner,
 * typing the word. There is no "activate automatically": nothing here changes a rule, a model or a pick.
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { t } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { dueReason } from "./evolutionDue";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  Hypothesis,
  HypothesisDecision,
  HypothesisTarget,
  MemoryEntry,
} from "@/lib/api/v1/types_ai";
import type { EvolutionDashboard } from "@/lib/api/v1/types_ai_layer";
import {
  DECISION_TONE,
  HYPOTHESIS_TONE,
  PROMOTE_WORD,
  canPromote,
  decisionsFor,
  groupOf,
  promoteUnlocked,
  type HypothesisGroup,
} from "./aiModel";
import { isoDay, utcDateTime } from "./format";

const STEPS = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"] as const;
const TARGETS: HypothesisTarget[] = [
  "models",
  "backtesting",
  "analytics",
  "features",
  "rankings",
  "pick_engine",
  "decision_rules",
  "data",
  "ai",
  "other",
];
const GROUPS: HypothesisGroup[] = ["pending", "promotable", "experiment", "closed"];
const COUNT_KEYS = [
  "matches_analyzed",
  "news",
  "injuries",
  "lineups",
  "market_moves",
  "picks_evaluated",
  "approved",
  "downgraded",
  "rejected",
  "abstained",
  "llm_reviews",
  "postmortems",
  "hypotheses",
] as const;
const INPUT =
  "w-full rounded-md border border-border bg-card px-2 py-1.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";
const DECISION_STYLE: Record<HypothesisDecision, string> = {
  reject: "border-border hover:bg-elevated",
  investigate: "border-warning/40 bg-warning-soft text-warning",
  approve_experiment: "border-positive/40 bg-positive-soft text-positive",
};

function invalidate(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["v1", "evolution"] });
}

// ── the day ──────────────────────────────────────────────────────────────────

function DayDashboard({ day, onDay }: { day: string; onDay: (d: string) => void }) {
  const q = useLiveQuery(live.evolutionDashboard(day));
  const d: EvolutionDashboard | null = q.data?.data ?? null;
  const combined = d?.shadow.find((s) => s.engine === "combined") ?? null;
  return (
    <Panel
      title={t("ai.evolution.dashboard.title")}
      subtitle={t("ai.evolution.dashboard.subtitle")}
      actions={
        <input
          type="date"
          value={day}
          max={isoDay(new Date())}
          onChange={(e) => e.target.value && onDay(e.target.value)}
          aria-label={t("ai.evolution.dashboard.day")}
          className="h-8 rounded-md border border-border bg-card px-2 text-xs"
        />
      }
    >
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={2} cols={6} /> : null}
      {d ? (
        <div className="space-y-3">
          <dl
            className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7"
            data-testid="evolution-counts"
          >
            {COUNT_KEYS.map((k) => (
              <div key={k} className="rounded-md border border-border bg-card px-2.5 py-2">
                <dt className="text-caption uppercase tracking-wider text-subtle-foreground">
                  {t(`ai.evolution.dashboard.counts.${k}`)}
                </dt>
                <dd className="numeric text-base font-semibold">{localInt(d.counts[k] ?? 0)}</dd>
              </div>
            ))}
            <div className="rounded-md border border-border bg-card px-2.5 py-2">
              <dt className="text-caption uppercase tracking-wider text-subtle-foreground">
                {t("ai.evolution.dashboard.cost")}
              </dt>
              <dd className="numeric text-base font-semibold">
                US$ {Number(d.cost_usd).toFixed(4)}
              </dd>
            </div>
          </dl>
          <div className="flex flex-wrap items-center gap-2 text-caption text-subtle-foreground">
            <span>{t("ai.evolution.dashboard.gate")}</span>
            <StatusBadge
              tone={
                combined?.verdict === "pass"
                  ? "positive"
                  : combined?.verdict === "fail"
                    ? "negative"
                    : "neutral"
              }
            >
              {t(`ai.layer.gate.${combined?.verdict ?? "none"}`)}
            </StatusBadge>
            <span>{t("ai.evolution.dashboard.gateHelp")}</span>
          </div>
        </div>
      ) : null}
    </Panel>
  );
}

function Findings({ day }: { day: string }) {
  const q = useLiveQuery(live.evolutionDashboard(day));
  const findings = q.data?.data?.findings ?? [];
  return (
    <Panel title={t("ai.evolution.findings.title")} subtitle={t("ai.evolution.findings.subtitle")}>
      {findings.length === 0 ? (
        <p className="text-xs text-subtle-foreground">{t("ai.evolution.findings.empty")}</p>
      ) : (
        <ul className="space-y-2" data-testid="evolution-findings">
          {findings.map((f) => (
            <li key={f.id} className="space-y-1 border-b border-border pb-2 last:border-0">
              <div className="flex flex-wrap items-center gap-1.5 text-caption text-subtle-foreground">
                <StatusBadge
                  tone={
                    f.kind.endsWith("failure") || f.kind === "context_error" ? "negative" : "info"
                  }
                >
                  {t(`ai.layer.memoryKind.${f.kind}`)}
                </StatusBadge>
                <span>
                  {f.entity_type}:{f.entity_id}
                </span>
                <span>· {utcDateTime(f.created_at)}</span>
              </div>
              {f.hypothesis ? (
                <p className="text-xs text-muted-foreground">{f.hypothesis}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Errors({ day }: { day: string }) {
  const q = useLiveQuery(live.evolutionDashboard(day));
  const errors = q.data?.data?.errors ?? [];
  return (
    <Panel title={t("ai.evolution.errors.title")} subtitle={t("ai.evolution.errors.subtitle")}>
      {errors.length === 0 ? (
        <p className="text-xs text-subtle-foreground">{t("ai.evolution.errors.empty")}</p>
      ) : (
        <ul className="space-y-2" data-testid="evolution-errors">
          {errors.map((e, i) => (
            <li
              key={`${e.fixture_id}-${i}`}
              className="space-y-1 rounded-md border border-border p-2.5"
            >
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="font-medium">{e.match}</span>
                {e.score ? <span className="numeric">{e.score.join("–")}</span> : null}
                {e.decision ? (
                  <StatusBadge tone={DECISION_TONE[e.decision]}>
                    {t(`ai.layer.decision.${e.decision}`)}
                  </StatusBadge>
                ) : null}
                <StatusBadge tone={e.settled === "win" ? "positive" : "negative"}>
                  {t(`ai.evolution.errors.settled.${e.settled === "win" ? "win" : "loss"}`)}
                </StatusBadge>
              </div>
              <p className="text-caption text-subtle-foreground">
                {e.market} · {e.selection}
                {e.line && e.line !== "0" ? ` ${e.line}` : ""}
                {e.signals.length ? ` · ${e.signals.join(", ")}` : ""}
              </p>
              {e.narrative ? <p className="text-xs text-muted-foreground">{e.narrative}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

// ── hypotheses ──────────────────────────────────────────────────────────────

function Decide({ h }: { h: Hypothesis }) {
  const [note, setNote] = useState("");
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (decision: HypothesisDecision) => v1.decideHypothesis(h.id, decision, note),
    onSuccess: () => invalidate(qc),
  });
  const options = decisionsFor(h.status);
  if (!options.length) return null;
  return (
    <div className="space-y-2">
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={500}
        placeholder={t("ai.evolution.note")}
        aria-label={t("ai.evolution.note")}
        className={INPUT}
      />
      <div className="flex flex-wrap gap-2">
        {options.map((d) => (
          <button
            key={d}
            type="button"
            data-decision={d}
            disabled={decide.isPending}
            onClick={() => decide.mutate(d)}
            className={`h-7 rounded-md border px-2.5 text-xs font-medium uppercase tracking-wide disabled:opacity-50 ${DECISION_STYLE[d]}`}
          >
            {t(`ai.evolution.decide.${d}`)}
          </button>
        ))}
      </div>
      {decide.isError ? <ApiErrorNotice error={decide.error} /> : null}
    </div>
  );
}

function Promote({ h }: { h: Hypothesis }) {
  const [typed, setTyped] = useState("");
  const [note, setNote] = useState("");
  const qc = useQueryClient();
  const promote = useMutation({
    mutationFn: () => v1.promoteHypothesis(h.id, note),
    onSuccess: () => invalidate(qc),
  });
  if (!canPromote(h)) return null;
  return (
    <div className="space-y-2 rounded-md border border-positive/30 bg-positive-soft/40 p-2.5">
      <p className="text-caption text-muted-foreground">
        {t("ai.evolution.promote.help", { word: PROMOTE_WORD })}
      </p>
      <input
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        aria-label={t("ai.evolution.promote.type", { word: PROMOTE_WORD })}
        placeholder={PROMOTE_WORD}
        className={INPUT}
      />
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={500}
        placeholder={t("ai.evolution.note")}
        aria-label={t("ai.evolution.note")}
        className={INPUT}
      />
      <button
        type="button"
        disabled={!promoteUnlocked(typed) || promote.isPending}
        onClick={() => promote.mutate()}
        className="h-7 rounded-md bg-positive px-2.5 text-xs font-medium uppercase text-positive-foreground disabled:opacity-50"
      >
        {t("ai.evolution.promote.button")}
      </button>
      {promote.isError ? <ApiErrorNotice error={promote.error} /> : null}
    </div>
  );
}

function HypothesisCard({ h }: { h: Hypothesis }) {
  return (
    <li className="space-y-2 rounded-md border border-border p-3" data-testid="hypothesis">
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={HYPOTHESIS_TONE[h.status]}>
          <span data-status={h.status}>{t(`ai.evolution.status.${h.status}`)}</span>
        </StatusBadge>
        <StatusBadge tone={h.proposed_by === "ai" ? "brand" : "neutral"}>
          {t(`ai.evolution.by.${h.proposed_by}`)}
        </StatusBadge>
        {h.target ? (
          <StatusBadge tone="neutral">{t(`ai.evolution.target.${h.target}`)}</StatusBadge>
        ) : null}
        <span className="text-caption text-subtle-foreground">{utcDateTime(h.created_at)}</span>
      </div>
      <p className="text-sm font-medium">{h.title}</p>
      <p className="text-xs text-muted-foreground">{h.hypothesis}</p>
      <p className="text-caption text-subtle-foreground">
        <span className="font-medium">{t("ai.evolution.rationale")}:</span> {h.rationale}
      </p>
      {Object.keys(h.evidence).length ? (
        <details className="text-caption text-subtle-foreground">
          <summary className="cursor-pointer">{t("ai.evolution.evidence")}</summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded border border-border bg-card p-2">
            {JSON.stringify(h.evidence, null, 2)}
          </pre>
        </details>
      ) : null}
      {h.stage_history && h.stage_history.length ? (
        <ol
          className="flex flex-wrap gap-1 text-caption text-subtle-foreground"
          aria-label={t("ai.evolution.history")}
        >
          {h.stage_history.map((s, i) => (
            <li key={i}>
              {i ? "→ " : ""}
              {t(`ai.evolution.status.${s.to}`)} · {utcDateTime(s.at)}
            </li>
          ))}
        </ol>
      ) : null}
      {h.outcome ? (
        <p className="text-caption text-subtle-foreground">
          {t("ai.evolution.outcome", {
            verdict:
              h.outcome["gate_passed"] === true ? t("ai.layer.gate.pass") : t("ai.layer.gate.fail"),
          })}
        </p>
      ) : null}
      <Decide h={h} />
      <Promote h={h} />
      {h.decided_at && !decisionsFor(h.status).length ? (
        <p className="text-caption text-subtle-foreground">
          {t("ai.evolution.decided", { who: h.decided_by ?? "—", when: utcDateTime(h.decided_at) })}
          {h.decision_note ? ` · ${h.decision_note}` : ""}
        </p>
      ) : null}
    </li>
  );
}

function HypothesesBoard({ hypotheses }: { hypotheses: Hypothesis[] }) {
  const by = new Map<HypothesisGroup, Hypothesis[]>(GROUPS.map((g) => [g, []]));
  for (const h of hypotheses) by.get(groupOf(h))?.push(h);
  return (
    <Panel
      title={t("ai.evolution.hypotheses")}
      subtitle={t("ai.evolution.hypothesesHelp")}
      actions={
        <span className="text-caption text-subtle-foreground">
          {t("ai.evolution.counts", {
            proposed: localInt(by.get("pending")?.length ?? 0),
            decided: localInt(hypotheses.length - (by.get("pending")?.length ?? 0)),
          })}
        </span>
      }
    >
      {hypotheses.length === 0 ? (
        <p className="text-xs text-subtle-foreground">{t("ai.evolution.empty")}</p>
      ) : (
        <div className="space-y-4">
          {GROUPS.map((g) => {
            const items = by.get(g) ?? [];
            if (!items.length) return null;
            return (
              <section key={g} className="space-y-2" data-group={g}>
                <h3 className="text-caption font-medium uppercase tracking-wider text-subtle-foreground">
                  {t(`ai.evolution.groups.${g}`)} · {localInt(items.length)}
                </h3>
                <ul className="space-y-2">
                  {items.map((h) => (
                    <HypothesisCard key={h.id} h={h} />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function Propose() {
  const [title, setTitle] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [rationale, setRationale] = useState("");
  const [target, setTarget] = useState<HypothesisTarget>("other");
  const qc = useQueryClient();
  const make = useMutation({
    mutationFn: () => v1.proposeHypothesis({ title, hypothesis, rationale, target }),
    onSuccess: () => {
      setTitle("");
      setHypothesis("");
      setRationale("");
      invalidate(qc);
    },
  });
  const ready =
    title.trim().length >= 5 && hypothesis.trim().length >= 5 && rationale.trim().length >= 5;
  return (
    <Panel title={t("ai.evolution.propose.title")} subtitle={t("ai.evolution.propose.subtitle")}>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) make.mutate();
        }}
      >
        <label className="block space-y-1 text-caption text-subtle-foreground">
          {t("ai.evolution.propose.fieldTitle")}
          <input
            value={title}
            maxLength={160}
            onChange={(e) => setTitle(e.target.value)}
            className={INPUT}
          />
        </label>
        <label className="block space-y-1 text-caption text-subtle-foreground">
          {t("ai.evolution.propose.fieldHypothesis")}
          <textarea
            value={hypothesis}
            maxLength={600}
            rows={2}
            onChange={(e) => setHypothesis(e.target.value)}
            className={INPUT}
          />
        </label>
        <label className="block space-y-1 text-caption text-subtle-foreground">
          {t("ai.evolution.propose.fieldRationale")}
          <textarea
            value={rationale}
            maxLength={1000}
            rows={2}
            onChange={(e) => setRationale(e.target.value)}
            className={INPUT}
          />
        </label>
        <label className="block space-y-1 text-caption text-subtle-foreground">
          {t("ai.evolution.propose.fieldTarget")}
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value as HypothesisTarget)}
            className={INPUT}
          >
            {TARGETS.map((x) => (
              <option key={x} value={x}>
                {t(`ai.evolution.target.${x}`)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={!ready || make.isPending}
          className="h-8 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {t("ai.evolution.propose.submit")}
        </button>
        {make.isSuccess ? (
          <p className="text-caption text-positive">{t("ai.evolution.propose.done")}</p>
        ) : null}
        {make.isError ? <ApiErrorNotice error={make.error} /> : null}
      </form>
    </Panel>
  );
}

function MemoryList({ memory }: { memory: MemoryEntry[] }) {
  if (!memory.length)
    return <p className="text-xs text-subtle-foreground">{t("ai.evolution.emptyMemory")}</p>;
  return (
    <ul className="space-y-2" data-testid="memory">
      {memory.map((m) => (
        <li key={m.id} className="space-y-1 border-b border-border pb-2 last:border-0">
          <div className="flex flex-wrap items-center gap-1.5 text-caption text-subtle-foreground">
            <StatusBadge tone="neutral">{t(`ai.evolution.source.${m.source}`)}</StatusBadge>
            <span className="numeric">{m.topic}</span>
            <span>· {utcDateTime(m.created_at)}</span>
            {m.versions > 1 ? (
              <span>· {t("ai.evolution.versions", { count: localInt(m.versions) })}</span>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">{m.finding}</p>
        </li>
      ))}
    </ul>
  );
}

/** What this page is today, in plain words: a shadow layer that proposes; the owner decides. */
function Honesty() {
  const ai = useLiveQuery(live.aiOverview);
  const o = ai.data?.data ?? null;
  const llm = o?.settings.llm_configured ?? false;
  return (
    <Panel title={t("ai.evolution.today.title")} bodyClassName="p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-1.5" data-testid="evolution-today">
        <StatusBadge tone="neutral">
          {t("ai.evolution.today.mode", {
            mode: t(`ai.layer.mode.${o?.settings.mode ?? "shadow"}`),
          })}
        </StatusBadge>
        <StatusBadge tone={llm ? "brand" : "neutral"}>
          {llm ? t("ai.evolution.today.aiOn") : t("ai.evolution.today.aiOff")}
        </StatusBadge>
        <StatusBadge tone={o?.enforcement.enforced ? "warning" : "neutral"}>
          {o?.enforcement.enforced ? t("ai.layer.enforced") : t("ai.layer.notEnforced")}
        </StatusBadge>
      </div>
      <p className="text-xs text-muted-foreground">{t("ai.evolution.today.body")}</p>
      <p className="text-xs text-muted-foreground">{t("ai.evolution.today.never")}</p>
    </Panel>
  );
}

export function EvolutionLive() {
  const q = useLiveQuery(live.evolution);
  const d = q.data?.data ?? null;
  const [day, setDay] = useState(() => isoDay(new Date()));
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.evolution.title")}
        description={t("admin.pages.evolution.description")}
      />
      <WarningBanner tone="info">{t("ai.evolution.noAuto")}</WarningBanner>
      <DayDashboard day={day} onDay={setDay} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Findings day={day} />
        <Errors day={day} />
      </div>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={5} cols={3} /> : null}
      {d ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <HypothesesBoard hypotheses={d.hypotheses} />
          <div className="space-y-4">
            <Honesty />
            <Panel title={t("ai.evolution.loopTitle")}>
              <ol className="list-decimal space-y-1.5 pl-4 text-xs text-muted-foreground">
                {STEPS.map((s) => (
                  <li key={s}>{t(`ai.evolution.loop.${s}`)}</li>
                ))}
              </ol>
            </Panel>
            <Panel bodyClassName="p-4 space-y-1">
              <KeyValue
                label={t("ai.evolution.lastMonitor")}
                value={d.last_monitor ? utcDateTime(d.last_monitor) : t("ai.evolution.never")}
              />
              <KeyValue
                label={t("ai.evolution.lastV2")}
                value={
                  d.last_v2 ? (
                    <span title={d.last_v2.name} className="block max-w-[14rem] truncate">
                      {d.last_v2.finished_at ? utcDateTime(d.last_v2.finished_at) : d.last_v2.name}
                    </span>
                  ) : (
                    t("ai.evolution.never")
                  )
                }
              />
              {d.research_frozen ? (
                <p className="pt-1 text-caption text-warning">
                  {t("ai.evolution.frozen", { reason: d.research_frozen })}
                </p>
              ) : null}
              <p className="pt-1 text-caption text-subtle-foreground">
                {d.v2_due
                  ? t(d.research_frozen ? "ai.evolution.dueWhenUnfrozen" : "ai.evolution.due", {
                      reason: dueReason(d),
                    })
                  : t("ai.evolution.notDue")}
              </p>
            </Panel>
            <Propose />
            <Panel title={t("ai.evolution.memory")} subtitle={t("ai.evolution.memoryHelp")}>
              <MemoryList memory={d.memory} />
            </Panel>
          </div>
        </div>
      ) : null}
    </div>
  );
}
