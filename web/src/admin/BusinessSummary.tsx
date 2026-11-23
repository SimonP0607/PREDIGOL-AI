/**
 * The console's «Resumen» opens on what waits for the owner (plan maestro unificado, UX-151; sheet AD1): payment notices to
 * review, messages waiting for an answer, bookmakers with late prices, the customers to look at, the announcements of the
 * day and the latest of the audit trail - each a tile that leads to its page. It reads the console's own endpoints (the
 * same the pages below read, with their keys) and changes nothing: no payment, membership or permission is touched here.
 * The technical overview stays below it, as before.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  BellRing,
  ChevronRight,
  Coins,
  CreditCard,
  Inbox,
  Megaphone,
  ScrollText,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import { t } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";

function Tile({
  to,
  search,
  icon,
  value,
  title,
  note,
  alert,
  testId,
}: {
  to: string;
  search?: Record<string, string>;
  icon: ReactNode;
  value: number | null;
  title: string;
  note?: string | null;
  alert: boolean;
  testId: string;
}) {
  return (
    <Link
      to={to as never}
      {...(search ? { search: search as never } : {})}
      data-testid={testId}
      className={cn(
        "surface-panel flex min-h-32 flex-col gap-2 rounded-card p-4 transition-colors hover:bg-elevated",
        alert && "border-gold/60",
      )}
    >
      <span
        className={cn(
          "flex h-9 w-9 items-center justify-center rounded-field",
          alert ? "bg-gold-soft text-gold" : "bg-elevated text-muted-foreground",
        )}
      >
        {icon}
      </span>
      <span className="numeric font-display text-3xl font-bold leading-none">{value ?? "—"}</span>
      <span className="text-sm font-semibold">{title}</span>
      {note ? <span className="text-caption text-muted-foreground">{note}</span> : null}
    </Link>
  );
}

const VIEWS = ["expiring", "at_risk", "tickets", "errors"] as const;

export function BusinessSummary() {
  const payments = useQuery({
    queryKey: ["admin", "payment-requests", "submitted"],
    queryFn: () => v1.adminPaymentRequests("submitted"),
  });
  const support = useQuery({
    queryKey: ["admin", "support", "summary"],
    queryFn: () => v1.supportInbox({ status: "open" }),
  });
  const odds = useQuery(live.oddsStatus);
  const customers = useQuery({
    queryKey: ["v1", "admin", "customers", "summary"],
    queryFn: () => v1.customers({ limit: 1 }),
  });
  const news = useQuery({ queryKey: ["admin", "announcements"], queryFn: v1.announcements });
  const audit = useQuery(live.authAudit());
  const late = (odds.data?.data?.by_book ?? []).filter((b) => b.stale > 0);
  const counts = support.data?.counts;
  const views = new Map((customers.data?.views ?? []).map((v) => [v.view, v.count]));
  return (
    <section
      aria-labelledby="business-summary"
      className="space-y-4"
      data-testid="business-summary"
    >
      <h2 id="business-summary" className="text-title">
        {t("admin.summary.title")}
      </h2>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Tile
          to="/admin/payments"
          icon={<CreditCard aria-hidden className="h-5 w-5" />}
          value={payments.data?.waiting ?? null}
          title={t("admin.summary.payments")}
          alert={(payments.data?.waiting ?? 0) > 0}
          testId="summary-payments"
        />
        <Tile
          to="/admin/support"
          icon={<Inbox aria-hidden className="h-5 w-5" />}
          value={counts ? counts.waiting : null}
          title={t("admin.summary.messages")}
          note={
            counts
              ? t("admin.summary.messagesNote", { late: counts.late, urgent: counts.urgent })
              : null
          }
          alert={(counts?.late ?? 0) + (counts?.urgent ?? 0) > 0}
          testId="summary-messages"
        />
        <Tile
          to="/odds/status"
          icon={<Coins aria-hidden className="h-5 w-5" />}
          value={odds.data?.data?.by_book ? late.length : null}
          title={t("admin.summary.books")}
          note={
            late.length > 0
              ? late
                  .map((b) => b.name)
                  .slice(0, 3)
                  .join(" · ")
              : null
          }
          alert={late.length > 0}
          testId="summary-books"
        />
        <Tile
          to="/admin/users"
          search={{ view: "expiring" }}
          icon={<Users aria-hidden className="h-5 w-5" />}
          value={views.get("expiring") ?? null}
          title={t("admin.summary.expiring")}
          note={
            views.size
              ? t("admin.summary.expiringNote", {
                  risk: views.get("at_risk") ?? 0,
                  errors: views.get("errors") ?? 0,
                })
              : null
          }
          alert={(views.get("at_risk") ?? 0) > 0}
          testId="summary-customers"
        />
      </div>
      {views.size ? (
        <div className="flex flex-wrap gap-2" data-testid="summary-views">
          {VIEWS.map((v) => (
            <Link
              key={v}
              to="/admin/users"
              search={{ view: v }}
              className="inline-flex min-h-11 items-center gap-1.5 rounded-full border border-border px-3 text-sm hover:bg-elevated"
            >
              {t(`admin.summary.views.${v}`)}
              <span className="numeric font-semibold">{views.get(v) ?? 0}</span>
            </Link>
          ))}
        </div>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="surface-panel rounded-card p-4" data-testid="summary-announcements">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Megaphone aria-hidden className="h-4 w-4 text-subtle-foreground" />
            {t("admin.summary.announcements")}
          </h3>
          {news.data ? (
            <>
              <ul className="mt-2 divide-y divide-border">
                {news.data.items.slice(0, 3).map((a) => (
                  <li key={a.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                    <span className="min-w-0 truncate">
                      {a.title_es || a.title_en || `#${a.id}`}
                    </span>
                    <span className="shrink-0 text-caption text-muted-foreground">
                      {t(`admin.summary.state.${a.status}`)}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-caption text-muted-foreground">
                {t("admin.summary.today", {
                  n: news.data.published_today,
                  max: news.data.daily_cap,
                })}
              </p>
            </>
          ) : null}
          <Link
            to="/admin/announcements"
            className="mt-1 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-primary"
          >
            {t("admin.summary.open")} <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </div>
        <div className="surface-panel rounded-card p-4" data-testid="summary-activity">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <ScrollText aria-hidden className="h-4 w-4 text-subtle-foreground" />
            {t("admin.summary.activity")}
          </h3>
          <ul className="mt-2 divide-y divide-border">
            {(audit.data?.data ?? []).slice(0, 4).map((e) => (
              <li key={e.id} className="flex items-baseline gap-3 py-2 text-sm">
                <span className="numeric shrink-0 text-caption text-muted-foreground">
                  {formatTime(e.at)}
                </span>
                <span className="min-w-0 truncate">{e.action}</span>
              </li>
            ))}
          </ul>
          <Link
            to="/admin/audit"
            className="mt-1 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-primary"
          >
            {t("admin.summary.open")} <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>
      <p className="flex items-center gap-2 text-caption text-muted-foreground">
        <BellRing aria-hidden className="h-3.5 w-3.5" />
        {t("admin.summary.readOnly")}
      </p>
    </section>
  );
}
