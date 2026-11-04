/**
 * SOMBRA CON BRAZOS (Aprendizaje > Sombra, plan IA phase 3, sections 22 and 23): the seven arms of the experiment side by side over the same
 * selections - how many reviews and selections each wrote, the share approved, downgraded, rejected and abstained, the invalid outputs, what it cost
 * the LAB (from the ledger), the p95 latency of its calls and why it paused -, how the matches were assigned, and the plan's thresholds (30 days,
 * 300 selections reviewed by both engines) as COUNTS. It never says an arm passed: reaching a threshold only says there is enough to look
 * ("nunca forzar PASS"). Reading only: the figures come from the server.
 */
import { t, translateOr } from "@/lib/i18n";
import { DASH, localInt, localPct } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { ArmRow, Assignments, Enough, ShadowArms } from "@/lib/api/v1/types_ai_shadow";
import { Block, Fact, Framed, Note, Stat, StatGrid } from "./AiBits";
import { bogotaDateTime, usd } from "./aiModel";
import { durationMs } from "./format";
import { ShadowOffNotice } from "./ShadowBits";
import {
  ARMS,
  armLabel,
  decisionShares,
  enoughState,
  invalidRate,
  invalidTone,
  progress,
  reasonLabel,
  sortedCounts,
  sumCounts,
} from "./shadowModel";

const pct = (x: number | null) => (x === null ? DASH : localPct(x, 0));

/** "12 (40 %)": a count and its share of the reviews of the arm. */
function Counted({ n, total }: { n: number | undefined; total: number }) {
  if (n === undefined) return <span className="text-muted-foreground">{DASH}</span>;
  return (
    <span className="numeric">
      {localInt(n)}{" "}
      <span className="text-muted-foreground">({pct(total > 0 ? n / total : null)})</span>
    </span>
  );
}

function ArmRowView({ a }: { a: ArmRow }) {
  // The comparable basis: the selections the shadow also reviewed. For an arm of the shadow it is all of its reviews.
  const d = a.decisions_on_sample;
  const total = a.on_sample;
  const shares = decisionShares(d, total);
  const rate = invalidRate(a);
  const lab = a.kind === "shadow";
  return (
    <TRow data-testid={`arm-${a.arm}`}>
      <TD className="min-w-[11rem]">
        <div className="font-medium">{armLabel(a.arm)}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
          <StatusBadge tone={lab ? "brand" : "neutral"} dot={false}>
            {t(`ai.arms.kind.${a.kind}`)}
          </StatusBadge>
          {a.engine ? (
            <span className="numeric text-caption text-muted-foreground">{a.engine}</span>
          ) : null}
        </div>
      </TD>
      <TD align="right">{localInt(a.reviews)}</TD>
      <TD align="right">
        <div>{localInt(a.on_sample)}</div>
        <div className="text-caption text-muted-foreground">
          {t("ai.arms.col.selectionsN", { n: a.selections_on_sample })}
        </div>
      </TD>
      {d && shares ? (
        <>
          <TD align="right">
            <Counted n={d.approved} total={total} />
          </TD>
          <TD align="right">
            <Counted n={d.downgraded} total={total} />
          </TD>
          <TD align="right">
            <Counted n={d.rejected} total={total} />
          </TD>
          <TD align="right">
            <Counted n={d.abstained} total={total} />
          </TD>
        </>
      ) : (
        <TD colSpan={4} className="text-center text-xs text-muted-foreground">
          {t("ai.arms.noDecisions")}
        </TD>
      )}
      <TD align="right">
        {rate === null ? (
          DASH
        ) : (
          <StatusBadge tone={invalidTone(rate)} dot={false}>
            {pct(rate)} · {localInt(a.invalid)}
          </StatusBadge>
        )}
      </TD>
      <TD align="right">
        {a.cost_usd === null || !lab ? DASH : usd(a.cost_usd)}
        {lab && a.ledger_usd !== null ? (
          <div className="text-caption text-muted-foreground">
            {t("ai.arms.col.ledger", { v: usd(a.ledger_usd), n: a.calls })}
          </div>
        ) : null}
      </TD>
      <TD align="right">
        {lab && a.latency_p95_ms !== null ? durationMs(a.latency_p95_ms) : DASH}
      </TD>
    </TRow>
  );
}

