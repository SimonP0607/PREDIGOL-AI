/**
 * EJECUCIONES DE LOS AGENTES (Operación > Agentes, plan IA, phase 3, sections 23 and 24): the recent calls of the Orchestrator's agents
 * (`ai.agent_runs`) - which agent, for which task, on which model, how it ended, the tokens, what it cost, how long it took and which rule of the
 * router sent it to Opus -, with filters, and the day's Opus calls against the cap. Reading only; the cap is the server's, never recomputed here.
 */
import { useState } from "react";
import { t, translateOr } from "@/lib/i18n";
import { DASH, localInt } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { AgentRunItem, AgentRuns } from "@/lib/api/v1/types_ai_shadow";
import { Block, Choice, DayInput, Framed, Note, Stat, StatGrid, Toolbar } from "./AiBits";
import { AI_TZ, bogotaTime, usd } from "./aiModel";
import { durationMs } from "./format";
import { ShadowOffNotice } from "./ShadowBits";
import {
  AGENTS,
  OPUS_TONE,
  RUN_STATUS_FILTER,
  RUN_TONE,
  TASK_KINDS,
  opusLevel,
  ruleLine,
  sortedCounts,
} from "./shadowModel";
import { todayKey } from "@/lib/time";

const tokens = (n: number | null) => (n === null ? DASH : localInt(n));

function RunRow({ r }: { r: AgentRunItem }) {
  const rule = ruleLine(r.escalation, r.fired);
  return (
    <TRow data-testid="agent-run">
      <TD className="numeric whitespace-nowrap text-xs">{bogotaTime(r.started_at)}</TD>
      <TD className="min-w-[8rem]">
        <div className="font-medium">{translateOr(`ai.agentRuns.agent.${r.agent}`, r.agent)}</div>
        <div className="numeric text-caption text-muted-foreground">{r.agent_version}</div>
      </TD>
      <TD>{translateOr(`ai.agentRuns.task.${r.task_kind}`, r.task_kind)}</TD>
      <TD className="min-w-[8rem]">
        {r.match ?? (r.fixture_id === null ? DASH : `#${r.fixture_id}`)}
        <div className="text-caption text-muted-foreground">
          {translateOr(`ai.arms.pass.${r.pass_kind}`, r.pass_kind)}
        </div>
      </TD>
      <TD className="numeric text-xs">
        {r.model ?? DASH}
        {r.effort ? <div className="text-caption text-muted-foreground">{r.effort}</div> : null}
      </TD>
      <TD>
        <StatusBadge tone={RUN_TONE[r.status] ?? "neutral"} dot={false}>
          {translateOr(`ai.agentRuns.status.${r.status}`, r.status)}
        </StatusBadge>
        {r.error ? (
          <div className="numeric mt-0.5 text-caption text-negative">{r.error}</div>
        ) : null}
      </TD>
      <TD align="right" className="numeric text-xs">
        <div>{tokens(r.input_tokens)}</div>
        <div className="text-caption text-muted-foreground">
          {tokens(r.output_tokens)}
          {r.cached_tokens ? ` · ${tokens(r.cached_tokens)}` : ""}
        </div>
      </TD>
      <TD align="right" className="numeric">
        {usd(r.cost_usd)}
      </TD>
      <TD align="right" className="numeric text-xs">
        {durationMs(r.latency_ms)}
      </TD>
      <TD className="numeric text-xs">{rule ?? DASH}</TD>
    </TRow>
  );
}

/** The day's Opus calls against the cap of 3: the figure the server counts, never one made up here. */
function OpusCard({ o }: { o: AgentRuns["opus"] }) {
  const level = opusLevel(o);
  return (
    <Block title={t("ai.agentRuns.opus.title", { day: o.day })} hint={t("ai.agentRuns.opus.hint")}>
      <StatGrid testId="agent-runs-opus">
        <Stat
          label={t("ai.agentRuns.opus.calls")}
          value={`${localInt(o.calls)} / ${localInt(o.cap)}`}
          tone={level === "spent" ? "negative" : level === "last" ? "warning" : "default"}
          hint={
            <StatusBadge tone={OPUS_TONE[level]} dot={false}>
              {t(`ai.agentRuns.opus.level.${level}`)}
            </StatusBadge>
          }
        />
        <Stat label={t("ai.agentRuns.opus.remaining")} value={localInt(o.remaining)} />
        <Stat label={t("ai.agentRuns.opus.skipped")} value={localInt(o.skipped)} />
        <Stat label={t("ai.agentRuns.opus.cost")} value={usd(o.cost_usd)} />
      </StatGrid>
    </Block>
  );
}

