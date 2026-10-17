import { t } from "@/lib/i18n";
import { Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD } from "@/components/primitives/DataTable";
import { Numeric } from "@/components/primitives/Indicators";
import { StatusNotice } from "@/components/system/LiveState";
import type { JobHealth, RunSummary } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { durationMs, utcDateTime } from "./format";
import { RunStatusBadge } from "./shared";
import { jobLabel } from "./labels";

export function RunsPanel({ runs }: { runs: RunSummary[] }) {
  return (
    <Panel title={t("system.runs.title")} subtitle={t("system.runs.subtitle")} bodyClassName="">
      {runs.length === 0 ? (
        <StatusNotice status="empty" reason={t("system.runs.empty")} />
      ) : (
        <TableShell>
          <THead>
            <TH>{t("system.runs.headers.job")}</TH>
            <TH>{t("system.runs.headers.status")}</TH>
            <TH>{t("system.runs.headers.started")}</TH>
            <TH align="right">{t("system.runs.headers.duration")}</TH>
            <TH align="right">{t("system.runs.headers.requests")}</TH>
            <TH align="right">{t("system.runs.headers.rows")}</TH>
            <TH align="right">{t("system.runs.headers.errors")}</TH>
          </THead>
          <tbody>
            {runs.map((r) => (
              <TRow key={r.id}>
                <TD>
                  <div className="text-sm">{jobLabel(r.job_type)}</div>
                  <div className="numeric text-caption text-subtle-foreground">
                    {t("system.runs.runId", { id: r.id })}
                  </div>
                </TD>
                <TD>
                  <RunStatusBadge status={r.status} />
                </TD>
                <TD>
                  <Numeric>{utcDateTime(r.started_at)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric muted>{durationMs(r.duration_ms)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric>{int(r.api_calls)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric>
                    {int(r.rows_written)} / {int(r.rows_updated)}
                  </Numeric>
                </TD>
                <TD align="right">
                  <span title={r.last_error ?? undefined}>
                    <Numeric className={r.errors ? "text-warning" : ""}>{int(r.errors)}</Numeric>
                  </span>
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}

export function JobsPanel({ jobs }: { jobs: JobHealth[] }) {
  return (
    <Panel title={t("system.jobs.title")} subtitle={t("system.jobs.subtitle")} bodyClassName="">
      {jobs.length === 0 ? (
        <StatusNotice status="empty" reason={t("system.jobs.empty")} />
      ) : (
        <TableShell>
          <THead>
            <TH>{t("system.jobs.headers.job")}</TH>
            <TH>{t("system.jobs.headers.last")}</TH>
            <TH align="right">{t("system.jobs.headers.runs24h")}</TH>
            <TH align="right">{t("system.jobs.headers.failedPartial")}</TH>
            <TH align="right">{t("system.jobs.headers.requests24h")}</TH>
            <TH>{t("system.jobs.headers.lastSuccess")}</TH>
            <TH>{t("system.jobs.headers.nextRun")}</TH>
          </THead>
          <tbody>
            {jobs.map((j) => (
              <TRow key={j.job_type}>
                <TD>
                  <div className="text-sm">{jobLabel(j.job_type)}</div>
                  {j.last_error ? (
                    <div
                      className="max-w-md truncate text-caption text-subtle-foreground"
                      title={j.last_error}
                    >
                      {t("system.jobs.lastError", { error: j.last_error })}
                    </div>
                  ) : null}
                </TD>
                <TD>
                  {j.last_status ? (
                    <RunStatusBadge status={j.last_status as RunSummary["status"]} />
                  ) : (
                    "—"
                  )}
                </TD>
                <TD align="right">
                  <Numeric>{int(j.runs_24h)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric className={j.failed_24h ? "text-negative" : ""}>
                    {int(j.failed_24h)} / {int(j.partial_24h)}
                  </Numeric>
                </TD>
                <TD align="right">
                  <Numeric muted>{int(j.api_calls_24h)}</Numeric>
                </TD>
                <TD>
                  <Numeric muted>{utcDateTime(j.last_success_at)}</Numeric>
                </TD>
                <TD>
                  <Numeric muted>
                    {j.next_run_at ? utcDateTime(j.next_run_at) : t("system.jobs.manual")}
                  </Numeric>
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}