/** Per arm, what is behind the numbers: the status of its reviews, why it was paused, why it answered nothing, what the evaluation has settled. */
function ArmDetail({ a }: { a: ArmRow }) {
  const paused = sortedCounts(a.paused);
  const silent = sortedCounts(a.not_answered);
  const statuses = sortedCounts(a.statuses);
  if (paused.length === 0 && silent.length === 0 && !a.settled && a.kind !== "shadow") return null;
  return (
    <div
      className="space-y-1 rounded-md border border-border px-3 py-2"
      data-testid={`arm-detail-${a.arm}`}
    >
      <div className="text-xs font-medium">{armLabel(a.arm)}</div>
      {statuses.length > 0 ? (
        <Fact
          label={t("ai.arms.detail.statuses")}
          value={statuses
            .map(([k, n]) => `${translateOr(`ai.arms.status.${k}`, k)} ${localInt(n)}`)
            .join(" · ")}
        />
      ) : null}
      <Fact
        label={t("ai.arms.detail.paused", { n: sumCounts(a.paused) })}
        value={
          paused.length > 0
            ? paused.map(([k, n]) => `${reasonLabel(k)} ${localInt(n)}`).join(" · ")
            : t("ai.arms.detail.none")
        }
      />
      <Fact
        label={t("ai.arms.detail.silent", { n: sumCounts(a.not_answered) })}
        value={
          silent.length > 0
            ? silent.map(([k, n]) => `${reasonLabel(k)} ${localInt(n)}`).join(" · ")
            : t("ai.arms.detail.none")
        }
      />
      {a.settled ? (
        <Fact
          label={t("ai.arms.detail.settled", { date: bogotaDateTime(a.settled.report_at) })}
          value={t("ai.arms.detail.settledValue", {
            n: a.settled.selections,
            kept: a.settled.kept,
            rejected: a.settled.rejected,
            clvKept: a.settled.clv_kept === null ? DASH : localPct(a.settled.clv_kept, 2, true),
            clvRejected:
              a.settled.clv_rejected === null ? DASH : localPct(a.settled.clv_rejected, 2, true),
          })}
        />
      ) : (
        <Fact label={t("ai.arms.detail.settledNone")} value={DASH} />
      )}
    </div>
  );
}

function EnoughPanel({ e }: { e: Enough }) {
  const state = enoughState(e);
  return (
    <Block title={t("ai.arms.enough.title")} hint={t("ai.arms.enough.hint")}>
      <StatGrid testId="arms-enough">
        <Stat
          label={t("ai.arms.enough.days")}
          value={`${localInt(e.days_running)} / ${localInt(e.days_need)}`}
          hint={t("ai.arms.enough.daysHint", {
            n: e.days,
            bar: progress(e.days_running, e.days_need),
          })}
          tone={e.days_reached ? "positive" : "default"}
        />
        <Stat
          label={t("ai.arms.enough.selections")}
          value={`${localInt(e.selections)} / ${localInt(e.selections_need)}`}
          hint={t("ai.arms.enough.selectionsHint", {
            bar: progress(e.selections, e.selections_need),
          })}
          tone={e.selections_reached ? "positive" : "default"}
        />
      </StatGrid>
      <div className="text-xs text-muted-foreground" data-testid="arms-enough-state">
        {t(`ai.arms.enough.state.${state}`)}
      </div>
    </Block>
  );
}

