/**
 * The six answers per dataset (5 Oct 2026 mandate): valid, behind, not requested, the provider does not have it,
 * requested and failed, held but not normalised. Read from the dataset register (GET /admin/data/datasets), so the
 * Data Truth and Data Quality pages count the same things.
 */
import { useQuery } from "@tanstack/react-query";
import { Panel } from "@/components/primitives/Panel";
import { TableShell, TableSkeleton, TD, TH, THead, TRow } from "@/components/primitives/DataTable";
import { live } from "@/lib/api/v1/queries";
import { DATASET_STATES, type DatasetState } from "@/lib/api/v1/types_truth";
import { t, translateOr } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { EmptyState, ErrorState } from "@/product/shared/States";

/** How a non-zero count reads: green for valid, red for ours to fix, amber for gaps, muted for the provider's. */
const TONE: Record<DatasetState, string> = {
  VALID: "text-positive",
  STALE: "text-negative",
  NOT_REQUESTED: "text-warning",
  PROVIDER_HAS_NO_DATA: "text-muted-foreground",
  REQUEST_FAILED: "text-negative",
  NORMALIZATION_FAILED: "text-warning",
};

export function DatasetStatesPanel() {
  const q = useQuery({ ...live.datasets });
  if (q.isPending) return <TableSkeleton rows={14} cols={7} />;
  if (q.error) return <ErrorState error={q.error} />;
  const rows = q.data?.data?.rows ?? [];
  if (rows.length === 0) return <EmptyState title={t("system.dataQuality.states.empty")} />;
  return (
    <Panel
      title={t("system.dataQuality.states.title")}
      subtitle={t("system.dataQuality.states.subtitle")}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH>{t("system.dataQuality.states.dataset")}</TH>
          {DATASET_STATES.map((s) => (
            <TH key={s} align="right">
              {t(`system.dataQuality.states.headers.${s}`)}
            </TH>
          ))}
        </THead>
        <tbody data-testid="dataset-states">
          {rows.map((r) => (
            <TRow key={r.dataset}>
              <TD>
                <div className="text-sm font-medium">
                  {translateOr(`truth.datasets.${r.dataset}`, r.dataset)}
                </div>
                <div className="max-w-[16rem] text-caption text-subtle-foreground">
                  {r.freshness}
                </div>
              </TD>
              {DATASET_STATES.map((s) => {
                const n = r.states?.[s] ?? 0;
                return (
                  <TD key={s} align="right" className="numeric text-xs">
                    <span className={n > 0 ? TONE[s] : "text-subtle-foreground"}>
                      {localInt(n)}
                    </span>
                  </TD>
                );
              })}
            </TRow>
          ))}
        </tbody>
      </TableShell>
      <p className="px-4 py-3 text-caption text-subtle-foreground">
        {t("system.dataQuality.states.legend")}
      </p>
    </Panel>
  );
}
