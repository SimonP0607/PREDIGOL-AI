/** System / Admin: the private operations view. Everything here is read; nothing is triggered. */
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, SectionView } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { ComponentStatus } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { relative, utcDateTime } from "./format";
import { JOB_LABEL } from "./labels";
import { ComponentStatusBadge } from "./shared";

const FRONTEND_VERSION = (import.meta.env["VITE_APP_VERSION"] as string | undefined) ?? "dev";

function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function jobName(k: string): string {
  return (JOB_LABEL as Record<string, string>)[k] ?? k.replace(/_/g, " ");
}

export function AdminLive() {
  const q = useLiveQuery(live.admin);
  const d = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "System" }, { label: "System / Admin" }]}
        title="System / Admin"
        description="Private operations view: worker, provider quota, history migration, captures, errors, data quality, backups and versions. Read-only; refreshed every 30 seconds."
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={6} cols={4} /> : null}
      {d ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard
              label="Worker"
              value={d.worker.status.toUpperCase()}
              tone={
                d.worker.status === "ok"
                  ? "positive"
                  : d.worker.status === "down"
                    ? "negative"
                    : "warning"
              }
              hint={d.worker.detail}
            />
            <MetricCard
              label="API-Football today"
              value={`${int(d.quota.spent)} / ${int(d.quota.budget)}`}
              hint={`${int(d.quota.remaining)} left under our guard · plan ${int(d.quota.plan_limit_per_day)}/day`}
              tone={d.quota.remaining < 3000 ? "warning" : "default"}
            />
            <MetricCard
              label="Provider"
              value={d.quota.provider_status.status.toUpperCase()}
              tone={d.quota.provider_status.status === "ok" ? "positive" : "warning"}
              hint={d.quota.provider_status.detail}
            />
            <MetricCard
              label="Database"
              value={bytes(d.database_bytes)}
              hint={`schema ${d.schema_revision ?? "?"}`}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel
              title="Worker jobs"
              subtitle="Next scheduled run of each job (UTC)."
              className="lg:col-span-1"
              bodyClassName=""
            >
              <TableShell compact>
                <THead>
                  <TH>Job</TH>
                  <TH>Next run</TH>
                </THead>
                <tbody>
                  {Object.entries(d.jobs_next)
                    .sort((a, b) => (a[1] ?? "").localeCompare(b[1] ?? ""))
                    .map(([k, v]) => (
                      <TRow key={k}>
                        <TD className="text-sm">{jobName(k)}</TD>
                        <TD className="text-xs text-muted-foreground">
                          {v ? utcDateTime(v) : "—"}
                        </TD>
                      </TRow>
                    ))}
                </tbody>
              </TableShell>
              <div className="px-4 py-2 text-caption">
                <Link to="/data-quality" className="text-primary hover:underline">
                  Job ledger and run history →
                </Link>
              </div>
            </Panel>
            <Panel
              title="Captures"
              subtitle="What the pipelines wrote recently."
              className="lg:col-span-2"
            >
              <div className="grid gap-x-6 sm:grid-cols-2">
                {d.captures.map((c) => (
                  <KeyValue
                    key={c.label}
                    label={c.label}
                    value={
                      <span title={c.note ?? undefined}>
                        {int(c.value)}
                        {c.at ? (
                          <span className="ml-1.5 text-subtle-foreground">· {relative(c.at)}</span>
                        ) : null}
                      </span>
                    }
                  />
                ))}
              </div>
            </Panel>
          </div>

          <Panel
            title="History migration"
            subtitle="Seeded backfill tasks by kind. Each task is one provider request; nothing is re-requested that the raw store already holds."
            bodyClassName=""
          >
            <SectionView section={d.migration}>
              {(rows) => {
                const total = rows.reduce((s, r) => s + r.total, 0);
                const done = rows.reduce((s, r) => s + r.done, 0);
                return (
                  <>
                    <div className="px-4 pt-3">
                      <div className="flex items-baseline justify-between text-xs">
                        <span>
                          {int(done)} of {int(total)} tasks done
                        </span>
                        <StatusBadge tone={done === total ? "positive" : "info"}>
                          {done === total ? "complete" : "running"}
                        </StatusBadge>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full bg-primary"
                          style={{ width: `${total ? (done / total) * 100 : 0}%` }}
                        />
                      </div>
                    </div>
                    <TableShell>
                      <THead>
                        <TH>Kind</TH>
                        <TH align="right">Done</TH>
                        <TH align="right">Pending</TH>
                        <TH align="right">Running</TH>
                        <TH align="right">Failed</TH>
                        <TH>Last completed</TH>
                      </THead>
                      <tbody>
                        {rows.map((r) => (
                          <TRow key={r.kind}>
                            <TD className="text-sm">{r.kind.replace(/_/g, " ")}</TD>
                            <TD align="right">
                              <Numeric className="text-xs">
                                {int(r.done)} / {int(r.total)}
                              </Numeric>
                            </TD>
                            <TD align="right">
                              <Numeric muted={!r.pending} className="text-xs">
                                {int(r.pending)}
                              </Numeric>
                            </TD>
                            <TD align="right">
                              <Numeric muted={!r.running} className="text-xs">
                                {int(r.running)}
                              </Numeric>
                            </TD>
                            <TD align="right">
                              <Numeric
                                className={r.failed ? "text-xs text-negative" : "text-xs"}
                                muted={!r.failed}
                              >
                                {int(r.failed)}
                              </Numeric>
                            </TD>
                            <TD className="text-xs text-muted-foreground">
                              {r.last_completed_at ? utcDateTime(r.last_completed_at) : "—"}
                            </TD>
                          </TRow>
                        ))}
                      </tbody>
                    </TableShell>
                  </>
                );
              }}
            </SectionView>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel
              title="Errors, last 72 h"
              subtitle="Runs that failed, half-succeeded, hit a cap or were cut off."
              className="lg:col-span-2"
              bodyClassName=""
            >
              <SectionView section={d.errors}>
                {(rows) => (
                  <div className="max-h-[360px] overflow-auto">
                    <TableShell compact>
                      <THead>
                        <TH>When</TH>
                        <TH>Job</TH>
                        <TH>Status</TH>
                        <TH>Error</TH>
                      </THead>
                      <tbody>
                        {rows.map((e) => (
                          <TRow key={e.run_id}>
                            <TD className="whitespace-nowrap text-xs text-muted-foreground">
                              {utcDateTime(e.started_at)}
                            </TD>
                            <TD className="text-xs">{jobName(e.job_type)}</TD>
                            <TD>
                              <StatusBadge tone={e.status === "failed" ? "negative" : "warning"}>
                                {e.status}
                              </StatusBadge>
                            </TD>
                            <TD className="max-w-[28rem] truncate text-caption text-muted-foreground">
                              <span title={e.error ?? undefined}>{e.error ?? "—"}</span>
                            </TD>
                          </TRow>
                        ))}
                      </tbody>
                    </TableShell>
                  </div>
                )}
              </SectionView>
            </Panel>
            <Panel title="Data quality" subtitle="Open issues by severity.">
              {d.quality.length ? (
                d.quality.map((c) => (
                  <KeyValue key={c.label} label={c.label} value={int(c.value)} />
                ))
              ) : (
                <p className="text-xs text-muted-foreground">No open issue.</p>
              )}
              <div className="mt-2 text-caption">
                <Link to="/data-quality" className="text-primary hover:underline">
                  Open Data Quality →
                </Link>
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel
              title="Backups"
              subtitle="Database dumps found on this machine, newest first."
              className="lg:col-span-2"
              bodyClassName=""
            >
              <SectionView section={d.backups}>
                {(rows) => (
                  <TableShell compact>
                    <THead>
                      <TH>File</TH>
                      <TH align="right">Size</TH>
                      <TH>Written</TH>
                    </THead>
                    <tbody>
                      {rows.map((b) => (
                        <TRow key={`${b.location}/${b.name}`}>
                          <TD className="text-xs">
                            {b.name}
                            <div className="text-caption text-subtle-foreground">{b.location}</div>
                          </TD>
                          <TD align="right">
                            <Numeric
                              className={b.bytes === 0 ? "text-xs text-negative" : "text-xs"}
                            >
                              {bytes(b.bytes)}
                            </Numeric>
                          </TD>
                          <TD className="text-xs text-muted-foreground">
                            {utcDateTime(b.modified_at)} · {relative(b.modified_at)}
                          </TD>
                        </TRow>
                      ))}
                    </tbody>
                  </TableShell>
                )}
              </SectionView>
            </Panel>
            <Panel title="Versions">
              <KeyValue label="Backend" value={d.backend_version} />
              <KeyValue label="Backend code" value={d.code_version} />
              <KeyValue label="Schema" value={d.schema_revision ?? "—"} />
              <KeyValue label="Frontend" value={FRONTEND_VERSION} />
              <KeyValue
                label="Worker"
                value={<ComponentStatusBadge status={d.worker.status as ComponentStatus} />}
              />
              <KeyValue
                label="Worker build"
                value={String(
                  ((d.worker.data["heartbeat"] as Record<string, unknown> | undefined)?.[
                    "code_version"
                  ] as string | undefined) ?? "—",
                )}
              />
            </Panel>
          </div>
        </>
      ) : null}
    </div>
  );
}