function AssignmentPanel({ a, asked }: { a: Assignments; asked: string }) {
  return (
    <Block
      title={t("ai.arms.assign.title")}
      hint={t("ai.arms.assign.hint", { salt: a.experiment })}
    >
      <StatGrid testId="arms-assign">
        <Stat label={t("ai.arms.assign.assigned")} value={localInt(a.assigned)} />
        <Stat label={t("ai.arms.assign.sampled")} value={localInt(a.sampled)} />
        <Stat label={t("ai.arms.assign.unsampled")} value={localInt(a.unsampled)} />
        <Stat
          label={t("ai.arms.assign.solo")}
          value={localInt(a.council_solo)}
          hint={t("ai.arms.assign.soloHint", {
            share: a.sampled > 0 ? pct(a.council_solo / a.sampled) : DASH,
          })}
        />
        <Stat
          label={t("ai.arms.assign.observed")}
          value={a.sampled_share === null ? DASH : pct(a.sampled_share)}
          hint={t("ai.arms.assign.asked", { share: asked })}
        />
      </StatGrid>
      {a.by_share.length > 0 ? (
        <Framed>
          <TableShell>
            <THead>
              <TH>{t("ai.arms.assign.col.share")}</TH>
              <TH align="right">{t("ai.arms.assign.col.assigned")}</TH>
              <TH align="right">{t("ai.arms.assign.col.sampled")}</TH>
              <TH align="right">{t("ai.arms.assign.col.solo")}</TH>
            </THead>
            <tbody>
              {a.by_share.map((s) => (
                <TRow key={s.share}>
                  <TD className="numeric">{s.share}</TD>
                  <TD align="right">{localInt(s.assigned)}</TD>
                  <TD align="right">{localInt(s.sampled)}</TD>
                  <TD align="right">{localInt(s.council_solo)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Framed>
      ) : null}
    </Block>
  );
}

/** Everything the panel shows, given the figures: the part that needs no server. */
export function ShadowArmsBody({ d }: { d: ShadowArms }) {
  const written =
    d.arms.some((a) => a.kind === "shadow" && a.reviews > 0) || d.assignments.assigned > 0;
  const ordered = ARMS.map((id) => d.arms.find((a) => a.arm === id)).filter(
    (a): a is ArmRow => a !== undefined,
  );
  return (
    <div className="space-y-4" data-testid="shadow-arms-body">
      {!d.switches.orchestrate || !written ? <ShadowOffNotice switches={d.switches} /> : null}
      {written ? (
        <>
          <Block title={t("ai.arms.table.title", { days: d.days })} hint={t("ai.arms.table.hint")}>
            <Framed>
              <TableShell>
                <THead>
                  <TH>{t("ai.arms.col.arm")}</TH>
                  <TH align="right">{t("ai.arms.col.reviews")}</TH>
                  <TH align="right">{t("ai.arms.col.onSample")}</TH>
                  <TH align="right">{t("ai.arms.col.approved")}</TH>
                  <TH align="right">{t("ai.arms.col.downgraded")}</TH>
                  <TH align="right">{t("ai.arms.col.rejected")}</TH>
                  <TH align="right">{t("ai.arms.col.abstained")}</TH>
                  <TH align="right">{t("ai.arms.col.invalid")}</TH>
                  <TH align="right">{t("ai.arms.col.cost")}</TH>
                  <TH align="right">{t("ai.arms.col.p95")}</TH>
                </THead>
                <tbody>
                  {ordered.map((a) => (
                    <ArmRowView key={a.arm} a={a} />
                  ))}
                </tbody>
              </TableShell>
            </Framed>
          </Block>
          <EnoughPanel e={d.enough} />
          <AssignmentPanel a={d.assignments} asked={d.switches.shadow_sample} />
          <Block title={t("ai.arms.lab.title")} hint={t("ai.arms.lab.hint")}>
            <StatGrid testId="arms-lab">
              <Stat
                label={t("ai.arms.lab.window", { days: d.days })}
                value={usd(d.lab.window_usd)}
              />
              <Stat label={t("ai.arms.lab.shadow")} value={usd(d.lab.shadow_usd)} />
              <Stat label={t("ai.arms.lab.calls")} value={localInt(d.lab.calls)} />
              <Stat
                label={t("ai.arms.lab.cycle")}
                value={
                  d.last_cycle
                    ? translateOr(`ai.arms.cycle.${d.last_cycle.status}`, d.last_cycle.status)
                    : DASH
                }
                hint={d.last_cycle ? bogotaDateTime(d.last_cycle.started_at) : undefined}
              />
            </StatGrid>
          </Block>
          <Block title={t("ai.arms.detail.title")}>
            <div className="space-y-2">
              {ordered.map((a) => (
                <ArmDetail key={a.arm} a={a} />
              ))}
            </div>
          </Block>
        </>
      ) : null}
    </div>
  );
}

/** SOMBRA CON BRAZOS: the panel of Aprendizaje > Sombra. */
export function ShadowArmsPanel() {
  const q = useLiveQuery(live.aiShadowArms());
  const d = q.data?.data ?? null;
  return (
    <Panel
      title={t("ai.arms.title")}
      subtitle={t("ai.arms.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <div data-testid="shadow-arms">
        <Note>{t("ai.arms.intro")}</Note>
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {d ? <ShadowArmsBody d={d} /> : q.isLoading ? <TableSkeleton rows={7} cols={6} /> : null}
      </div>
    </Panel>
  );
}
