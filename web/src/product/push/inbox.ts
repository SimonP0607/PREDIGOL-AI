/** «Avisos» (plan maestro UX/UI 2026, decision 1): the bell's figure and what keeps it true. */
import { useQuery } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import { useAuth } from "@/lib/auth/AuthProvider";

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
