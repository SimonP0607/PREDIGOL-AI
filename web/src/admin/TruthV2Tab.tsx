/**
 * Data truth audit V2 in the Admin Console: the newest run of each audit command and the evidence
 * ledger (E-XXX) - every established discrepancy with who is at fault, its root cause and its fix.
 * The audits run on the machine (`python -m scripts.audit_standings`, `audit_team_stats`,
 * `audit_player_stats`, `audit_data_truth ...`); this page reads them and records the owner's verdict.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MetricCard, Panel } from "@/components/primitives/Panel";
import {
  LimitedRows,
  TableShell,
  TableSkeleton,
  TD,
  TH,
  THead,
  TRow,
} from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { FilterBar, SelectFilter } from "@/components/system/Filters";
import { SeverityBadge } from "@/components/system/Timelines";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { EvidenceEntry, EvidenceFault, EvidenceStatus } from "@/lib/api/v1/types_truth";
import { t, translateOr } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { formatDateTime, formatRelative } from "@/lib/time";
import { EmptyState, ErrorState } from "@/product/shared/States";

const STATUS_TONE: Record<EvidenceStatus, BadgeTone> = {
  OPEN: "negative",
  MONITOR: "warning",
  FIXED: "positive",
  ACCEPTED: "info",
  CLEARED: "neutral",
};
const FAULT_TONE: Record<EvidenceFault, BadgeTone> = {
  predigol: "negative",
  provider: "warning",
  none: "neutral",
  undetermined: "info",
};

function verdicts(summary: Record<string, unknown>): string {
  const v = (summary["verdicts"] ??
    summary["block_verdicts"] ??
    summary["labels"] ??
    summary["classes"]) as Record<string, number> | undefined;
  if (!v || typeof v !== "object") return "—";
  return Object.entries(v)
    .map(([k, n]) => `${k} ${localInt(n)}`)
    .join(" · ");
}

function Decide({ entry }: { entry: EvidenceEntry }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: (status: "FIXED" | "ACCEPTED" | "MONITOR" | "OPEN") =>
      v1.decideEvidence(entry.code, status),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["v1", "truth", "v2"] }),
  });
  if (entry.status === "CLEARED") return null;
  return (
    <div className="flex flex-wrap gap-1">
      {(["ACCEPTED", "MONITOR", "FIXED"] as const)
        .filter((s) => s !== entry.status)
        .map((s) => (
          <button
            key={s}
            type="button"
            disabled={m.isPending}
            onClick={() => m.mutate(s)}
            className="rounded border border-border px-1.5 py-0.5 text-[11px] hover:bg-muted"
          >
            {t(`truth.v2.decide.${s}`)}
          </button>
        ))}
    </div>
  );
}

export function TruthV2Tab() {
  const q = useQuery({ ...live.truthV2 });
  const [area, setArea] = useState("all");
  const [status, setStatus] = useState("OPEN");
  const data = q.data?.data;
  const ledger = useMemo(
    () =>
      (data?.ledger ?? []).filter(
        (e) => (area === "all" || e.area === area) && (status === "all" || e.status === status),
      ),
    [data, area, status],
  );
  if (q.isPending) return <TableSkeleton rows={8} cols={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!data || (data.runs.length === 0 && data.ledger.length === 0))
    return <EmptyState title={q.data?.reason ?? t("truth.v2.none")} />;
  const open = data.counts["OPEN"] ?? {};
  const areas = Array.from(new Set(data.ledger.map((e) => e.area))).sort();
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(["critical", "high", "medium", "low"] as const).map((s) => (
          <MetricCard
            key={s}
            label={t(`truth.v2.open.${s}`)}
            value={localInt(open[s] ?? 0)}
            tone={
              s === "critical" || s === "high"
                ? (open[s] ?? 0) > 0
                  ? "negative"
                  : "default"
                : "default"
            }
          />
        ))}
      </div>
      <Panel
        title={t("truth.v2.runs.title")}
        subtitle={t("truth.v2.runs.subtitle")}
        bodyClassName=""
      >
        <TableShell>
          <THead>
            <TH>{t("truth.v2.runs.kind")}</TH>
            <TH>{t("truth.v2.runs.when")}</TH>
            <TH>{t("truth.v2.runs.status")}</TH>
            <TH align="right">{t("truth.v2.runs.requests")}</TH>
            <TH>{t("truth.v2.runs.verdicts")}</TH>
          </THead>
          <tbody>
            {data.runs.map((r) => (
              <TRow key={r.id}>
                <TD className="text-sm">{translateOr(`truth.v2.kinds.${r.kind}`, r.kind)}</TD>
                <TD className="text-xs">
                  <span title={formatDateTime(r.started_at)}>
                    {formatRelative(r.finished_at ?? r.started_at)}
                  </span>
                </TD>
                <TD>
                  <StatusBadge tone={r.status === "completed" ? "positive" : "warning"}>
                    {r.status}
                  </StatusBadge>
                </TD>
                <TD align="right" className="numeric text-xs">
                  {localInt(r.requests)}
                </TD>
                <TD className="text-xs text-muted-foreground">{verdicts(r.summary)}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </Panel>
      <Panel
        title={t("truth.v2.ledger.title")}
        subtitle={t("truth.v2.ledger.subtitle")}
        bodyClassName=""
      >
        <FilterBar>
          <SelectFilter
            label={t("truth.v2.ledger.area")}
            value={area}
            onChange={setArea}
            options={[
              { value: "all", label: t("truth.findings.all") },
              ...areas.map((a) => ({ value: a, label: translateOr(`truth.v2.areas.${a}`, a) })),
            ]}
          />
          <SelectFilter
            label={t("truth.v2.ledger.status")}
            value={status}
            onChange={setStatus}
            options={[
              { value: "all", label: t("truth.findings.all") },
              ...(["OPEN", "MONITOR", "ACCEPTED", "FIXED", "CLEARED"] as const).map((s) => ({
                value: s,
                label: t(`truth.v2.status.${s}`),
              })),
            ]}
          />
        </FilterBar>
        {ledger.length === 0 ? (
          <EmptyState title={t("truth.v2.ledger.empty")} />
        ) : (
          <LimitedRows rows={ledger} step={40}>
            {(shown) => (
              <TableShell>
                <THead>
                  <TH>{t("truth.v2.ledger.code")}</TH>
                  <TH>{t("truth.v2.ledger.severity")}</TH>
                  <TH>{t("truth.v2.ledger.issue")}</TH>
                  <TH>{t("truth.v2.ledger.fault")}</TH>
                  <TH>{t("truth.v2.ledger.claim")}</TH>
                  <TH>{t("truth.v2.ledger.status")}</TH>
                  <TH>{t("truth.v2.ledger.decide")}</TH>
                </THead>
                <tbody>
                  {shown.map((e) => (
                    <TRow key={e.code}>
                      <TD className="font-mono text-[11px]">{e.code}</TD>
                      <TD>
                        {e.severity === "info" ? (
                          <StatusBadge tone="neutral">info</StatusBadge>
                        ) : (
                          <SeverityBadge severity={e.severity} />
                        )}
                      </TD>
                      <TD className="text-xs">
                        <div>{e.issue_type}</div>
                        <div className="text-caption text-subtle-foreground">
                          {translateOr(`truth.v2.areas.${e.area}`, e.area)}
                        </div>
                      </TD>
                      <TD>
                        <StatusBadge tone={FAULT_TONE[e.at_fault]}>
                          {t(`truth.v2.fault.${e.at_fault}`)}
                        </StatusBadge>
                      </TD>
                      <TD className="max-w-xl text-xs">
                        <div>{e.claim}</div>
                        {e.root_cause ? (
                          <div className="text-caption text-subtle-foreground">
                            {t("truth.v2.ledger.cause")}: {e.root_cause}
                          </div>
                        ) : null}
                        {e.fix ? (
                          <div className="text-caption text-subtle-foreground">
                            {t("truth.v2.ledger.fix")}: {e.fix}
                          </div>
                        ) : null}
                      </TD>
                      <TD>
                        <StatusBadge tone={STATUS_TONE[e.status]}>
                          {t(`truth.v2.status.${e.status}`)}
                        </StatusBadge>
                        <div className="text-caption text-subtle-foreground">
                          {t("truth.v2.ledger.seen", {
                            n: e.times_seen,
                            when: formatRelative(e.last_seen_at),
                          })}
                        </div>
                      </TD>
                      <TD>
                        <Decide entry={e} />
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </LimitedRows>
        )}
      </Panel>
    </div>
  );
}
