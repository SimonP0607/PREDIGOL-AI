/**
 * «Avisos» grouped by day (UX-250, decision C-02), pure. It lives apart from `inbox.ts` (which the bell in the top bar
 * loads on every visit) so the first visit's JS does not carry it (UX-139): only the page of Avisos imports it.
 */
import type { InboxItem } from "@/lib/api/v1/types_inbox";

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
