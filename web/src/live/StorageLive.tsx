/** Almacenamiento: where the server's disk goes, the copies, the last cleanup and the retention policy. Everything is read; nothing is
 * deleted from this page (the cleanups run on the server, with a verified off-site copy and the owner's word). */
import { t } from "@/lib/i18n";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { StorageOverview } from "@/lib/api/v1/types_storage";
import { int } from "@/lib/format";
import { localFixed } from "@/lib/i18n/format";
import { relative } from "./format";
import { bytes, daysText, levelTone, offsiteState, parts, retentionByTier } from "./storageModel";

export function StorageLive() {
  const q = useLiveQuery(live.adminStorage);
  const env = q.data;
  return (
    <div className="space-y-4" data-testid="storage-page">
      <PageHeader title={t("storage.title")} description={t("storage.description")} />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={6} cols={4} /> : null}
      {env ? <StorageView data={env.data} stale={env.data.stale === true} /> : null}
    </div>
  );
}

export function StorageView({ data, stale }: { data: StorageOverview; stale: boolean }) {
  const r = data.report;
  return (
    <>
      <p className="text-caption text-muted-foreground" data-testid="storage-readonly">
        {t("storage.readOnly")}
      </p>
      {!r ? (
        <p className="text-sm text-muted-foreground" data-testid="storage-empty">
          {t("storage.notReported")}
        </p>
      ) : (
        <>
          {stale ? (
            <p className="text-sm text-warning" data-testid="storage-stale">
              {t("storage.stale")}
            </p>
          ) : null}
          <p className="text-caption text-subtle-foreground">
            {t("storage.measuredAt", { when: relative(r.measured_at), host: r.host })}
          </p>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard
              label={t("storage.metrics.disk")}
              value={`${r.disk.pct} % · ${t(`storage.level.${data.level ?? r.disk.level}`)}`}
              tone={levelTone(data.level ?? r.disk.level)}
              hint={t("storage.metrics.diskHint", {
                used: bytes(r.disk.used_bytes),
                size: bytes(r.disk.size_bytes),
                free: bytes(r.disk.avail_bytes),
              })}
            />
            <MetricCard
              label={t("storage.metrics.database")}
              value={bytes(r.database.bytes)}
              hint={t("storage.metrics.databaseHint")}
            />
            <MetricCard
              label={t("storage.metrics.raw")}
              value={bytes(r.parts.raw_bytes)}
              hint={t("storage.metrics.rawHint", { files: int(r.parts.raw_files ?? null) })}
            />
            <MetricCard
              label={t("storage.metrics.docker")}
              value={bytes(
                (r.docker.images_bytes ?? 0) +
                  (r.docker.volumes_bytes ?? 0) +
                  (r.docker.build_cache_bytes ?? 0),
              )}
              hint={t("storage.metrics.dockerHint", {
                reclaimable: bytes(
                  (r.docker.images_reclaimable_bytes ?? 0) +
                    (r.docker.volumes_orphan_bytes ?? 0) +
                    (r.docker.build_cache_reclaimable_bytes ?? 0),
                ),
              })}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel
              title={t("storage.parts.title")}
              subtitle={t("storage.parts.subtitle")}
              bodyClassName=""
            >
              <TableShell compact>
                <tbody>
                  {parts(r).map((p) => (
                    <TRow key={p.key}>
                      <TD className="text-sm">
                        {p.key === "dockerVolumes" && (r.docker.volumes_orphan_count ?? 0) > 0
                          ? `${p.label} · ${t("storage.parts.orphanVolumes", { n: r.docker.volumes_orphan_count ?? 0 })}`
                          : p.label}
                      </TD>
                      <TD className="text-right text-sm tabular-nums">{bytes(p.bytes)}</TD>
                      <TD className="text-right text-caption text-muted-foreground">
                        {p.reclaimable
                          ? t("storage.parts.reclaimable", { bytes: bytes(p.reclaimable) })
                          : ""}
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            </Panel>
            <GrowthPanel data={data} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <BackupsPanel data={data} />
            <Panel
              title={t("storage.tables.title")}
              subtitle={t("storage.tables.subtitle")}
              bodyClassName=""
            >
              <TableShell compact>
                <THead>
                  <TH>{t("storage.tables.name")}</TH>
                  <TH align="right">{t("storage.tables.size")}</TH>
                </THead>
                <tbody>
                  {r.database.top_tables.map((tb) => (
                    <TRow key={tb.name}>
                      <TD className="font-mono text-xs">{tb.name}</TD>
                      <TD className="text-right text-sm tabular-nums">{bytes(tb.bytes)}</TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            </Panel>
          </div>

          <Panel title={t("storage.cleanup.title")} subtitle={t("storage.cleanup.subtitle")}>
            {r.cleanup ? (
              <>
                <KeyValue label={t("storage.cleanup.last")} value={relative(r.cleanup.at)} />
                <KeyValue label={t("storage.cleanup.freed")} value={bytes(r.cleanup.freed_bytes)} />
                <KeyValue label={t("storage.cleanup.items")} value={int(r.cleanup.items.length)} />
              </>
            ) : (
              <p className="text-xs text-muted-foreground" data-testid="storage-cleanup-none">
                {t("storage.cleanup.none")}
              </p>
            )}
          </Panel>
        </>
      )}
      <RetentionPanel data={data} />
    </>
  );
}

function GrowthPanel({ data }: { data: StorageOverview }) {
  const p = data.projection;
  const g = data.report?.growth;
  return (
    <Panel title={t("storage.growth.title")} subtitle={t("storage.growth.subtitle")}>
      {g?.anomaly ? (
        <p className="mb-2 text-sm text-negative" data-testid="storage-anomaly">
          {t("storage.growth.anomaly", {
            delta: bytes(g.last_delta_bytes),
            median: bytes(g.median_delta_bytes),
          })}
        </p>
      ) : null}
      {p && p.per_day_bytes !== null ? (
        <>
          <KeyValue
            label={t("storage.growth.perDay")}
            value={t("storage.growth.perDayValue", { bytes: bytes(p.per_day_bytes) })}
          />
          {p.at.map((a) => (
            <KeyValue
              key={a.days}
              label={t("storage.growth.in", { days: a.days })}
              value={t("storage.growth.inValue", {
                bytes: bytes(a.used_bytes),
                pct: localFixed(a.pct, 0),
              })}
            />
          ))}
          <KeyValue label={t("storage.growth.to80")} value={daysText(p.days_to["80"])} />
          <KeyValue label={t("storage.growth.to90")} value={daysText(p.days_to["90"])} />
        </>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="storage-no-projection">
          {t("storage.growth.noProjection")}
        </p>
      )}
      {g?.last_day && g.last_delta_bytes !== undefined ? (
        <KeyValue
          label={t("storage.growth.lastDay", { day: g.last_day })}
          value={bytes(g.last_delta_bytes)}
        />
      ) : null}
    </Panel>
  );
}

function BackupsPanel({ data }: { data: StorageOverview }) {
  const b = data.report?.backups;
  const latest = b?.latest ?? null;
  const state = offsiteState(data);
  const restore = b?.restore_test ?? null;
  return (
    <Panel title={t("storage.backups.title")} subtitle={t("storage.backups.subtitle")}>
      <KeyValue
        label={t("storage.backups.latest")}
        value={latest ? `${latest.name} · ${relative(latest.at)}` : t("storage.backups.none")}
      />
      {latest ? <KeyValue label={t("storage.backups.size")} value={bytes(latest.bytes)} /> : null}
      {latest?.sha256 ? (
        <KeyValue
          label={t("storage.backups.checksum")}
          value={<span className="font-mono text-xs">{latest.sha256.slice(0, 16)}…</span>}
        />
      ) : null}
      <KeyValue
        label={t("storage.backups.offsite")}
        value={
          <span data-testid="storage-offsite" data-state={state}>
            <StatusBadge tone={state === "ok" ? "positive" : "negative"}>
              {state === "ok"
                ? t("storage.backups.offsiteYes", {
                    when: relative(latest?.offsite?.verified_at ?? null),
                  })
                : state === "missing"
                  ? t("storage.backups.offsiteMissing")
                  : t("storage.backups.offsiteNotConfigured")}
            </StatusBadge>
          </span>
        }
      />
      <KeyValue
        label={t("storage.backups.restore")}
        value={
          restore?.at ? (
            <StatusBadge tone={restore.passed ? "positive" : "negative"}>
              {restore.passed
                ? t("storage.backups.restorePassed", {
                    when: relative(restore.at),
                    seconds: int(restore.seconds),
                  })
                : t("storage.backups.restoreFailed", { when: relative(restore.at) })}
            </StatusBadge>
          ) : (
            t("storage.backups.restoreNever")
          )
        }
      />
      {b?.keep_daily !== undefined ? (
        <KeyValue
          label={t("storage.backups.keep")}
          value={t("storage.backups.keepValue", {
            daily: b.keep_daily,
            weekly: b.keep_weekly ?? 0,
          })}
        />
      ) : null}
    </Panel>
  );
}

function RetentionPanel({ data }: { data: StorageOverview }) {
  return (
    <Panel
      title={t("storage.retention.title")}
      subtitle={t("storage.retention.subtitle")}
      bodyClassName=""
    >
      <TableShell compact>
        <THead>
          <TH>{t("storage.retention.headers.what")}</TH>
          <TH>{t("storage.retention.headers.where")}</TH>
          <TH>{t("storage.retention.headers.keep")}</TH>
        </THead>
        <tbody>
          {retentionByTier(data).flatMap((g) => [
            <TRow key={`tier-${g.tier}`}>
              <TD className="pt-3 text-caption font-semibold uppercase text-muted-foreground">
                {t(`storage.retention.tier.${g.tier}`)}
              </TD>
              <TD>{""}</TD>
              <TD>{""}</TD>
            </TRow>,
            ...g.rows.map((row) => (
              <TRow key={row.what}>
                <TD className="text-sm">{t(`storage.retention.what.${row.what}`)}</TD>
                <TD className="text-xs text-muted-foreground">
                  {t(`storage.retention.where.${row.where}`)}
                </TD>
                <TD className="text-xs">{t(`storage.retention.keep.${row.keep}`)}</TD>
              </TRow>
            )),
          ])}
        </tbody>
      </TableShell>
    </Panel>
  );
}
