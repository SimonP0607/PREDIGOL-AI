/**
 * Clientes (/admin/customers, plan UX, B10): every reader with what is needed to attend and renew them. Six views say who
 * needs attention - their cover ends within 7 days, 14 days unseen, an open ticket, an error in the last 24 hours, at risk or invited and
 * never activated (the lifecycle, B11) - with
 * how many each holds; a search by address or alias; a table from xl and a card per reader below. Each row opens the
 * reader's card. Only the owner reaches it; the list holds no IP, no token and no loose click.
 */
import { useDeferredValue, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { RefreshCw, Search } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { v1 } from "@/lib/api/v1/client";
import { CUSTOMER_VIEWS, type CustomerRow, type CustomerView } from "@/lib/api/v1/types_customers";
import { t } from "@/lib/i18n";
import { formatDateYear, formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { LifecycleBadge, MembershipBadge } from "./CustomerParts";

const PAGE = 50;

function Flags({ row }: { row: CustomerRow }) {
  return (
    <span className="flex flex-wrap gap-1.5">
      {row.open_tickets > 0 ? (
        <span className="rounded-full border border-warning/40 px-1.5 py-0.5 text-[0.65rem] font-semibold text-warning">
          {t("admin.customers.ticketsFlag", { count: row.open_tickets })}
        </span>
      ) : null}
      {row.errors_24h > 0 ? (
        <span className="rounded-full border border-negative/40 px-1.5 py-0.5 text-[0.65rem] font-semibold text-negative">
          {t("admin.customers.errorsFlag", { count: row.errors_24h })}
        </span>
      ) : null}
      {row.status !== "active" ? (
        <span className="rounded-full border border-border-strong px-1.5 py-0.5 text-[0.65rem] font-semibold text-muted-foreground">
          {t(`admin.customers.status.${row.status}`)}
        </span>
      ) : null}
    </span>
  );
}

function SeenCell({ row }: { row: CustomerRow }) {
  return (
    <span className="numeric text-xs text-muted-foreground">
      {row.last_seen_at ? formatRelative(row.last_seen_at) : t("admin.users.never")}
    </span>
  );
}

export function CustomersPage() {
  const [view, setView] = useState<CustomerView>("all");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const needle = useDeferredValue(search.trim());
  const q = useQuery({
    queryKey: ["v1", "admin", "customers", view, needle, offset],
    queryFn: () => v1.customers({ view, limit: PAGE, offset, ...(needle ? { q: needle } : {}) }),
    placeholderData: keepPreviousData,
  });
  const data = q.data;
  const counts = new Map(data?.views.map((v) => [v.view, v.count]));
  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.customers.title")}
        description={t("admin.pages.customers.description")}
        actions={
          <button
            type="button"
            onClick={() => void q.refetch()}
            aria-label={t("common.retry")}
            className="tap relative rounded-md border border-border-strong p-2 hover:bg-elevated"
          >
            <RefreshCw aria-hidden className={cn("h-4 w-4", q.isFetching && "animate-spin")} />
          </button>
        }
      />
      <div
        className="flex flex-wrap items-center gap-2"
        role="tablist"
        data-testid="customer-views"
      >
        {CUSTOMER_VIEWS.map((v) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={view === v}
            data-testid={`customer-view-${v}`}
            onClick={() => {
              setView(v);
              setOffset(0);
            }}
            className={cn(
              "tap-y relative inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium pointer-coarse:py-2.5",
              view === v
                ? "border-primary bg-primary/10 text-foreground"
                : "border-border-strong text-muted-foreground hover:bg-elevated",
            )}
          >
            {t(`admin.customers.views.${v}`)}
            <span className="numeric font-semibold" data-testid={`customer-count-${v}`}>
              {counts.get(v) ?? "·"}
            </span>
          </button>
        ))}
      </div>
      <label className="relative block max-w-md">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <input
          type="search"
          value={search}
          data-testid="customer-search"
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
          placeholder={t("admin.customers.search")}
          aria-label={t("admin.customers.search")}
          className="h-10 w-full rounded-md border border-input bg-background pl-9 pr-3 text-base focus:border-primary focus:outline-none sm:text-sm"
        />
      </label>
      <Card className="overflow-hidden">
        {q.isPending ? (
          <SkeletonCards className="p-4" />
        ) : q.isError && !data ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState title={t("admin.customers.empty")} />
        ) : (
          <>
            <div className="border-b border-border px-4 py-2 text-caption text-muted-foreground">
              {t("admin.customers.shown", {
                from: data.offset + 1,
                to: data.offset + data.items.length,
                total: data.total,
              })}
            </div>
            <div className="hidden overflow-x-auto xl:block">
              <table className="w-full text-sm" data-testid="customers-table">
                <thead className="text-left text-caption uppercase tracking-wider text-subtle-foreground">
                  <tr className="border-b border-border">
                    <th className="px-4 py-2 font-medium">{t("admin.customers.customer")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.membership.column")}</th>
                    <th className="px-3 py-2 font-medium">
                      {t("admin.customers.lifecycle.column")}
                    </th>
                    <th className="px-3 py-2 font-medium">{t("admin.customers.lastSeen")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.customers.activeDays")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.customers.csat")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.customers.attention")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.created")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr
                      key={r.id}
                      className="border-b border-border/60 last:border-0"
                      data-testid={`customer-row-${r.id}`}
                    >
                      <td className="px-4 py-3">
                        <Link
                          to="/admin/customers/$userId"
                          params={{ userId: String(r.id) }}
                          className="tap-y relative font-medium text-primary hover:underline"
                        >
                          {r.display_name ?? r.email}
                        </Link>
                        <div className="text-caption text-muted-foreground">{r.email}</div>
                      </td>
                      <td className="px-3 py-3">
                        <MembershipBadge membership={r.membership} />
                      </td>
                      <td className="px-3 py-3">
                        <LifecycleBadge state={r.lifecycle} reasons={r.lifecycle_reasons} />
                      </td>
                      <td className="px-3 py-3">
                        <SeenCell row={r} />
                      </td>
                      <td className="numeric px-3 py-3 text-xs">{r.active_days_7}/7</td>
                      <td className="numeric px-3 py-3 text-xs">{r.last_csat ?? "—"}</td>
                      <td className="px-3 py-3">
                        <Flags row={r} />
                      </td>
                      <td className="numeric px-3 py-3 text-xs text-muted-foreground">
                        {formatDateYear(r.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul
              className="divide-y divide-border md:grid md:grid-cols-2 md:gap-px md:divide-y-0 md:bg-border xl:hidden"
              data-testid="customers-cards"
            >
              {data.items.map((r) => (
                <li
                  key={r.id}
                  className="space-y-2 bg-card p-4"
                  data-testid={`customer-card-${r.id}`}
                >
                  <Link
                    to="/admin/customers/$userId"
                    params={{ userId: String(r.id) }}
                    className="tap-y relative block break-words font-medium text-primary hover:underline"
                  >
                    {r.display_name ?? r.email}
                  </Link>
                  <div className="break-all text-caption text-muted-foreground">{r.email}</div>
                  <MembershipBadge membership={r.membership} />
                  <LifecycleBadge state={r.lifecycle} reasons={r.lifecycle_reasons} />
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>
                      {t("admin.customers.lastSeen")}: <SeenCell row={r} />
                    </span>
                    <span>
                      {t("admin.customers.activeDays")}: {r.active_days_7}/7
                    </span>
                    <span>
                      {t("admin.users.created")}: {formatDateYear(r.created_at)}
                    </span>
                  </div>
                  <Flags row={r} />
                </li>
              ))}
            </ul>
            {data.total > PAGE ? (
              <div className="flex items-center justify-between gap-2 border-t border-border px-4 py-2">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE))}
                  data-testid="customers-prev"
                  className="tap-y relative rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium disabled:opacity-50"
                >
                  {t("admin.customers.previous")}
                </button>
                <button
                  type="button"
                  disabled={offset + PAGE >= data.total}
                  onClick={() => setOffset(offset + PAGE)}
                  data-testid="customers-next"
                  className="tap-y relative rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium disabled:opacity-50"
                >
                  {t("admin.customers.next")}
                </button>
              </div>
            ) : null}
          </>
        )}
      </Card>
    </div>
  );
}
