/** Sign-ins and account changes. The API never stores a password or a token here. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { live } from "@/lib/api/v1/queries";
import { t, translateOr } from "@/lib/i18n";
import { formatDateTime, formatRelative } from "@/lib/time";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { cn } from "@/lib/utils";

const ACTIONS = [
  "login.succeeded",
  "login.failed",
  "login.refused",
  "logout",
  "user.created",
  "user.role_changed",
  "user.status_changed",
  "password.changed",
  "password.change_refused",
  "password.reset",
  "preferences.updated",
];

/** Catalog keys cannot contain dots (they are paths): "user.role_changed" -> "user_role_changed". */
function actionLabel(action: string): string {
  return translateOr(`admin.audit.actions.${action.replace(/\./g, "_")}`, action);
}

const TONE: Record<string, string> = {
  "login.failed": "text-negative",
  "login.refused": "text-negative",
  "password.change_refused": "text-negative",
  "user.role_changed": "text-gold",
  "user.status_changed": "text-warning",
};

function detailText(detail: Record<string, unknown>): string {
  const parts = Object.entries(detail).map(
    ([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`,
  );
  return parts.join(" · ");
}

export function AuditPage() {
  const [action, setAction] = useState<string>("");
  const q = useQuery({ ...live.authAudit(action || undefined) });
  const events = q.data?.data ?? [];
  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.audit.title")}
        description={t("admin.pages.audit.description")}
        actions={
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            {t("admin.audit.filter")}
            <select
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="h-8 rounded-md border border-input bg-background px-2 text-xs"
            >
              <option value="">{t("admin.audit.allActions")}</option>
              {ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {actionLabel(a)}
                </option>
              ))}
            </select>
          </label>
        }
      />
      <Card className="overflow-hidden">
        {q.isPending ? (
          <SkeletonCards className="p-4" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : events.length === 0 ? (
          <EmptyState title={t("common.noData")} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm" data-testid="audit-table">
              <thead className="text-left text-caption uppercase tracking-wider text-subtle-foreground">
                <tr className="border-b border-border">
                  <th className="px-4 py-2 font-medium">{t("admin.audit.when")}</th>
                  <th className="px-3 py-2 font-medium">{t("admin.audit.action")}</th>
                  <th className="px-3 py-2 font-medium">{t("admin.audit.actor")}</th>
                  <th className="px-3 py-2 font-medium">{t("admin.audit.target")}</th>
                  <th className="px-3 py-2 font-medium">{t("admin.audit.detail")}</th>
                  <th className="px-3 py-2 font-medium">{t("admin.audit.ip")}</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} className="border-b border-border/60 last:border-0">
                    <td className="numeric px-4 py-2 text-xs" title={formatDateTime(e.at)}>
                      {formatRelative(e.at)}
                    </td>
                    <td className={cn("px-3 py-2 text-xs font-medium", TONE[e.action])}>
                      {actionLabel(e.action)}
                    </td>
                    <td className="px-3 py-2 text-xs">{e.actor_email ?? "—"}</td>
                    <td className="px-3 py-2 text-xs">{e.target_email ?? e.email ?? "—"}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {detailText(e.detail)}
                    </td>
                    <td className="numeric px-3 py-2 text-xs text-subtle-foreground">
                      {e.ip ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
