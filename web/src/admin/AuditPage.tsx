/** Sign-ins and account changes. The API never stores a password or a token here. */
import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { live } from "@/lib/api/v1/queries";
import { t, translateOr } from "@/lib/i18n";
import { dayBounds, formatDateTime, formatRelative, todayKey } from "@/lib/time";
import { Segmented } from "@/components/ui/segmented";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { cn } from "@/lib/utils";
import { detailText } from "./auditDetail";

/** The kinds the console always lists; the trail adds every other kind it holds (plan UX, B10). */
const KNOWN_ACTIONS = [
  "login.succeeded",
  "login.password_ok",
  "login.failed",
  "login.refused",
  "login.locked",
  "logout",
  "mfa.verified",
  "mfa.failed",
  "mfa.enrolled",
  "mfa.recovery_code_used",
  "mfa.reset",
  "mfa.disabled",
  "user.created",
  "user.role_changed",
  "user.status_changed",
  "user.unlocked",
  "user.mfa_requirement_changed",
  "password.changed",
  "password.change_refused",
  "password.reset",
  "session.revoked",
  "preferences.updated",
  "admin.write",
];

/** Catalog keys cannot contain dots (they are paths): "user.role_changed" -> "user_role_changed". */
function actionLabel(action: string): string {
  return translateOr(`admin.audit.actions.${action.replace(/\./g, "_")}`, action);
}

const TONE: Record<string, string> = {
  "login.failed": "text-negative",
  "login.refused": "text-negative",
  "login.locked": "text-negative",
  "mfa.failed": "text-negative",
  "password.change_refused": "text-negative",
  "user.role_changed": "text-gold",
  "user.status_changed": "text-warning",
  "mfa.reset": "text-warning",
  "password.reset": "text-warning",
};

const FAMILIES = ["all", "access", "accounts", "membership", "console"] as const;
type FamilyChoice = (typeof FAMILIES)[number];

/** «Hoy en cifras» (decision 12): which actions each figure adds up. Counted from the trail's own rows of today. */
export const TODAY_FIGURES: ReadonlyArray<{
  key: string;
  actions: readonly string[];
  tone?: string;
}> = [
  { key: "logins", actions: ["login.succeeded"] },
  { key: "failed", actions: ["login.failed", "login.refused"], tone: "text-negative" },
  { key: "locked", actions: ["login.locked"], tone: "text-warning" },
  { key: "console", actions: ["admin.write"] },
  { key: "payments", actions: ["membership.payment_recorded"] },
];

export function sumOf(counts: ReadonlyMap<string, number>, actions: readonly string[]): number {
  return actions.reduce((n, a) => n + (counts.get(a) ?? 0), 0);
}

export function AuditPage() {
  const [action, setAction] = useState<string>("");
  const [family, setFamily] = useState<FamilyChoice>("all");
  const q = useInfiniteQuery({
    ...live.authAuditPages(action || undefined, family === "all" ? undefined : family),
  });
  // the reader's own midnight: what the page calls «hoy»
  const since = new Date(dayBounds(todayKey()).from).toISOString();
  const day = useQuery({ ...live.authAuditSince(since) });
  const counts = new Map((day.data?.data ?? []).map((a) => [a.action, a.count]));
  const locked = sumOf(counts, ["login.locked"]);
  const held = useQuery({ ...live.authAuditActions });
  const actions = [
    ...new Set([...KNOWN_ACTIONS, ...(held.data?.data ?? []).map((a) => a.action)]),
  ].sort();
  const events = q.data?.pages.flatMap((p) => p.data) ?? [];
  const total = q.data?.pages[0]?.meta.total ?? events.length;
  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.audit.title")}
        description={t("admin.pages.audit.description")}
        actions={
          // Wraps on a phone: the longest action's name made the select push the page 21 px sideways at 320 px.
          <label className="flex min-w-0 max-w-full flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {t("admin.audit.filter")}
            <select
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="h-8 min-w-0 max-w-full rounded-md border border-input bg-background px-2 text-xs"
            >
              <option value="">{t("admin.audit.allActions")}</option>
              {actions.map((a) => (
                <option key={a} value={a}>
                  {actionLabel(a)}
                </option>
              ))}
            </select>
          </label>
        }
      />
      <Segmented
        value={family}
        onChange={setFamily}
        label={t("admin.audit.families.label")}
        testId="audit-family"
        className="max-w-full"
        options={FAMILIES.map((f) => ({ value: f, label: t(`admin.audit.families.${f}`) }))}
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem] xl:items-start">
        <Card className="overflow-hidden">
          {q.isPending ? (
            <SkeletonCards className="p-4" />
          ) : q.isError ? (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          ) : events.length === 0 ? (
            <EmptyState title={t("common.noData")} />
          ) : (
            // beside «Hoy en cifras» the table scrolls sideways sooner: the keyboard must reach that scroll too
            <div
              className="overflow-x-auto focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
              role="region"
              aria-label={t("admin.pages.audit.title")}
              tabIndex={0}
            >
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
          {events.length > 0 ? (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2 text-caption text-muted-foreground">
              <span data-testid="audit-shown">
                {t("admin.audit.shown", { shown: events.length, total })}
              </span>
              {q.hasNextPage ? (
                <button
                  type="button"
                  data-testid="audit-more"
                  disabled={q.isFetchingNextPage}
                  onClick={() => void q.fetchNextPage()}
                  className="tap-y relative rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium disabled:opacity-50"
                >
                  {t("admin.audit.loadMore")}
                </button>
              ) : (
                <span>{t("admin.audit.allLoaded")}</span>
              )}
            </div>
          ) : null}
        </Card>
        <aside className="space-y-4">
          <Card className="p-4" data-testid="audit-today">
            <h2 className="text-title">{t("admin.audit.today.title")}</h2>
            <dl className="mt-2">
              {TODAY_FIGURES.map((f) => (
                <div
                  key={f.key}
                  className="flex items-baseline justify-between gap-3 border-b border-border/60 py-2 last:border-0"
                >
                  <dt className="text-[0.8125rem] text-muted-foreground">
                    {t(`admin.audit.today.${f.key}`)}
                  </dt>
                  <dd
                    // a colour only when there is something to look at: a zero is not an alarm
                    className={cn(
                      "numeric text-[0.9375rem] font-bold",
                      sumOf(counts, f.actions) > 0 && f.tone,
                    )}
                    data-testid={`audit-today-${f.key}`}
                  >
                    {day.data ? sumOf(counts, f.actions) : "—"}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-caption text-muted-foreground">{t("admin.audit.today.note")}</p>
          </Card>
          <Card className="p-4" data-testid="audit-watch">
            <h2 className="text-title">{t("admin.audit.watch.title")}</h2>
            {locked > 0 ? (
              <>
                <p className="mt-2 text-[0.8125rem] leading-snug text-foreground-soft">
                  {t("admin.audit.watch.locked", { count: locked })}
                </p>
                <button
                  type="button"
                  data-testid="audit-watch-locked"
                  onClick={() => {
                    setFamily("all");
                    setAction("login.locked");
                  }}
                  className="tap-y relative mt-2 text-[0.8125rem] font-semibold text-primary hover:underline"
                >
                  {t("admin.audit.watch.see")}
                </button>
              </>
            ) : (
              <p className="mt-2 text-[0.8125rem] text-muted-foreground">
                {day.data ? t("admin.audit.watch.none") : "—"}
              </p>
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}
