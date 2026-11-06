/** The owner's communiqués (closing plan 4.3; fbi.api.contracts.announcements). */

export type AnnouncementKind = "maintenance" | "incident" | "update" | "general";
export type AnnouncementStatus = "draft" | "published" | "retracted";

export interface AnnouncementIn {
  kind: AnnouncementKind;
  title_es: string;
  title_en: string;
  body_es: string;
  body_en: string;
  starts_at: string;
  ends_at: string;
  to_banner: boolean;
  to_updates: boolean;
  to_telegram: boolean;
  to_email: boolean;
  critical: boolean;
}

export interface Announcement extends AnnouncementIn {
  id: number;
  status: AnnouncementStatus;
  created_at: string;
  published_at: string | null;
  retracted_at: string | null;
}

export interface AnnouncementList {
  telegram_configured: boolean;
  daily_cap: number;
  published_today: number;
  items: Announcement[];
}

export interface AnnouncementLogLine {
  action: string;
  actor_user_id: number | null;
  detail: Record<string, unknown>;
  at: string;
}

/** What each destination will say; ``code`` is shown once and lives ten minutes. */
export interface AnnouncementPreview {
  id: number;
  code: string;
  expires_at: string;
  destinations: {
    banner?: { from: string; until: string };
    updates?: { es: string; en: string };
    telegram?: { title: string; body: string; configured: boolean };
    email?: { recipients: number; critical: boolean };
  };
  published_today: number;
  daily_cap: number;
}

export interface AnnouncementPublished {
  id: number;
  emails_queued: number;
  telegram: "sent" | "failed" | "not_configured" | "not_requested";
}

export interface PublicNotice {
  id: number;
  kind: AnnouncementKind;
  title_es: string;
  title_en: string;
  body_es: string;
  body_en: string;
  starts_at: string;
  ends_at: string;
  critical: boolean;
}

export interface PublicUpdate {
  id: number;
  title_es: string;
  title_en: string;
  body_es: string;
  body_en: string;
  starts_at: string;
}

export interface ActiveAnnouncements {
  banners: PublicNotice[];
  updates: PublicUpdate[];
}
