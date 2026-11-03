/**
 * EXPEDIENTE DE LA SOMBRA (Operación > Partido, plan IA, phase 3, section 24): the file of one match as the Orchestrator saw it - how the match was
 * assigned, the candidates c1..cN with the server's numbers, the Match Agent's assessment in codes, the contradictions, and each engine's verdict
 * on each candidate side by side with today's reviewers (rules, language model, combined) -, the ids of the evidence the verdicts cite and the
 * calls it took with what they cost. Codes and numbers only: never a model's free text, never an address. Reading only.
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
import type {
  Cell,
  FileAssessment,
  FileCandidate,
  FileVerdicts,
  ShadowFile,
} from "@/lib/api/v1/types_ai_shadow";
import { Block, Choice, Fact, Framed, Note, Stat, StatGrid, Toolbar } from "./AiBits";
import { bogotaDateTime, engineLabel, usd } from "./aiModel";
import { marketText, pickText } from "./familiesText";
import { durationMs } from "./format";
import { Codes, Refs, ShadowOffNotice, VerdictBadge } from "./ShadowBits";
import { FILE_ENGINES, REVIEW_TONE, RUN_TONE, answered, disagrees, ruleLine } from "./shadowModel";

const cell = (v: string | null) => (v === null || v === "" ? DASH : v);

function candidateName(c: FileCandidate): string {
  return `${marketText(c.market)} · ${pickText(c.market, c.selection, c.line)}`;
}

function CandidatesTable({ rows }: { rows: FileCandidate[] }) {
  return (
    <Framed>
      <TableShell>
        <THead>
          <TH>{t("ai.shadowFile.col.key")}</TH>
          <TH>{t("ai.shadowFile.col.pick")}</TH>
          <TH align="right">{t("ai.shadowFile.col.odds")}</TH>
          <TH align="right">{t("ai.shadowFile.col.pModel")}</TH>
          <TH align="right">{t("ai.shadowFile.col.pMarket")}</TH>
          <TH align="right">{t("ai.shadowFile.col.edge")}</TH>
          <TH align="right">{t("ai.shadowFile.col.ev")}</TH>
          <TH>{t("ai.shadowFile.col.leftOut")}</TH>
        </THead>
        <tbody>
          {rows.map((c, i) => (
            <TRow key={c.key ?? `x${i}`} data-testid="file-candidate">
              <TD className="numeric text-xs">{c.key ?? DASH}</TD>
              <TD className="min-w-[10rem]">
                {candidateName(c)}
                {c.family ? (
                  <div className="numeric text-caption text-muted-foreground">{c.family}</div>
                ) : null}
              </TD>
              <TD align="right" className="numeric">
                {cell(c.odds)}
              </TD>
              <TD align="right" className="numeric">
                {cell(c.p_model)}
              </TD>
              <TD align="right" className="numeric">
                {cell(c.p_market)}
              </TD>
              <TD align="right" className="numeric">
                {cell(c.edge)}
              </TD>
              <TD align="right" className="numeric">
                {cell(c.ev)}
              </TD>
              <TD>
                {c.left_out ? (
                  <StatusBadge tone="warning" dot={false}>
                    {translateOr(`ai.arms.reason.${c.left_out}`, c.left_out)}
                  </StatusBadge>
                ) : (
                  DASH
                )}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Framed>
  );
}

function AssessmentCard({ a }: { a: FileAssessment }) {
  return (
    <div
      className="space-y-2 rounded-md border border-border px-3 py-2"
      data-testid="file-assessment"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium">{a.label}</span>
        <StatusBadge tone={RUN_TONE[a.status] ?? "neutral"} dot={false}>
          {translateOr(`ai.agentRuns.status.${a.status}`, a.status)}
        </StatusBadge>
        {a.model ? (
          <span className="numeric text-caption text-muted-foreground">{a.model}</span>
        ) : null}
        {a.quality ? (
          <span className="text-caption text-muted-foreground">
            {t("ai.shadowFile.quality", {
              q: translateOr(`ai.shadowFile.level.${a.quality}`, a.quality),
            })}
          </span>
        ) : null}
      </div>
      {a.signals.length > 0 ? (
        <ul className="space-y-0.5 text-xs" data-testid="file-signals">
          {a.signals.map((s, i) => (
            <li key={`${s.code}-${i}`} className="flex flex-wrap items-center gap-2">
              <span className="numeric">{s.code}</span>
              <span className="text-muted-foreground">
                {translateOr(`ai.shadowFile.direction.${s.direction}`, s.direction)} ·{" "}
                {translateOr(`ai.shadowFile.level.${s.strength}`, s.strength)}
              </span>
              <Refs refs={s.refs} />
            </li>
          ))}
        </ul>
      ) : null}
      {a.candidates.length > 0 ? (
        <ul className="space-y-1 text-xs" data-testid="file-stances">
          {a.candidates.map((c) => (
            <li key={c.candidate} className="flex flex-wrap items-center gap-2">
              <span className="numeric">{c.candidate}</span>
              <StatusBadge tone="neutral" dot={false}>
                {translateOr(`ai.shadowFile.stance.${c.stance}`, c.stance)}
              </StatusBadge>
              <Codes codes={c.drivers} />
              <Codes codes={c.risks} />
              <Refs refs={c.refs} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** One engine's cell for one candidate: the verdict, how sure, what drove it and the codes behind it; a dash when it has none. */
