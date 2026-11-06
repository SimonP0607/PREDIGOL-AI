/**
 * The owner's banners (closing plan 4.3): which of the ones in force a reader sees, in their language, and which they
 * closed. A reader closes a banner for themselves only (per id, on this browser): the next communiqué shows again.
 */
import type { Locale } from "@/lib/i18n/catalogs";
import type { AnnouncementKind, PublicNotice } from "@/lib/api/v1/types_announcements";

export const DISMISSED_KEY = "predigol.notices.closed";
const KEEP = 30;

/** The most urgent first, as the server orders them; a stable sort keeps its order inside a kind. */
const RANK: Readonly<Record<AnnouncementKind, number>> = {
  incident: 0,
  maintenance: 1,
  update: 2,
  general: 3,
};

export interface ShownNotice {
  id: number;
  kind: AnnouncementKind;
  critical: boolean;
  title: string;
  body: string;
  until: string;
}

export function readClosed(): number[] {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((n): n is number => Number.isInteger(n)) : [];
  } catch {
    return [];
  }
}

export function rememberClosed(id: number, closed: readonly number[] = readClosed()): number[] {
  const next = [...closed.filter((n) => n !== id), id].slice(-KEEP);
  try {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: it closes for this visit only */
  }
  return next;
}

/** The banners in force now and not closed, in the reader's language. The server already filtered by date; this guards a stale cache. */
export function visibleNotices(
  notices: readonly PublicNotice[],
  closed: readonly number[],
  locale: Locale,
  now: number = Date.now(),
): ShownNotice[] {
  return [...notices]
    .filter(
      (n) =>
        !closed.includes(n.id) && Date.parse(n.starts_at) <= now && Date.parse(n.ends_at) > now,
    )
    .sort((a, b) => RANK[a.kind] - RANK[b.kind])
    .map((n) => ({
      id: n.id,
      kind: n.kind,
      critical: n.critical,
      title: locale === "en" ? n.title_en : n.title_es,
      body: locale === "en" ? n.body_en : n.body_es,
      until: n.ends_at,
    }));
}
