/**
 * «Avisos» (plan maestro UX/UI 2026, decision 1; sheet I05): what PrediGol told this reader in the last 30 days - the
 * result of what they saved, the line-ups of their teams, the day's summary, the reminders they asked for, their account -
 * whether a device received it or not. Filters Todos · Picks · Partidos · Cuenta; «Marcar leídos»; a notice opens its page
 * and is read. Only category, title, text, link and date are kept of a notice. GET /me/inbox, behind FBI_INBOX.
 */
import { useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Bell, CalendarClock, CheckCheck, ListChecks, ShieldCheck, Trophy } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { v1 } from "@/lib/api/v1/client";
import type { InboxCategory, InboxFilter, InboxItem } from "@/lib/api/v1/types_inbox";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, PageTitle, SkeletonCards } from "@/product/shared/States";
import { INBOX_UNREAD_KEY, noticeTarget } from "./inbox";

const FILTERS: readonly InboxFilter[] = ["all", "picks", "matches", "account"];

const ICON: Record<InboxCategory, typeof Bell> = {
  result: Trophy,
  digest: ListChecks,
  lineup: CalendarClock,
  reminder: Bell,
  account: ShieldCheck,
};

function Notice({ item, onOpen }: { item: InboxItem; onOpen: (id: number) => void }) {
  const Icon = ICON[item.category];
  const target = noticeTarget(item.url);
  return (
    <li data-testid="inbox-item" data-read={item.read} data-category={item.category}>
      <Link
        to={target.path as never}
        {...(target.hash ? { hash: target.hash } : {})}
        onClick={() => (item.read ? undefined : onOpen(item.id))}
        className={cn(
          "flex items-start gap-3 px-4 py-3.5 transition-colors hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          !item.read && "bg-primary/[0.04]",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
            item.read ? "bg-elevated text-muted-foreground" : "bg-primary-soft text-primary",
          )}
        >
          <Icon className="h-[1.125rem] w-[1.125rem]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-3">
            <span className={cn("text-sm", item.read ? "font-medium" : "font-semibold")}>
              {item.title}
            </span>
            <span className="numeric shrink-0 text-xs text-muted-foreground">
              {formatRelative(item.at)}
            </span>
          </span>
          <span className="mt-0.5 block text-[0.8125rem] leading-snug text-muted-foreground">
            {item.body}
          </span>
          <span className="mt-1 block text-xs text-subtle-foreground">
            {t(`push.inbox.category.${item.category}`)}
            {item.read ? null : <span className="sr-only"> · {t("push.inbox.unreadMark")}</span>}
          </span>
        </span>
        {item.read ? null : (
          <span aria-hidden className="mt-2 h-2 w-2 shrink-0 rounded-full bg-primary" />
        )}
      </Link>
    </li>
  );
}

export function InboxPage() {
  const open = useAuth().user?.inbox === true;
  const qc = useQueryClient();
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [busy, setBusy] = useState(false);
  const q = useInfiniteQuery({
    queryKey: ["me", "inbox", "list", filter],
    queryFn: ({ pageParam }) => v1.inbox(filter, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
    enabled: open,
    staleTime: 30_000,
  });
  const items = (q.data?.pages ?? []).flatMap((p) => p.items);
  const unread = q.data?.pages[0]?.unread ?? 0;

  async function markRead(ids?: number[]) {
    try {
      const left = await v1.markInboxRead(ids);
      qc.setQueryData(INBOX_UNREAD_KEY, left);
      await qc.invalidateQueries({ queryKey: ["me", "inbox", "list"] });
    } catch {
      // the next visit tries again: a notice left unread is never a lost one
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4" data-testid="inbox">
      <PageTitle title={t("push.inbox.title")} subtitle={t("push.inbox.subtitle")} />
      {!open ? (
        <EmptyState
          icon={<Bell aria-hidden className="h-6 w-6" />}
          title={t("push.inbox.closed")}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div
              role="radiogroup"
              aria-label={t("push.inbox.filterLabel")}
              className="scroll-strip -mx-1 flex min-w-0 gap-2 px-1 py-1"
              data-testid="inbox-filters"
            >
              {FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  role="radio"
                  aria-checked={filter === f}
                  onClick={() => setFilter(f)}
                  data-testid={`inbox-filter-${f}`}
                  className={cn(
                    "tap-y relative inline-flex h-9 shrink-0 items-center whitespace-nowrap rounded-full border px-3.5 text-[0.8125rem] font-semibold leading-none transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                    filter === f
                      ? "border-primary/40 bg-primary-soft text-primary"
                      : "border-transparent bg-elevated text-foreground-soft hover:text-foreground",
                  )}
                >
                  {t(`push.inbox.filter.${f}`)}
                </button>
              ))}
            </div>
            {unread > 0 ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  void markRead().finally(() => setBusy(false));
                }}
                data-testid="inbox-read-all"
                className={buttonVariants({ variant: "text", size: "sm" })}
              >
                <CheckCheck aria-hidden />
                {t("push.inbox.readAll")}
              </button>
            ) : null}
          </div>
          {q.isPending ? (
            <SkeletonCards count={3} />
          ) : q.isError ? (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<Bell aria-hidden className="h-6 w-6" />}
              title={t(filter === "all" ? "push.inbox.empty" : "push.inbox.emptyFilter")}
              body={t("push.inbox.emptyBody")}
            />
          ) : (
            <>
              <ul
                className="card-surface divide-y divide-border overflow-hidden rounded-card"
                data-testid="inbox-list"
              >
                {items.map((item) => (
                  <Notice key={item.id} item={item} onOpen={(id) => void markRead([id])} />
                ))}
              </ul>
              {q.hasNextPage ? (
                <button
                  type="button"
                  onClick={() => void q.fetchNextPage()}
                  disabled={q.isFetchingNextPage}
                  data-testid="inbox-more"
                  className={buttonVariants({ variant: "secondary", block: true })}
                >
                  {t("push.inbox.more")}
                </button>
              ) : null}
            </>
          )}
          <p className="text-caption text-subtle-foreground">
            {t("push.inbox.note")}{" "}
            <Link
              to="/profile"
              hash="notifications"
              className="font-medium text-primary underline-offset-2 hover:underline"
            >
              {t("push.inbox.toSettings")}
            </Link>
          </p>
        </>
      )}
    </div>
  );
}
