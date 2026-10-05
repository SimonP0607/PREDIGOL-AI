/**
 * The fourteen datasets, each with its class (FRESH, STALE, INCOMPLETE, INVALID, UNKNOWN), whether a model may
 * use it, the provider endpoint, its service level, the last capture and write, rows, coverage, errors and what
 * blocks it (GET /admin/data/datasets, measured now and kept for two minutes).
 */
import { useQuery } from "@tanstack/react-query";
import { Panel } from "@/components/primitives/Panel";
import { TableShell, TableSkeleton, TD, TH, THead, TRow } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { live } from "@/lib/api/v1/queries";
import type { DatasetClass, ModelEligibility } from "@/lib/api/v1/types_truth";
import { t, translateOr } from "@/lib/i18n";
import { localInt, localPct } from "@/lib/i18n/format";
import { formatRelative } from "@/lib/time";
import { EmptyState, ErrorState } from "@/product/shared/States";

const CLASS_TONE: Record<DatasetClass, BadgeTone> = {
  FRESH: "positive",
  STALE: "negative",
  INCOMPLETE: "warning",
  INVALID: "negative",
  UNKNOWN: "neutral",
};

const MODEL_TONE: Record<ModelEligibility, BadgeTone> = {
  MODEL_READY: "positive",
  NOT_MODEL_READY: "warning",
  NOT_USED: "neutral",
};

export function DatasetsTab() {
  const q = useQuery({ ...live.datasets });
  if (q.isPending) return <TableSkeleton rows={14} cols={8} />;
  if (q.error) return <ErrorState error={q.error} />;
  const report = q.data?.data;
  if (!report || report.rows.length === 0) return <EmptyState title={t("truth.register.empty")} />;
  return (
    <Panel
      title={t("truth.register.title")}
      subtitle={t("truth.register.subtitle", {
        version: report.dataset_version ?? "—",
        status: report.dataset_version_status ?? "—",
        when: formatRelative(report.measured_at),
      })}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH>{t("truth.register.dataset")}</TH>
          <TH>{t("truth.register.class")}</TH>
          <TH>{t("truth.register.model")}</TH>
          <TH>{t("truth.register.endpoint")}</TH>
          <TH>{t("truth.register.capture")}</TH>
          <TH align="right">{t("truth.register.rows")}</TH>
          <TH align="right">{t("truth.register.coverage")}</TH>
          <TH align="right">{t("truth.register.errors")}</TH>
          <TH>{t("truth.register.blockers")}</TH>
        </THead>
        <tbody data-testid="dataset-register">
          {report.rows.map((r) => (
            <TRow key={r.dataset}>
              <TD>
                <div className="text-sm font-medium">
                  {translateOr(`truth.datasets.${r.dataset}`, r.dataset)}
                </div>
                <div className="max-w-[16rem] text-caption text-subtle-foreground">
                  {translateOr(`truth.sla.${r.dataset}`, r.sla)}
                </div>
              </TD>
              <TD>
                <StatusBadge tone={CLASS_TONE[r.klass]}>
                  {t(`truth.register.classes.${r.klass}`)}
                </StatusBadge>
              </TD>
              <TD>
                <span title={r.model_reason}>
                  <StatusBadge tone={MODEL_TONE[r.model]} dot={false}>
                    {t(`truth.register.models.${r.model}`)}
                  </StatusBadge>
                </span>
                <div className="mt-1 text-caption text-subtle-foreground">
                  {translateOr(`truth.role.${r.role}`, r.role)}
                </div>
              </TD>
              <TD className="max-w-[12rem] text-xs text-muted-foreground">
                {r.endpoints.join(" · ")}
              </TD>
              <TD className="text-xs">
                <div>
                  {t("truth.register.captured")}{" "}
                  {r.last_capture ? formatRelative(r.last_capture) : "—"}
                </div>
                <div className="text-caption text-subtle-foreground">
                  {t("truth.register.written")} {r.last_write ? formatRelative(r.last_write) : "—"}
                </div>
              </TD>
              <TD align="right" className="numeric text-xs">
                {localInt(r.rows)}
              </TD>
              <TD align="right" className="text-xs">
                <div className="numeric">{r.coverage === null ? "—" : localPct(r.coverage, 0)}</div>
                {r.provider_gap ? (
                  <div className="text-caption text-subtle-foreground">
                    {t("truth.register.gap", { share: localPct(r.provider_gap, 0) })}
                  </div>
                ) : null}
              </TD>
              <TD align="right" className="numeric text-xs">
                {localInt(r.errors_24h)}
                {r.failed_runs_24h ? (
                  <div className="text-caption text-subtle-foreground">
                    {t("truth.register.badRuns", { n: localInt(r.failed_runs_24h) })}
                  </div>
                ) : null}
              </TD>
              <TD className="max-w-[18rem] text-xs">
                {r.blockers.length ? (
                  <ul className="list-disc space-y-0.5 pl-4">
                    {r.blockers.map((b) => (
                      <li key={b}>{b}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-subtle-foreground">—</span>
                )}
                {r.notes.map((n) => (
                  <div key={n} className="mt-1 text-caption text-subtle-foreground">
                    {n}
                  </div>
                ))}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
      <p className="px-4 py-3 text-caption text-subtle-foreground">{t("truth.register.legend")}</p>
    </Panel>
  );
}
