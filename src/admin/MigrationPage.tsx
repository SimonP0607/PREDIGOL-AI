/** Historical backfill: the plan and the seeded tasks, apart from the System page's other panels. */
import { PageHeader } from "@/components/layout/PageHeader";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { live } from "@/lib/api/v1/queries";
import { t } from "@/lib/i18n";
import { BackfillPanel } from "@/live/AdminLive";
import { MigrationTab } from "@/live/AnalyticsLive";

export function MigrationPage() {
  const q = useLiveQuery(live.admin);
  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.migration.title")}
        description={t("admin.pages.migration.description")}
      />
      {q.isPending ? (
        <TableSkeleton rows={5} cols={6} />
      ) : q.isError ? (
        <ApiErrorNotice error={q.error} />
      ) : (
        <BackfillPanel section={q.data.data.migration} />
      )}
      <MigrationTab />
    </div>
  );
}
