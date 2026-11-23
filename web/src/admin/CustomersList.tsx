/**
 * La lista de clientes (dentro de «Usuarios», plan AP-A03; antes /admin/customers, plan UX, B10): every reader with what is needed to attend and renew them. Six views say who
 * needs attention - their cover ends within 7 days, 14 days unseen, an open ticket, an error in the last 24 hours, at risk or invited and
 * never activated (the lifecycle, B11) - with
 * how many each holds; a search by address or alias; a table from xl and a card per reader below. Each row opens the
 * reader's card. Only the owner reaches it; the list holds no IP, no token and no loose click.
 */
import { useDeferredValue, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { CustomerRow, CustomerView } from "@/lib/api/v1/types_customers";
import { t } from "@/lib/i18n";
import { formatDateYear, formatRelative } from "@/lib/time";
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

export function CustomersList({ view }: { view: CustomerView }) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const needle = useDeferredValue(search.trim());
  const q = useQuery({
    queryKey: ["v1", "admin", "customers", view, needle, offset],
    queryFn: () => v1.customers({ view, limit: PAGE, offset, ...(needle ? { q: needle } : {}) }),
    placeholderData: keepPreviousData,
  });
  const data = q.data;
  // sheet AD3 (UX-151): from 1536 px, a customer's summary at the side of the list; the full card stays its own page
  const [picked, setPicked] = useState<number | null>(null);
  const side = data?.items.find((r) => r.id === picked) ?? null;
  return (
    <div className="space-y-5">
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
      <div className="2xl:grid 2xl:grid-cols-[minmax(0,1fr)_24rem] 2xl:items-start 2xl:gap-4">
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
                            to="/admin/users/$userId"
                            params={{ userId: String(r.id) }}
                            className="tap-y relative font-medium text-primary hover:underline"
                          >
                            {r.display_name ?? r.email}
                          </Link>
                          <div className="text-caption text-muted-foreground">{r.email}</div>
                          <button
                            type="button"
                            onClick={() => setPicked(r.id)}
                            aria-pressed={picked === r.id}
                            data-testid={`customer-peek-${r.id}`}
                            className="tap-y relative hidden text-caption font-semibold text-primary hover:underline 2xl:inline"
                          >
                            {t("admin.customers.peek")}
                          </button>
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
                      to="/admin/users/$userId"
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
        <aside
          className="hidden 2xl:sticky 2xl:top-20 2xl:block"
          aria-label={t("admin.customers.peekTitle")}
          data-testid="customer-side"
        >
          {side ? (
            <Card className="space-y-3 p-4">
              <div>
                <p className="break-words font-display text-base font-semibold">
                  {side.display_name ?? side.email}
                </p>
                <p className="break-all text-caption text-muted-foreground">{side.email}</p>
              </div>
              <MembershipBadge membership={side.membership} />
              <LifecycleBadge state={side.lifecycle} reasons={side.lifecycle_reasons} />
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <dt className="text-caption text-muted-foreground">
                    {t("admin.customers.lastSeen")}
                  </dt>
                  <dd>
                    <SeenCell row={side} />
                  </dd>
                </div>
                <div>
                  <dt className="text-caption text-muted-foreground">
                    {t("admin.customers.activeDays")}
                  </dt>
                  <dd className="numeric">{side.active_days_7}/7</dd>
                </div>
                <div>
                  <dt className="text-caption text-muted-foreground">
                    {t("admin.customers.csat")}
                  </dt>
                  <dd className="numeric">{side.last_csat ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-caption text-muted-foreground">{t("admin.users.created")}</dt>
                  <dd className="numeric">{formatDateYear(side.created_at)}</dd>
                </div>
              </dl>
              <Flags row={side} />
              <Link
                to="/admin/users/$userId"
                params={{ userId: String(side.id) }}
                className="inline-flex h-10 w-full items-center justify-center rounded-control border border-border text-sm font-semibold hover:bg-elevated"
              >
                {t("admin.customers.openCard")}
              </Link>
            </Card>
          ) : (
            <Card className="p-4 text-sm text-muted-foreground">
              {t("admin.customers.peekNone")}
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}
