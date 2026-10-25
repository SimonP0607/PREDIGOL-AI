/**
 * The state of a match for the agents (Operación > Partido, plan IA, phase 1): what the job that writes the states stored about the match, without
 * any model - the measures of each slice of its package, never their content -, every state the match went through, and the tasks and attempts of
 * the agents on it (none until phase 2). Reading only.
 */
import type { ReactNode } from "react";
import { t, translateOr } from "@/lib/i18n";
import { DASH, localInt } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  AgentRunRow,
  AgentTaskRow,
  MatchState,
  MatchStateRow,
} from "@/lib/api/v1/types_ai_agents";
import { Fact, Note, SubTitle } from "./AiBits";
import { bogotaDateTime, usd } from "./aiModel";
import { durationMs, shortHash } from "./format";
import { slicesOver, totalTokens } from "./agentsModel";

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <SubTitle>{title}</SubTitle>
      {children}
    </div>
  );
}

function Framed({ children }: { children: ReactNode }) {
  return <div className="overflow-hidden rounded-md border border-border">{children}</div>;
}

/** A list of words as small badges, or "none". */
function Words({ words, tone }: { words: string[]; tone: "warning" | "info" }) {
  if (words.length === 0)
    return <span className="text-muted-foreground">{t("ai.agents.match.none")}</span>;
  return (
    <span className="flex flex-wrap justify-end gap-1">
      {words.map((w) => (
        <StatusBadge key={w} tone={tone} dot={false}>
          {w}
        </StatusBadge>
      ))}
    </span>
  );
}

const pass = (kind: string) => translateOr(`ai.agents.package.pass.${kind}`, kind);

