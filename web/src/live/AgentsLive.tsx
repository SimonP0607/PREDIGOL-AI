/**
 * AGENTES (Operación, plan IA, phase 1): the agents of PrediGol Intelligence as the owner reads them. What the registry says exists and whether the
 * code that runs is the code it holds; which engine each family of markets reads (the newest promotion row decides, none means the language model of
 * today) and the owner's latest decisions; what the job that writes the state of each match did - how many states, how big each slice is against
 * its cap, how long it took, how the job itself fared -; the Orchestrator's queue (empty until phase 3); and the nightly audit of what an agent
 * may know. Reading only: nothing here calls a model, creates a task or changes a pick. The file of one match is in "Partido" (MatchStatePanel).
 */
import type { ReactNode } from "react";
import { t, translateOr } from "@/lib/i18n";
import { DASH, localInt, localPct } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { cn } from "@/lib/utils";
import type {
  AgentView,
  AgentsOverview,
  AgentsSettings,
  AuditRule,
  FamilyEngine,
  PackageStats,
  PromotionRow,
  QueueStats,
  SliceStat,
} from "@/lib/api/v1/types_ai_agents";
import { Fact, Note, Stat, StatGrid, SubTitle } from "./AiBits";
import { bogotaDateTime, dayShort, usd } from "./aiModel";
import { durationMs } from "./format";
import {
  AUDIT_TONE,
  ENGINE_TONE,
  PASSES,
  RUN_STATUSES,
  SLICE_TONE,
  STATUS_TONE,
  SYNC_TONE,
  TASK_STATES,
  attention,
  auditVerdict,
  capShare,
  decisionChange,
  orderedCounts,
  promotionLine,
  registryCounts,
  sliceLevel,
  syncState,
  taskLine,
} from "./agentsModel";

/** A titled block inside a panel: the title, a line of what it means, then the block. */
function Block({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <SubTitle>{title}</SubTitle>
      {hint ? <Note>{hint}</Note> : null}
      {children}
    </div>
  );
}

/** A table inside a padded panel: its own frame, so its edge fade and its scroll stay inside the card. */
function Framed({ children }: { children: ReactNode }) {
  return <div className="overflow-hidden rounded-md border border-border">{children}</div>;
}

/** A framed list of things to look at: a warning, or an alarm when what it lists is a fault of ours. */
function Notice({
  tone,
  testId,
  title,
  children,
}: {
  tone: "warning" | "negative";
  testId: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div
      role={tone === "negative" ? "alert" : undefined}
      data-tone={tone}
      data-testid={testId}
      className={cn(
        "rounded-md border px-3 py-2 text-xs",
        tone === "negative"
          ? "border-negative/35 bg-negative-soft"
          : "border-warning/35 bg-warning-soft",
      )}
    >
      <div className="font-medium">{title}</div>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-foreground/85">{children}</ul>
    </div>
  );
}

/** What the owner should look at, most serious first - or, honestly, that there is nothing. */
function AttentionLine({ o }: { o: AgentsOverview }) {
  const items = attention(o);
  if (items.length === 0) {
    return (
      <div
        className="flex flex-wrap items-center gap-2 rounded-md border border-positive/30 bg-positive-soft px-3 py-2 text-xs"
        data-testid="agents-attention"
      >
        <StatusBadge tone="positive">{t("ai.agents.attention.title")}</StatusBadge>
        <span className="min-w-0 text-foreground/85">{t("ai.agents.attention.none")}</span>
      </div>
    );
  }
  const serious = items.some((i) => i.code === "audit_violations" || i.code === "drift");
  return (
    <Notice
      tone={serious ? "negative" : "warning"}
      testId="agents-attention"
      title={t("ai.agents.attention.title")}
    >
      {items.map((i) => (
        <li key={i.code}>{t(`ai.agents.attention.${i.code}`, { n: i.n })}</li>
      ))}
    </Notice>
  );
}

// ── the registry ─────────────────────────────────────────────────────────────

