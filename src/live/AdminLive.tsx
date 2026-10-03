/** System / Admin: the private operations view. Everything here is read; nothing is triggered. */
import { t, translateOr } from "@/lib/i18n";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, SectionView } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { ComponentStatus, Section } from "@/lib/api/v1/types";
import type { AdminCount, BackfillProgress } from "@/lib/api/v1/types_center";
import { int } from "@/lib/format";
import { relative, utcDateTime } from "./format";
import { jobLabel } from "./labels";
import { ComponentStatusBadge } from "./shared";
import { localFixed } from "@/lib/i18n/format";

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
  return `${localFixed(v, i === 0 ? 0 : 1)} ${units[i]}`;
}

/** A count from the API, named in the reader's language when its key is known (else the API's label). */
function countLabel(group: "captures" | "quality", c: AdminCount): string {
  return c.key ? translateOr(`system.${group}.labels.${c.key}`, c.label) : c.label;
}

function countNote(c: AdminCount): string | undefined {
  if (!c.note) return undefined;
  return c.key ? translateOr(`system.captures.notes.${c.key}`, c.note) : c.note;
}

export function AdminLive() {
  const q = useLiveQuery(live.admin);
  const d = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.system.title")}
        description={t("admin.pages.system.description")}
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={6} cols={4} /> : null}
      {d ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard
              label={t("system.metrics.worker")}
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
              label={t("system.metrics.apiFootball")}
              value={`${int(d.quota.spent)} / ${int(d.quota.budget)}`}
              hint={t("system.metrics.quotaHint", {
                left: int(d.quota.remaining),
                plan: int(d.quota.plan_limit_per_day),
              })}
              tone={d.quota.remaining < 3000 ? "warning" : "default"}
            />
            <MetricCard
              label={t("system.metrics.provider")}
              value={d.quota.provider_status.status.toUpperCase()}
              tone={d.quota.provider_status.status === "ok" ? "positive" : "warning"}
              hint={d.quota.provider_status.detail}
            />
            <MetricCard
              label={t("system.metrics.database")}
              value={bytes(d.database_bytes)}
              hint={t("system.metrics.schemaHint", { rev: d.schema_revision ?? "?" })}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel
              title={t("system.workerJobs.title")}
              subtitle={t("system.workerJobs.subtitle")}
              className="lg:col-span-1"
              bodyClassName=""
            >
              <TableShell compact>
                <THead>
                  <TH>{t("system.workerJobs.job")}</TH>
                  <TH>{t("system.workerJobs.nextRun")}</TH>
                </THead>
                <tbody>
                  {Object.entries(d.jobs_next)
                    .sort((a, b) => (a[1] ?? "").localeCompare(b[1] ?? ""))
                    .map(([k, v]) => (
                      <TRow key={k}>
                        <TD className="text-sm">{jobLabel(k)}</TD>
                        <TD className="text-xs text-muted-foreground">
                          {v ? utcDateTime(v) : "—"}
                        </TD>
                      </TRow>
                    ))}
                </tbody>
              </TableShell>
              <div className="px-4 py-2 text-caption">
                <Link to="/admin/data-quality" className="text-primary hover:underline">
                  {t("system.workerJobs.ledgerLink")}
                </Link>
              </div>
            </Panel>
            <Panel
              title={t("system.captures.title")}
              subtitle={t("system.captures.subtitle")}
              className="lg:col-span-2"
            >
              <div className="grid gap-x-6 sm:grid-cols-2">
                {d.captures.map((c) => (
                  <KeyValue
                    key={c.key ?? c.label}
                    label={countLabel("captures", c)}
                    value={
                      <span title={countNote(c)}>
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

          <BackfillPanel section={d.migration} />

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel
              title={t("system.errors.title")}
              subtitle={t("system.errors.subtitle")}
              className="lg:col-span-2"
              bodyClassName=""
            >
              <SectionView section={d.errors}>
                {(rows) => (
                  <div className="max-h-[360px] overflow-auto">
                    <TableShell compact>
                      <THead>
                        <TH>{t("system.errors.headers.when")}</TH>
                        <TH>{t("system.errors.headers.job")}</TH>
                        <TH>{t("system.errors.headers.status")}</TH>
                        <TH>{t("system.errors.headers.error")}</TH>
                      </THead>
                      <tbody>
                        {rows.map((e) => (
                          <TRow key={e.run_id}>
                            <TD className="whitespace-nowrap text-xs text-muted-foreground">
                              {utcDateTime(e.started_at)}
                            </TD>
                            <TD className="text-xs">{jobLabel(e.job_type)}</TD>
                            <TD>
                              <StatusBadge tone={e.status === "failed" ? "negative" : "warning"}>
                                {translateOr(`admin.status.run.${e.status}`, e.status)}
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
            <Panel title={t("system.quality.title")} subtitle={t("system.quality.subtitle")}>
              {d.quality.length ? (
                d.quality.map((c) => (
                  <KeyValue
                    key={c.key ?? c.label}
                    label={countLabel("quality", c)}
                    value={int(c.value)}
                  />
                ))
              ) : (
                <p className="text-xs text-muted-foreground">{t("system.quality.empty")}</p>
              )}
              <div className="mt-2 text-caption">
                <Link to="/admin/data-quality" className="text-primary hover:underline">
                  {t("system.quality.link")}
                </Link>
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel
              title={t("system.backups.title")}
              subtitle={t("system.backups.subtitle")}
              className="lg:col-span-2"
              bodyClassName=""
            >
              <SectionView section={d.backups}>
                {(rows) => (
                  <TableShell compact>
                    <THead>
                      <TH>{t("system.backups.headers.file")}</TH>
                      <TH align="right">{t("system.backups.headers.size")}</TH>
                      <TH>{t("system.backups.headers.written")}</TH>
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
            <Panel title={t("system.versions.title")}>
              <KeyValue label={t("system.versions.backend")} value={d.backend_version} />
              <KeyValue label={t("system.versions.backendCode")} value={d.code_version} />
              <KeyValue label={t("system.versions.schema")} value={d.schema_revision ?? "—"} />
              <KeyValue label={t("system.versions.frontend")} value={FRONTEND_VERSION} />
              <KeyValue
                label={t("system.versions.worker")}
                value={<ComponentStatusBadge status={d.worker.status as ComponentStatus} />}
              />
              <KeyValue
                label={t("system.versions.workerBuild")}
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

/** Seeded backfill tasks by kind - shared by System and Migration. */
export function BackfillPanel({ section }: { section: Section<BackfillProgress[]> }) {
  return (
    <Panel
      title={t("system.backfill.title")}
      subtitle={t("system.backfill.subtitle")}
      bodyClassName=""
    >
      <SectionView section={section}>
        {(rows) => {
          const total = rows.reduce((s, r) => s + r.total, 0);
          const done = rows.reduce((s, r) => s + r.done, 0);
          return (
            <>
              <div className="px-4 pt-3">
                <div className="flex items-baseline justify-between text-xs">
                  <span>
                    {t("system.backfill.progress", { done: int(done), total: int(total) })}
                  </span>
                  <StatusBadge tone={done === total ? "positive" : "info"}>
                    {done === total ? t("system.backfill.complete") : t("system.backfill.running")}
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
                  <TH>{t("system.backfill.headers.kind")}</TH>
                  <TH align="right">{t("system.backfill.headers.done")}</TH>
                  <TH align="right">{t("system.backfill.headers.pending")}</TH>
                  <TH align="right">{t("system.backfill.headers.running")}</TH>
                  <TH align="right">{t("system.backfill.headers.failed")}</TH>
                  <TH>{t("system.backfill.headers.lastCompleted")}</TH>
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
  );
}