/** The newest live state: its facts, and the measures of each slice against its cap. */
function CurrentState({ row }: { row: MatchStateRow }) {
  return (
    <Block title={t("ai.agents.match.current")}>
      <div data-testid="match-state-current">
        <Fact label={t("ai.agents.match.field.pass")} value={pass(row.pass_kind)} />
        <Fact label={t("ai.agents.match.field.knownAt")} value={bogotaDateTime(row.known_at)} />
        <Fact label={t("ai.agents.match.field.written")} value={bogotaDateTime(row.created_at)} />
        <Fact
          label={t("ai.agents.match.field.version")}
          value={`${row.state_version} · ${row.package_version ?? DASH}`}
        />
        <Fact label={t("ai.agents.match.field.hash")} value={shortHash(row.package_hash)} />
        <Fact label={t("ai.agents.match.field.code")} value={row.code ?? DASH} />
        <Fact
          label={t("ai.agents.match.field.packet")}
          value={row.packet_id === null ? DASH : localInt(row.packet_id)}
        />
        <Fact label={t("ai.agents.match.field.elapsed")} value={durationMs(row.elapsed_ms)} />
        <Fact
          label={t("ai.agents.match.field.blocking")}
          value={<Words words={row.blocking} tone="warning" />}
        />
        <Fact
          label={t("ai.agents.match.field.flags")}
          value={<Words words={row.flags} tone="warning" />}
        />
        <Fact label={t("ai.agents.match.field.agents")} value={localInt(row.agents)} />
        <Fact
          label={t("ai.agents.match.field.contradictions")}
          value={localInt(row.contradictions)}
        />
        <Fact label={t("ai.agents.match.field.candidates")} value={localInt(row.candidates)} />
        <Fact label={t("ai.agents.match.field.risks")} value={localInt(row.risks)} />
        <Fact
          label={t("ai.agents.match.field.final")}
          value={row.final ? t("ai.agents.match.final.yes") : t("ai.agents.match.final.no")}
        />
      </div>
      <Framed>
        <TableShell compact>
          <THead>
            <TH>{t("ai.agents.match.slice.col.slice")}</TH>
            <TH align="right">{t("ai.agents.match.slice.col.tokens")}</TH>
            <TH align="right">{t("ai.agents.match.slice.col.cap")}</TH>
            <TH>{t("ai.agents.match.slice.col.fits")}</TH>
            <TH>{t("ai.agents.match.slice.col.trimmed")}</TH>
            <TH>{t("ai.agents.match.slice.col.blocks")}</TH>
          </THead>
          <tbody>
            {row.slices.map((s) => (
              <TRow key={s.name}>
                <TD className="font-medium">{s.name}</TD>
                <TD align="right">{localInt(s.tokens)}</TD>
                <TD align="right">{localInt(s.cap)}</TD>
                <TD>
                  <StatusBadge tone={s.fits ? "positive" : "negative"} dot={false}>
                    {s.fits ? t("ai.agents.match.fits.yes") : t("ai.agents.match.fits.no")}
                  </StatusBadge>
                </TD>
                <TD className="text-xs">{s.trimmed.length ? s.trimmed.join(", ") : DASH}</TD>
                <TD className="text-xs">{s.blocks.length ? s.blocks.join(", ") : DASH}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Framed>
    </Block>
  );
}

function History({ rows, currentId }: { rows: MatchStateRow[]; currentId: number | null }) {
  return (
    <Block title={t("ai.agents.match.history.title")}>
      <Framed>
        <TableShell>
          <THead>
            <TH>{t("ai.agents.match.history.col.pass")}</TH>
            <TH>{t("ai.agents.match.history.col.known")}</TH>
            <TH>{t("ai.agents.match.history.col.written")}</TH>
            <TH>{t("ai.agents.match.history.col.hash")}</TH>
            <TH align="right">{t("ai.agents.match.history.col.tokens")}</TH>
            <TH>{t("ai.agents.match.history.col.problems")}</TH>
          </THead>
          <tbody>
            {rows.map((r) => {
              const over = slicesOver(r);
              return (
                <TRow key={r.id} selected={r.id === currentId}>
                  <TD>
                    {pass(r.pass_kind)}
                    {r.run_kind === "live" ? null : (
                      <span className="ml-1.5 text-caption text-muted-foreground">
                        {r.run_kind}
                      </span>
                    )}
                    {r.id === currentId ? (
                      <StatusBadge tone="brand" dot={false} className="ml-1.5">
                        {t("ai.agents.match.history.current")}
                      </StatusBadge>
                    ) : null}
                  </TD>
                  <TD className="whitespace-nowrap text-xs">{bogotaDateTime(r.known_at)}</TD>
                  <TD className="whitespace-nowrap text-xs">{bogotaDateTime(r.created_at)}</TD>
                  <TD className="numeric text-xs">{shortHash(r.package_hash)}</TD>
                  <TD align="right">{localInt(totalTokens(r))}</TD>
                  <TD className="text-xs">
                    {[
                      ...over.map((n) => t("ai.agents.match.history.over", { name: n })),
                      ...r.blocking,
                      ...r.flags,
                    ].join(" · ") || DASH}
                  </TD>
                </TRow>
              );
            })}
          </tbody>
        </TableShell>
      </Framed>
    </Block>
  );
}

function Tasks({ rows }: { rows: AgentTaskRow[] }) {
  return (
    <Block title={t("ai.agents.match.tasks.title")}>
      {rows.length === 0 ? (
        <Note>{t("ai.agents.match.tasks.empty")}</Note>
      ) : (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.agents.match.tasks.col.agent")}</TH>
              <TH>{t("ai.agents.match.tasks.col.task")}</TH>
              <TH>{t("ai.agents.match.tasks.col.pass")}</TH>
              <TH>{t("ai.agents.match.tasks.col.state")}</TH>
              <TH align="right">{t("ai.agents.match.tasks.col.priority")}</TH>
              <TH align="right">{t("ai.agents.match.tasks.col.cost")}</TH>
              <TH align="right">{t("ai.agents.match.tasks.col.attempts")}</TH>
              <TH>{t("ai.agents.match.tasks.col.reason")}</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={r.id}>
                  <TD>
                    <div className="font-medium">{r.agent}</div>
                    <div className="numeric text-caption text-muted-foreground">
                      {r.agent_version}
                    </div>
                  </TD>
                  <TD className="numeric text-xs">{r.task_kind}</TD>
                  <TD>{pass(r.pass_kind)}</TD>
                  <TD>{translateOr(`ai.agents.match.state.${r.state}`, r.state)}</TD>
                  <TD align="right">{localInt(r.priority)}</TD>
                  <TD align="right">{usd(r.est_cost_usd)}</TD>
                  <TD align="right">{localInt(r.attempts)}</TD>
                  <TD className="max-w-[20rem] break-words text-xs">{r.reason}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Framed>
      )}
    </Block>
  );
}

function Runs({ rows }: { rows: AgentRunRow[] }) {
  return (
    <Block title={t("ai.agents.match.runs.title")}>
      {rows.length === 0 ? (
        <Note>{t("ai.agents.match.runs.empty")}</Note>
      ) : (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.agents.match.runs.col.agent")}</TH>
              <TH>{t("ai.agents.match.runs.col.task")}</TH>
              <TH>{t("ai.agents.match.runs.col.status")}</TH>
              <TH>{t("ai.agents.match.runs.col.model")}</TH>
              <TH>{t("ai.agents.match.runs.col.verdict")}</TH>
              <TH>{t("ai.agents.match.runs.col.started")}</TH>
              <TH align="right">{t("ai.agents.match.runs.col.cost")}</TH>
              <TH>{t("ai.agents.match.runs.col.reason")}</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={r.id}>
                  <TD>
                    <div className="font-medium">{r.agent}</div>
                    <div className="numeric text-caption text-muted-foreground">
                      {r.agent_version}
                    </div>
                  </TD>
                  <TD className="numeric text-xs">{r.task_kind}</TD>
                  <TD>{translateOr(`ai.agents.match.status.${r.status}`, r.status)}</TD>
                  <TD className="numeric text-xs">{r.model ?? DASH}</TD>
                  <TD className="text-xs">{r.verdict ?? DASH}</TD>
                  <TD className="whitespace-nowrap text-xs">{bogotaDateTime(r.started_at)}</TD>
                  <TD align="right">{usd(r.cost_usd)}</TD>
                  <TD className="max-w-[20rem] break-words text-xs">{r.reason}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Framed>
      )}
    </Block>
  );
}

/** Everything the panel shows, given the file of the match: the part that needs no server. */
export function MatchStateBody({ s }: { s: MatchState }) {
  return (
    <div className="space-y-4" data-testid="match-state-body">
      {s.current === null ? (
        <Note>{t("ai.agents.match.empty")}</Note>
      ) : (
        <CurrentState row={s.current} />
      )}
      {s.history.length > 0 ? <History rows={s.history} currentId={s.current?.id ?? null} /> : null}
      <Tasks rows={s.tasks} />
      <Runs rows={s.runs} />
    </div>
  );
}

/** The state of the match the dossier is open on, for the agents. */
export function MatchStatePanel({ fixture }: { fixture: string }) {
  const q = useLiveQuery(live.aiMatchState(fixture));
  const s = q.data?.data ?? null;
  return (
    <Panel
      title={t("ai.agents.match.title")}
      subtitle={t("ai.agents.match.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <div data-testid="match-state">
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {s ? <MatchStateBody s={s} /> : q.isLoading ? <TableSkeleton rows={4} cols={4} /> : null}
      </div>
    </Panel>
  );
}
