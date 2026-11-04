/**
 * The readers' notices on their devices (plan UX, B7; section 34): whether they can be offered, the browsers a reader
 * allowed, the categories, the bell of a match, and the owner's counts in /admin/product. Mirrors
 * backend/src/fbi/api/contracts/push.py. A device never comes back with its push service's address nor its keys.
 */
import type { Iso } from "./types";

export type PushFamily = "chrome" | "firefox" | "safari" | "edge" | "other";
export type PushSystem = "android" | "ios" | "windows" | "macos" | "linux" | "other";
/** What a reader can switch off. The bell's reminders exist only when they ring it. */
export type PushCategory = "result" | "lineup" | "digest" | "account";
export type NoticeCategory = PushCategory | "reminder" | "test";

export interface PushDevice {
  id: number;
  family: PushFamily;
  system: PushSystem;
  /** Subscribed from the installed app (an iPhone needs it). */
  installed: boolean;
  created_at: Iso;
  /** The last notice its push service took. */
  last_ok_at: Iso | null;
}

export type PushCategories = Record<PushCategory, boolean>;

export interface PushState {
  /** FBI_PUSH on and PrediGol's VAPID key set (P12): false hides every invitation. */
  available: boolean;
  /** The application server key the browser subscribes with (base64url). */
  public_key: string | null;
  devices: PushDevice[];
  categories: PushCategories;
  /** The quiet hours, in the reader's zone ("22:00", "08:00"): what falls inside waits. */
  quiet_start: string;
  quiet_end: string;
  /** At most this many results, line-ups and summaries a day. */
  daily_cap: number;
}

/** PushSubscription.toJSON() of the browser, with what the page knows of it. */
export interface PushSubscribeIn {
  endpoint: string;
  keys: { p256dh: string; auth: string };
  family: PushFamily;
  system: PushSystem;
  installed: boolean;
}

/** This browser (its address) or another of the list (its id). */
export interface PushUnsubscribeIn {
  endpoint?: string | null;
  device_id?: number | null;
}

export type PushCategoriesIn = Partial<PushCategories>;

export type AlertMinutes = 15 | 30 | 60;

/** The bell of a match for this reader. */
export interface MatchAlert {
  fixture_id: number;
  on: boolean;
  minutes_before: AlertMinutes | null;
  kickoff_at: Iso | null;
}

export interface PushFamilyCount {
  family: PushFamily;
  system: PushSystem;
  devices: number;
}

export interface PushCategoryCount {
  category: NoticeCategory;
  sent: number;
  dropped: number;
}

/** The owner's view: live devices and the last 7 days of notices - counts, never who. */
export interface PushOverview {
  available: boolean;
  /** Readers with at least one live device. */
  readers: number;
  devices: PushFamilyCount[];
  notices: PushCategoryCount[];
  /** Devices their push service dropped in the last 7 days (404/410). */
  gone: number;
}