/** Everything the panel shows, given the figures: the part that needs no server. */
export function AgentRunsBody({ d }: { d: AgentRuns }) {
  const statuses = sortedCounts(d.by_status);
  return (
    <div className="space-y-4" data-testid="agent-runs-body">
      {!d.switches.orchestrate || d.total === 0 ? <ShadowOffNotice switches={d.switches} /> : null}
      <OpusCard o={d.opus} />
      <StatGrid testId="agent-runs-totals">
        <Stat label={t("ai.agentRuns.total")} value={localInt(d.total)} />
        <Stat label={t("ai.agentRuns.cost")} value={usd(d.cost_usd)} />
        {statuses.map(([k, n]) => (
          <Stat key={k} label={translateOr(`ai.agentRuns.status.${k}`, k)} value={localInt(n)} />
        ))}
      </StatGrid>
      {d.runs.length === 0 ? (
        <Note>{t("ai.agentRuns.empty")}</Note>
      ) : (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.agentRuns.col.time")}</TH>
              <TH>{t("ai.agentRuns.col.agent")}</TH>
              <TH>{t("ai.agentRuns.col.task")}</TH>
              <TH>{t("ai.agentRuns.col.match")}</TH>
              <TH>{t("ai.agentRuns.col.model")}</TH>
              <TH>{t("ai.agentRuns.col.status")}</TH>
              <TH align="right" title={t("ai.agentRuns.col.tokensHint")}>
                {t("ai.agentRuns.col.tokens")}
              </TH>
              <TH align="right">{t("ai.agentRuns.col.cost")}</TH>
              <TH align="right">{t("ai.agentRuns.col.latency")}</TH>
              <TH title={t("ai.agentRuns.col.ruleHint")}>{t("ai.agentRuns.col.rule")}</TH>
            </THead>
            <tbody>
              {d.runs.map((r) => (
                <RunRow key={r.id} r={r} />
              ))}
            </tbody>
          </TableShell>
        </Framed>
      )}
    </div>
  );
}

/** EJECUCIONES: the panel under the agents' overview (Operación > Agentes). */
export function AgentRunsPanel() {
  const today = todayKey(AI_TZ);
  const [day, setDay] = useState(today);
  const [agent, setAgent] = useState("");
  const [task, setTask] = useState("");
  const [status, setStatus] = useState("");
  const q = useLiveQuery(
    live.aiAgentRuns({
      day,
      agent: agent || undefined,
      task_kind: task || undefined,
      status: status || undefined,
      limit: 100,
    }),
  );
  const d = q.data?.data ?? null;
  return (
    <Panel
      title={t("ai.agentRuns.title")}
      subtitle={t("ai.agentRuns.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <div className="space-y-4" data-testid="agent-runs">
        <Toolbar>
          <DayInput
            value={day}
            onChange={setDay}
            label={t("ai.agentRuns.filter.day")}
            max={today}
          />
          <Choice label={t("ai.agentRuns.filter.agent")} value={agent} onChange={setAgent}>
            <option value="">{t("ai.agentRuns.filter.all")}</option>
            {AGENTS.map((a) => (
              <option key={a} value={a}>
                {translateOr(`ai.agentRuns.agent.${a}`, a)}
              </option>
            ))}
          </Choice>
          <Choice label={t("ai.agentRuns.filter.task")} value={task} onChange={setTask}>
            <option value="">{t("ai.agentRuns.filter.all")}</option>
            {TASK_KINDS.map((k) => (
              <option key={k} value={k}>
                {translateOr(`ai.agentRuns.task.${k}`, k)}
              </option>
            ))}
          </Choice>
          <Choice label={t("ai.agentRuns.filter.status")} value={status} onChange={setStatus}>
            <option value="">{t("ai.agentRuns.filter.all")}</option>
            {RUN_STATUS_FILTER.map((s) => (
              <option key={s} value={s}>
                {translateOr(`ai.agentRuns.status.${s}`, s)}
              </option>
            ))}
          </Choice>
        </Toolbar>
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {d ? <AgentRunsBody d={d} /> : q.isLoading ? <TableSkeleton rows={6} cols={8} /> : null}
      </div>
    </Panel>
  );
}