function VerdictCell({ c, vs }: { c: Cell | undefined; vs: string | null }) {
  if (!c || c.decision === null) {
    return (
      <div className="text-xs text-muted-foreground">
        {DASH}
        {c?.reason ? <div className="numeric text-caption">{c.reason}</div> : null}
      </div>
    );
  }
  const differs = disagrees(c.decision, vs);
  return (
    <div
      className="space-y-1"
      data-testid={`verdict-${c.engine}`}
      data-differs={differs ? "true" : "false"}
    >
      <div className="flex flex-wrap items-center gap-1">
        <VerdictBadge decision={c.decision} />
        {differs ? (
          <StatusBadge tone="warning" dot={false}>
            {t("ai.shadowFile.differs")}
          </StatusBadge>
        ) : null}
      </div>
      <div className="numeric text-caption text-muted-foreground">
        {[c.confidence, c.level].filter((x) => x !== null && x !== "").join(" · ") || DASH}
      </div>
      {c.status && c.status !== "ok" ? (
        <StatusBadge tone={REVIEW_TONE[c.status] ?? "neutral"} dot={false}>
          {translateOr(`ai.arms.status.${c.status}`, c.status)}
        </StatusBadge>
      ) : null}
      <Codes codes={c.drivers} />
      <Codes codes={c.risks} />
      {c.contradictions.length > 0 ? <Codes codes={c.contradictions} /> : null}
      {c.escalation ? (
        <div className="numeric text-caption text-muted-foreground">
          {ruleLine(c.escalation.rule, [])}
          {c.escalation.replaced ? ` · ${t("ai.shadowFile.replaced")}` : ""}
          {c.escalation.skipped ? ` · ${c.escalation.skipped}` : ""}
        </div>
      ) : null}
      <Refs refs={c.refs} />
      {c.cost_usd !== null ? (
        <div className="numeric text-caption text-muted-foreground">{usd(c.cost_usd)}</div>
      ) : null}
    </div>
  );
}

function VerdictGrid({ rows, names }: { rows: FileVerdicts[]; names: Map<string, string> }) {
  const all = rows.flatMap((r) => r.cells);
  return (
    <Framed>
      <TableShell>
        <THead>
          <TH>{t("ai.shadowFile.col.candidate")}</TH>
          {FILE_ENGINES.map((e) => (
            <TH key={e}>
              <div>{engineLabel(e)}</div>
              <div className="numeric text-caption font-normal text-muted-foreground">
                {t("ai.shadowFile.answered", {
                  n: answered(all.filter((c) => c.engine === e)),
                })}
              </div>
            </TH>
          ))}
        </THead>
        <tbody>
          {rows.map((r) => {
            const by = new Map(r.cells.map((c) => [c.engine, c] as const));
            // The reference for "differs" is the combined reviewer of today: what the pick would have got.
            const ref = by.get("combined")?.decision ?? null;
            return (
              <TRow key={r.candidate} data-testid={`verdict-row-${r.candidate}`}>
                <TD className="min-w-[9rem]">
                  <div className="numeric text-xs font-medium">{r.candidate}</div>
                  <div className="text-caption text-muted-foreground">
                    {names.get(r.candidate) ?? DASH}
                  </div>
                </TD>
                {FILE_ENGINES.map((e) => (
                  <TD key={e} className="min-w-[8rem] align-top">
                    <VerdictCell
                      c={by.get(e)}
                      vs={e === "rules" || e === "llm" || e === "combined" ? null : ref}
                    />
                  </TD>
                ))}
              </TRow>
            );
          })}
        </tbody>
      </TableShell>
    </Framed>
  );
}

