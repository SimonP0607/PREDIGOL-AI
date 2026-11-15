/** «Avisos»: the reader's inbox (plan maestro UX/UI 2026, decision 1). Mirrors fbi.api.contracts.push (BE-041). */
import type { Iso } from "./types";

export type InboxFilter = "all" | "picks" | "matches" | "account";
export type InboxCategory = "result" | "lineup" | "digest" | "reminder" | "account";

export interface InboxItem {
  id: number;
  category: InboxCategory;
  title: string;
  body: string;
  /** The page of PrediGol it opens: a path. */
  url: string;
  at: Iso;
  read: boolean;
}

export interface Inbox {
  items: InboxItem[];
  total: number;
  /** Unread ones in all, whatever the filter: the bell's figure. */
  unread: number;
  next_offset: number | null;
}

export interface InboxUnread {
  unread: number;
}