/** What the plan says of an agent: the phase that builds it, what it replaces, when it is retired, what comes after it, the gate that wakes it. */
function PlanCell({ a }: { a: AgentView }) {
  const lines: string[] = [];
  if (a.status === "built") {
    if (a.baseline) lines.push(t("ai.agents.registry.baseline"));
    if (a.retire_phase !== null) lines.push(t("ai.agents.registry.retires", { n: a.retire_phase }));
    if (a.next_version !== null && a.next_phase !== null)
      lines.push(t("ai.agents.registry.next", { version: a.next_version, n: a.next_phase }));
  }
  if (a.status === "planned") {
    if (a.phase !== null) lines.push(t("ai.agents.registry.phase", { n: a.phase }));
    if (a.replaces !== null) lines.push(t("ai.agents.registry.replaces", { what: a.replaces }));
  }
  if (a.status === "postponed" && a.gate !== null) lines.push(a.gate);
  if (lines.length === 0) return <span className="text-muted-foreground">{DASH}</span>;
  return (
    <div className="space-y-0.5 text-xs">
      {lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

function RegistryRow({ a }: { a: AgentView }) {
  const sync = syncState(a);
  return (
    <TRow>
      <TD className="max-w-[22rem]">
        <div className="font-medium">{a.agent}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{a.purpose}</div>
      </TD>
      <TD>
        <StatusBadge tone={STATUS_TONE[a.status]} dot={false}>
          {t(`ai.agents.registry.status.${a.status}`)}
        </StatusBadge>
      </TD>
      <TD>
        <div className="numeric text-xs">{a.version ?? DASH}</div>
        {a.status === "built" ? (
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="numeric text-caption text-muted-foreground">
              {a.fingerprint ?? DASH}
            </span>
            <StatusBadge tone={SYNC_TONE[sync]} dot={false}>
              {t(`ai.agents.registry.sync.${sync}`)}
            </StatusBadge>
          </div>
        ) : null}
      </TD>
      <TD>
        <div className="numeric text-xs">{a.contract ?? DASH}</div>
        {a.tasks.map((task) => (
          <div key={task.task} className="numeric text-caption text-muted-foreground">
            {taskLine(task)}
          </div>
        ))}
      </TD>
      <TD>
        <PlanCell a={a} />
      </TD>
    </TRow>
  );
}

function RegistryPanel({ o }: { o: AgentsOverview }) {
  const counts = registryCounts(o.registry);
  return (
    <Panel
      title={t("ai.agents.registry.title")}
      subtitle={t("ai.agents.registry.subtitle")}
      bodyClassName="space-y-3 p-4"
    >
      <StatGrid testId="agents-registry-counts">
        <Stat label={t("ai.agents.registry.counts.built")} value={localInt(counts.built)} />
        <Stat label={t("ai.agents.registry.counts.planned")} value={localInt(counts.planned)} />
        <Stat label={t("ai.agents.registry.counts.postponed")} value={localInt(counts.postponed)} />
        <Stat
          label={t("ai.agents.registry.counts.drift")}
          value={localInt(counts.drift)}
          tone={counts.drift > 0 ? "negative" : "positive"}
        />
      </StatGrid>
      {o.problems.length > 0 ? (
        <Notice
          tone="negative"
          testId="agents-problems"
          title={t("ai.agents.registry.problemsTitle")}
        >
          {o.problems.map((p) => (
            <li key={`${p.code}:${p.subject}`}>
              <span className="numeric">
                {p.code} · {p.subject}
              </span>
              : {p.text}
            </li>
          ))}
        </Notice>
      ) : (
        <Note>{t("ai.agents.registry.noProblems")}</Note>
      )}
      <Framed>
        <TableShell>
          <THead>
            <TH>{t("ai.agents.registry.col.agent")}</TH>
            <TH>{t("ai.agents.registry.col.status")}</TH>
            <TH>{t("ai.agents.registry.col.version")}</TH>
            <TH>{t("ai.agents.registry.col.contract")}</TH>
            <TH>{t("ai.agents.registry.col.plan")}</TH>
          </THead>
          <tbody>
            {o.registry.map((a) => (
              <RegistryRow key={a.agent} a={a} />
            ))}
          </tbody>
        </TableShell>
      </Framed>
    </Panel>
  );
}

// ── the engine of each family, and the decisions ─────────────────────────────

function EngineRow({ f }: { f: FamilyEngine }) {
  const { name, understood } = promotionLine(f);
  return (
    <TRow>
      <TD className="font-medium">{f.family}</TD>
      <TD>
        <StatusBadge tone={ENGINE_TONE[f.engine]} dot={false}>
          {t(`ai.agents.engines.engineName.${f.engine}`)}
        </StatusBadge>
      </TD>
      <TD>
        {name === null ? (
          <span className="text-muted-foreground">{DASH}</span>
        ) : (
          <>
            <div className="numeric text-xs">{name}</div>
            {understood ? null : (
              <div className="text-caption text-warning">
                {t("ai.agents.engines.notUnderstood")}
              </div>
            )}
          </>
        )}
      </TD>
      <TD className="text-xs">{f.since ? bogotaDateTime(f.since) : DASH}</TD>
    </TRow>
  );
}

function DecisionRow({ d }: { d: PromotionRow }) {
  return (
    <TRow>
      <TD className="whitespace-nowrap text-xs">{bogotaDateTime(d.at)}</TD>
      <TD className="font-medium">{d.family ?? DASH}</TD>
      <TD className="numeric text-xs">{d.promotion ?? DASH}</TD>
      <TD className="numeric whitespace-nowrap text-xs">{decisionChange(d)}</TD>
      <TD>
        <StatusBadge tone={d.decided_by === "owner" ? "brand" : "warning"} dot={false}>
          {t(`ai.agents.decisions.by.${d.decided_by}`)}
        </StatusBadge>
      </TD>
      <TD className="numeric text-xs">{d.gate_version}</TD>
      <TD className="max-w-[24rem] break-words text-xs">{d.reason}</TD>
    </TRow>
  );
}

function EnginesPanel({
  families,
  decisions,
}: {
  families: FamilyEngine[];
  decisions: PromotionRow[];
}) {
  return (
    <Panel
      title={t("ai.agents.engines.title")}
      subtitle={t("ai.agents.engines.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <Framed>
        <TableShell compact>
          <THead>
            <TH>{t("ai.agents.engines.col.family")}</TH>
            <TH>{t("ai.agents.engines.col.engine")}</TH>
            <TH>{t("ai.agents.engines.col.promotion")}</TH>
            <TH>{t("ai.agents.engines.col.since")}</TH>
          </THead>
          <tbody>
            {families.map((f) => (
              <EngineRow key={f.family} f={f} />
            ))}
          </tbody>
        </TableShell>
      </Framed>
      <Block title={t("ai.agents.decisions.title")}>
        {decisions.length === 0 ? (
          <Note>{t("ai.agents.decisions.empty")}</Note>
        ) : (
          <Framed>
            <TableShell>
              <THead>
                <TH>{t("ai.agents.decisions.col.when")}</TH>
                <TH>{t("ai.agents.decisions.col.family")}</TH>
                <TH>{t("ai.agents.decisions.col.promotion")}</TH>
                <TH>{t("ai.agents.decisions.col.change")}</TH>
                <TH>{t("ai.agents.decisions.col.by")}</TH>
                <TH>{t("ai.agents.decisions.col.gate")}</TH>
                <TH>{t("ai.agents.decisions.col.reason")}</TH>
              </THead>
              <tbody>
                {decisions.map((d) => (
                  <DecisionRow key={d.id} d={d} />
                ))}
              </tbody>
            </TableShell>
          </Framed>
        )}
      </Block>
    </Panel>
  );
}

// ── the states of the matches ────────────────────────────────────────────────

function SliceRow({ s }: { s: SliceStat }) {
  const level = sliceLevel(s);
  const share = capShare(s);
  return (
    <TRow>
      <TD className="font-medium">{s.name}</TD>
      <TD align="right">{localInt(s.states)}</TD>
      <TD align="right">{localInt(s.tokens_p50)}</TD>
      <TD align="right">{localInt(s.tokens_p95)}</TD>
      <TD align="right">{localInt(s.tokens_max)}</TD>
      <TD align="right">{localInt(s.cap)}</TD>
      <TD align="right">{share === null ? DASH : localPct(share, 0)}</TD>
      <TD align="right">{localInt(s.trimmed)}</TD>
      <TD align="right" className={s.over_cap > 0 ? "text-negative" : ""}>
        {localInt(s.over_cap)}
      </TD>
      <TD>
        <StatusBadge tone={SLICE_TONE[level]} dot={false}>
          {t(`ai.agents.package.slices.level.${level}`)}
        </StatusBadge>
      </TD>
    </TRow>
  );
}

function SlicesTable({ slices }: { slices: SliceStat[] }) {
  if (slices.length === 0) return <Note>{t("ai.agents.package.slices.empty")}</Note>;
  return (
    <Framed>
      <TableShell>
        <THead>
          <TH>{t("ai.agents.package.slices.col.slice")}</TH>
          <TH align="right">{t("ai.agents.package.slices.col.states")}</TH>
          <TH align="right">p50</TH>
          <TH align="right">p95</TH>
          <TH align="right">{t("ai.agents.package.slices.col.max")}</TH>
          <TH align="right">{t("ai.agents.package.slices.col.cap")}</TH>
          <TH align="right">{t("ai.agents.package.slices.col.share")}</TH>
          <TH align="right">{t("ai.agents.package.slices.col.trimmed")}</TH>
          <TH align="right">{t("ai.agents.package.slices.col.over")}</TH>
          <TH>{t("ai.agents.package.slices.col.level")}</TH>
        </THead>
        <tbody>
          {slices.map((s) => (
            <SliceRow key={s.name} s={s} />
          ))}
        </tbody>
      </TableShell>
    </Framed>
  );
}

function PackagePanel({ p, settings }: { p: PackageStats; settings: AgentsSettings }) {
  const last = p.cycles.last;
  const switchedOff = !settings.package;
  return (
    <Panel
      title={t("ai.agents.package.title")}
      subtitle={t("ai.agents.package.subtitle", { days: p.days })}
      bodyClassName="space-y-4 p-4"
    >
      <StatGrid testId="agents-package-stats">
        <Stat label={t("ai.agents.package.stat.states")} value={localInt(p.states)} />
        <Stat label={t("ai.agents.package.stat.matches")} value={localInt(p.matches)} />
        <Stat
          label={t("ai.agents.package.stat.blocked")}
          value={localInt(p.blocked)}
          hint={t("ai.agents.package.stat.blockedHint")}
          tone={p.blocked > 0 ? "warning" : "default"}
        />
        <Stat
          label={t("ai.agents.package.stat.flagged")}
          value={localInt(p.flagged)}
          hint={t("ai.agents.package.stat.flaggedHint")}
          tone={p.flagged > 0 ? "warning" : "default"}
        />
        <Stat
          label={t("ai.agents.package.stat.build")}
          value={[p.build_ms.p50, p.build_ms.p95, p.build_ms.max]
            .map((ms) => durationMs(ms))
            .join(" · ")}
          hint="p50 · p95 · max"
        />
        <Stat
          label={t("ai.agents.package.stat.cycles")}
          value={localInt(p.cycles.total)}
          hint={t("ai.agents.package.cyclesText", {
            ok: p.cycles.ok,
            partial: p.cycles.partial,
            failed: p.cycles.failed,
            running: p.cycles.running,
          })}
          tone={p.cycles.failed > 0 ? "warning" : "default"}
        />
        <Stat
          label={t("ai.agents.package.stat.job")}
          value={switchedOff ? t("ai.agents.package.job.off") : t("ai.agents.package.job.on")}
          hint={t("ai.agents.package.job.mode", { mode: settings.mode })}
          tone={switchedOff ? "warning" : "positive"}
        />
      </StatGrid>

      <Block title={t("ai.agents.package.last")}>
        {last === null ? (
          <Note>{t("ai.agents.package.never")}</Note>
        ) : (
          <div data-testid="agents-last-cycle">
            <Fact
              label={t("ai.agents.package.lastStarted")}
              value={`${bogotaDateTime(last.started_at)} · ${translateOr(`ai.layer.cycleStatus.${last.status}`, last.status)}`}
            />
            {Object.entries(last.counts).map(([k, v]) => (
              <Fact
                key={k}
                label={translateOr(`ai.agents.package.count.${k}`, k)}
                value={localInt(v)}
              />
            ))}
            {last.error ? (
              <Fact label={t("ai.agents.package.lastError")} value={last.error} />
            ) : null}
          </div>
        )}
      </Block>

      {Object.keys(p.by_pass).length > 0 ? (
        <Block title={t("ai.agents.package.byPass")}>
          <div className="flex flex-wrap gap-2" data-testid="agents-by-pass">
            {orderedCounts(p.by_pass, PASSES).map(([pass, n]) => (
              <StatusBadge key={pass} tone="neutral" dot={false}>
                {translateOr(`ai.agents.package.pass.${pass}`, pass)} · {localInt(n)}
              </StatusBadge>
            ))}
          </div>
        </Block>
      ) : null}

      <Block title={t("ai.agents.package.slices.title")} hint={t("ai.agents.package.slices.hint")}>
        <SlicesTable slices={p.slices} />
      </Block>

      <Block title={t("ai.agents.package.perDay.title")}>
        {p.per_day.length === 0 ? (
          <Note>{t("ai.agents.package.perDay.empty")}</Note>
        ) : (
          <Framed>
            <TableShell compact>
              <THead>
                <TH>{t("ai.agents.package.perDay.col.day")}</TH>
                <TH align="right">{t("ai.agents.package.perDay.col.states")}</TH>
                <TH align="right">{t("ai.agents.package.perDay.col.matches")}</TH>
                <TH align="right">{t("ai.agents.package.perDay.col.blocked")}</TH>
                <TH align="right">{t("ai.agents.package.perDay.col.flagged")}</TH>
              </THead>
              <tbody>
                {p.per_day.map((d) => (
                  <TRow key={d.day}>
                    <TD>{dayShort(d.day)}</TD>
                    <TD align="right">{localInt(d.states)}</TD>
                    <TD align="right">{localInt(d.matches)}</TD>
                    <TD align="right">{localInt(d.blocked)}</TD>
                    <TD align="right">{localInt(d.flagged)}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Framed>
        )}
      </Block>

      <Block title={t("ai.agents.package.rule.title")}>
        <div data-testid="agents-package-rule">
          <Fact label={t("ai.agents.package.rule.stateVersion")} value={p.rule.state_version} />
          <Fact label={t("ai.agents.package.rule.packageVersion")} value={p.rule.package_version} />
          <Fact
            label={t("ai.agents.package.rule.window")}
            value={t("ai.agents.package.rule.windowDays", { n: p.rule.window_days })}
          />
          <Fact label={t("ai.agents.package.rule.limit")} value={localInt(p.rule.limit)} />
          <Fact
            label={t("ai.agents.package.rule.maxSeconds")}
            value={t("ai.agents.package.rule.seconds", { n: p.rule.max_seconds })}
          />
        </div>
      </Block>
    </Panel>
  );
}

// ── the queue ────────────────────────────────────────────────────────────────

function CountTiles({
  counts,
  order,
  prefix,
}: {
  counts: QueueStats["tasks"];
  order: readonly string[];
  prefix: string;
}) {
  return (
    <StatGrid>
      {orderedCounts(counts, order, true).map(([word, n]) => (
        <Stat key={word} label={translateOr(`${prefix}.${word}`, word)} value={localInt(n)} />
      ))}
    </StatGrid>
  );
}

function QueuePanel({ q }: { q: QueueStats }) {
  return (
    <Panel
      title={t("ai.agents.queue.title")}
      subtitle={t("ai.agents.queue.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <StatGrid testId="agents-queue-stats">
        <Stat label={t("ai.agents.queue.stat.open")} value={localInt(q.open)} />
        <Stat label={t("ai.agents.queue.stat.reserved")} value={usd(q.reserved_usd)} />
      </StatGrid>
      <Block title={t("ai.agents.queue.tasks", { days: q.days })}>
        <CountTiles counts={q.tasks} order={TASK_STATES} prefix="ai.agents.queue.state" />
      </Block>
      <Block title={t("ai.agents.queue.runs", { days: q.days })}>
        <CountTiles counts={q.runs} order={RUN_STATUSES} prefix="ai.agents.queue.status" />
      </Block>
    </Panel>
  );
}

// ── the audit ────────────────────────────────────────────────────────────────

function AuditRow({ r }: { r: AuditRule }) {
  const verdict = auditVerdict(r);
  return (
    <TRow>
      <TD>
        <div className="font-medium">{translateOr(`ai.agents.audit.rule.${r.rule}`, r.rule)}</div>
        <div className="numeric text-caption text-muted-foreground">{r.rule}</div>
      </TD>
      <TD>
        <StatusBadge tone={AUDIT_TONE[verdict]} dot={false}>
          {t(`ai.agents.audit.verdict.${verdict}`)}
        </StatusBadge>
      </TD>
      <TD align="right">{localInt(r.days_audited)}</TD>
      <TD align="right">{localInt(r.checked)}</TD>
      <TD align="right" className={r.violations > 0 ? "text-negative" : ""}>
        {localInt(r.violations)}
      </TD>
      <TD className="text-xs">{r.days[0] ? dayShort(r.days[0].day) : DASH}</TD>
    </TRow>
  );
}

function AuditPanel({ rules }: { rules: AuditRule[] }) {
  const withViolations = rules.flatMap((r) =>
    r.days.filter((d) => d.n_violations > 0).map((d) => ({ rule: r.rule, day: d })),
  );
  return (
    <Panel
      title={t("ai.agents.audit.title")}
      subtitle={t("ai.agents.audit.subtitle")}
      bodyClassName="space-y-3 p-4"
    >
      {rules.length === 0 ? (
        <Note>{t("ai.agents.audit.empty")}</Note>
      ) : (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.agents.audit.col.rule")}</TH>
              <TH>{t("ai.agents.audit.col.verdict")}</TH>
              <TH align="right">{t("ai.agents.audit.col.days")}</TH>
              <TH align="right">{t("ai.agents.audit.col.checked")}</TH>
              <TH align="right">{t("ai.agents.audit.col.violations")}</TH>
              <TH>{t("ai.agents.audit.col.last")}</TH>
            </THead>
            <tbody>
              {rules.map((r) => (
                <AuditRow key={r.rule} r={r} />
              ))}
            </tbody>
          </TableShell>
        </Framed>
      )}
      {withViolations.length > 0 ? (
        <Block title={t("ai.agents.audit.examples")}>
          <ul className="space-y-1 text-xs" data-testid="agents-audit-examples">
            {withViolations.map(({ rule, day }) => (
              <li key={`${rule}:${day.day}`} className="break-words">
                <span className="numeric">
                  {rule} · {dayShort(day.day)} · {localInt(day.n_violations)}
                </span>{" "}
                <span className="text-muted-foreground">
                  {JSON.stringify(day.examples).slice(0, 300)}
                </span>
              </li>
            ))}
          </ul>
        </Block>
      ) : null}
    </Panel>
  );
}

// ── the tab ──────────────────────────────────────────────────────────────────

/** Everything the tab shows, given the figures: the part of the tab that needs no server. */
export function AgentsBody({ o }: { o: AgentsOverview }) {
  return (
    <div className="space-y-4" data-testid="agents-body">
      <AttentionLine o={o} />
      <RegistryPanel o={o} />
      <EnginesPanel families={o.families} decisions={o.decisions} />
      <PackagePanel p={o.package} settings={o.settings} />
      <QueuePanel q={o.queue} />
      <AuditPanel rules={o.audit} />
    </div>
  );
}

/** AGENTES: the tab of Operación. */
export function AgentsView() {
  const q = useLiveQuery(live.aiAgents());
  const o = q.data?.data ?? null;
  return (
    <div className="space-y-4" data-testid="operation-agents">
      <Note>{t("ai.agents.intro")}</Note>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {o ? <AgentsBody o={o} /> : q.isLoading ? <TableSkeleton rows={6} cols={5} /> : null}
    </div>
  );
}