/** Everything the panel shows, given the figures: the part that needs no server. */
export function ShadowFileBody({
  d,
  pass,
  onPass,
}: {
  d: ShadowFile;
  pass?: string;
  onPass?: (pass: string) => void;
}) {
  const names = new Map(
    d.candidates.flatMap((c) => (c.key ? [[c.key, candidateName(c)] as const] : [])),
  );
  const kinds = [...new Set(d.passes.map((p) => p.pass_kind))];
  const empty = d.passes.length === 0 && d.assignment === null;
  return (
    <div className="space-y-4" data-testid="shadow-file-body">
      {empty || !d.switches.orchestrate ? (
        <ShadowOffNotice switches={d.switches} testId="file-shadow-off" />
      ) : null}
      {empty ? (
        <Note>{t("ai.shadowFile.none")}</Note>
      ) : (
        <>
          {onPass && kinds.length > 1 ? (
            <Toolbar>
              <Choice label={t("ai.shadowFile.passPick")} value={pass ?? ""} onChange={onPass}>
                <option value="">{t("ai.shadowFile.newest")}</option>
                {kinds.map((k) => (
                  <option key={k} value={k}>
                    {translateOr(`ai.arms.pass.${k}`, k)}
                  </option>
                ))}
              </Choice>
            </Toolbar>
          ) : null}
          <Block title={t("ai.shadowFile.assignment.title")}>
            {d.assignment ? (
              <div data-testid="file-assignment">
                <Fact
                  label={t("ai.shadowFile.assignment.sampled")}
                  value={t(d.assignment.sampled ? "ai.shadowFile.yes" : "ai.shadowFile.no")}
                />
                <Fact
                  label={t("ai.shadowFile.assignment.solo")}
                  value={t(d.assignment.council_solo ? "ai.shadowFile.yes" : "ai.shadowFile.no")}
                />
                <Fact label={t("ai.shadowFile.assignment.share")} value={d.assignment.share} />
                <Fact
                  label={t("ai.shadowFile.assignment.bucket")}
                  value={localInt(d.assignment.bucket)}
                />
                <Fact
                  label={t("ai.shadowFile.assignment.engines")}
                  value={d.assignment.engines.length > 0 ? d.assignment.engines.join(" · ") : DASH}
                />
                <Fact
                  label={t("ai.shadowFile.assignment.at")}
                  value={bogotaDateTime(d.assignment.assigned_at)}
                />
              </div>
            ) : (
              <Note>{t("ai.shadowFile.assignment.none")}</Note>
            )}
          </Block>
          {d.selected ? (
            <Block title={t("ai.shadowFile.pass.title")}>
              <div data-testid="file-pass">
                <Fact
                  label={t("ai.shadowFile.pass.kind")}
                  value={translateOr(`ai.arms.pass.${d.selected.pass_kind}`, d.selected.pass_kind)}
                />
                <Fact
                  label={t("ai.shadowFile.pass.knownAt")}
                  value={bogotaDateTime(d.selected.known_at)}
                />
                <Fact
                  label={t("ai.shadowFile.pass.status")}
                  value={
                    d.selected.reason
                      ? `${translateOr(`ai.shadowFile.pass.${d.selected.status}`, d.selected.status)} · ${d.selected.reason}`
                      : translateOr(`ai.shadowFile.pass.${d.selected.status}`, d.selected.status)
                  }
                />
                <Fact
                  label={t("ai.shadowFile.pass.elapsed")}
                  value={durationMs(d.selected.elapsed_ms)}
                />
              </div>
            </Block>
          ) : null}
          <Block
            title={t("ai.shadowFile.candidates.title")}
            hint={t("ai.shadowFile.candidates.hint")}
          >
            {d.candidates.length > 0 ? (
              <CandidatesTable rows={d.candidates} />
            ) : (
              <Note>{DASH}</Note>
            )}
          </Block>
          <Block
            title={t("ai.shadowFile.assessment.title")}
            hint={t("ai.shadowFile.assessment.hint")}
          >
            {d.assessments.length > 0 ? (
              <div className="space-y-2">
                {d.assessments.map((a, i) => (
                  <AssessmentCard key={`${a.mode}-${i}`} a={a} />
                ))}
              </div>
            ) : (
              <Note>{DASH}</Note>
            )}
          </Block>
          <Block title={t("ai.shadowFile.contra.title")}>
            {d.contradictions.length > 0 ? (
              <ul className="space-y-1 text-xs" data-testid="file-contradictions">
                {d.contradictions.map((c, i) => (
                  <li
                    key={`${c.code}-${c.subject}-${i}`}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <span className="numeric font-medium">{c.code}</span>
                    <span className="text-muted-foreground">
                      {translateOr(`ai.contra.code.${c.code}`, c.code)}
                    </span>
                    <StatusBadge tone={c.confirmed ? "warning" : "neutral"} dot={false}>
                      {t(c.confirmed ? "ai.contra.confirmed" : "ai.contra.unconfirmed")}
                    </StatusBadge>
                    <span className="numeric text-caption">{c.candidates.join(" ")}</span>
                    <Refs refs={c.refs} />
                  </li>
                ))}
              </ul>
            ) : (
              <Note>{t("ai.shadowFile.contra.none")}</Note>
            )}
          </Block>
          <Block title={t("ai.shadowFile.verdicts.title")} hint={t("ai.shadowFile.verdicts.hint")}>
            {d.verdicts.length > 0 ? (
              <VerdictGrid rows={d.verdicts} names={names} />
            ) : (
              <Note>{DASH}</Note>
            )}
          </Block>
          {d.arms.length > 0 ? (
            <Block title={t("ai.shadowFile.arms.title")}>
              <div className="space-y-1" data-testid="file-arms">
                {d.arms.map((a) => (
                  <Fact
                    key={a.engine}
                    label={engineLabel(a.engine)}
                    value={
                      [
                        a.status ? translateOr(`ai.arms.status.${a.status}`, a.status) : null,
                        a.reason,
                        ...a.paused,
                      ]
                        .filter((x): x is string => x !== null && x !== "")
                        .join(" · ") || DASH
                    }
                  />
                ))}
              </div>
            </Block>
          ) : null}
          <Block title={t("ai.shadowFile.evidence.title")} hint={t("ai.shadowFile.evidence.hint")}>
            {d.evidence_ids.length > 0 ? (
              <span
                className="numeric flex flex-wrap gap-x-2 text-xs text-muted-foreground"
                data-testid="file-evidence"
              >
                {d.evidence_ids.map((id) => (
                  <span key={id}>E:{id}</span>
                ))}
              </span>
            ) : (
              <Note>{DASH}</Note>
            )}
          </Block>
          <Block title={t("ai.shadowFile.calls.title")}>
            <StatGrid testId="file-calls-totals">
              <Stat label={t("ai.shadowFile.calls.n")} value={localInt(d.calls.length)} />
              <Stat label={t("ai.shadowFile.calls.cost")} value={usd(d.cost_usd)} />
            </StatGrid>
            {d.calls.length > 0 ? (
              <Framed>
                <TableShell>
                  <THead>
                    <TH>{t("ai.agentRuns.col.agent")}</TH>
                    <TH>{t("ai.agentRuns.col.task")}</TH>
                    <TH>{t("ai.agentRuns.col.model")}</TH>
                    <TH>{t("ai.agentRuns.col.status")}</TH>
                    <TH align="right">{t("ai.agentRuns.col.cost")}</TH>
                    <TH align="right">{t("ai.agentRuns.col.latency")}</TH>
                    <TH>{t("ai.agentRuns.col.rule")}</TH>
                  </THead>
                  <tbody>
                    {d.calls.map((r) => (
                      <TRow key={r.id} data-testid="file-call">
                        <TD>{translateOr(`ai.agentRuns.agent.${r.agent}`, r.agent)}</TD>
                        <TD>{translateOr(`ai.agentRuns.task.${r.task_kind}`, r.task_kind)}</TD>
                        <TD className="numeric text-xs">{r.model ?? DASH}</TD>
                        <TD>
                          <StatusBadge tone={RUN_TONE[r.status] ?? "neutral"} dot={false}>
                            {translateOr(`ai.agentRuns.status.${r.status}`, r.status)}
                          </StatusBadge>
                        </TD>
                        <TD align="right" className="numeric">
                          {usd(r.cost_usd)}
                        </TD>
                        <TD align="right" className="numeric text-xs">
                          {durationMs(r.latency_ms)}
                        </TD>
                        <TD className="numeric text-xs">
                          {ruleLine(r.escalation, r.fired) ?? DASH}
                        </TD>
                      </TRow>
                    ))}
                  </tbody>
                </TableShell>
              </Framed>
            ) : null}
          </Block>
        </>
      )}
    </div>
  );
}

/** EXPEDIENTE DE LA SOMBRA: the panel of Operación > Partido, under the state of the match. */
export function ShadowFilePanel({ fixture }: { fixture: string }) {
  const [pass, setPass] = useState("");
  const q = useLiveQuery(live.aiMatchShadow(fixture, pass || undefined));
  const d = q.data?.data ?? null;
  return (
    <Panel
      title={t("ai.shadowFile.title")}
      subtitle={t("ai.shadowFile.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <div data-testid="shadow-file">
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {d ? (
          <ShadowFileBody d={d} pass={pass} onPass={setPass} />
        ) : q.isLoading ? (
          <TableSkeleton rows={6} cols={6} />
        ) : null}
      </div>
    </Panel>
  );
}
