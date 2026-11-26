/** «Avisos» (plan maestro UX/UI 2026, decision 1): the bell's figure and what keeps it true. */
import { useQuery } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { InboxItem } from "@/lib/api/v1/types_inbox";

export const INBOX_UNREAD_KEY = ["me", "inbox", "unread"] as const;

/** A link of a notice is a path of PrediGol: `/matches/7#postmatch` -> its path and its hash. Anything else: Inicio. */
export function noticeTarget(url: string): { path: string; hash?: string } {
  if (!url.startsWith("/") || url.startsWith("//")) return { path: "/home" };
  const [withQuery, hash] = url.split("#");
  const path = (withQuery ?? "").split("?")[0] || "/home";
  return hash ? { path, hash } : { path };
}

/** How the bell writes its figure: nothing at zero, «9+» beyond nine. */
export function bellFigure(unread: number): string | null {
  if (unread <= 0) return null;
  return unread > 9 ? "9+" : String(unread);
}

/** The unread count, only while the inbox is open to this account (FBI_INBOX); read again every two minutes. */
export function useInboxUnread(): { open: boolean; unread: number } {
  const open = useAuth().user?.inbox === true;
  const q = useQuery({
    queryKey: INBOX_UNREAD_KEY,
    queryFn: v1.inboxUnread,
    enabled: open,
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
  return { open, unread: open ? (q.data?.unread ?? 0) : 0 };
}

export type NoticeDay = "today" | "yesterday" | "week" | "earlier";

/** The calendar day (reader's local time) a moment falls on, as a number of days: two moments of one day give the same figure. */
function dayNumber(at: Date): number {
  return Math.floor(Date.UTC(at.getFullYear(), at.getMonth(), at.getDate()) / 86_400_000);
}

/** Which group of the list a notice belongs to: Hoy · Ayer · Esta semana (the six days before yesterday) · Antes. A date that cannot be read goes to «Antes». */
export function noticeDay(at: string, now: Date = new Date()): NoticeDay {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return "earlier";
  const ago = dayNumber(now) - dayNumber(d);
  if (ago <= 0) return "today"; // a notice stamped a few seconds ahead is still today
  if (ago === 1) return "yesterday";
  if (ago <= 7) return "week";
  return "earlier";
}

const ORDER: readonly NoticeDay[] = ["today", "yesterday", "week", "earlier"];

/** The list grouped by day, groups in that order, each one in the order the server sent (newest first); an empty group is left out. */
export function groupByDay(
  items: readonly InboxItem[],
  now: Date = new Date(),
): { day: NoticeDay; items: InboxItem[] }[] {
  const by = new Map<NoticeDay, InboxItem[]>();
  for (const item of items) {
    const d = noticeDay(item.at, now);
    by.set(d, [...(by.get(d) ?? []), item]);
  }
  return ORDER.filter((d) => by.has(d)).map((day) => ({ day, items: by.get(day)! }));
}
