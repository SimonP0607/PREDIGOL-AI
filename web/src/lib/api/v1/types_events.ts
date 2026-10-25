/**
 * Product analytics (plan UX, A6): the owner's view of the readers' events.
 * Mirrors backend/src/fbi/api/contracts/events.py.
 */

export interface UsageRow {
  name: string;
  group: string;
  events_7d: number;
  subjects_7d: number;
  events_30d: number;
  subjects_30d: number;
}

export interface FunnelStep {
  step: "activated" | "onboarding_started" | "onboarding_completed" | "first_value";
  subjects: number;
}

export interface ProductOverview {
  /** FBI_PRODUCT_EVENTS: off records nothing. */
  mode: "off" | "on" | "consent";
  /** FBI_EVENTS_PURGE: dry counts, on deletes (the owner's OK). */
  purge: "off" | "dry" | "on";
  /** Global figures need at least this many readers active in 30 days. */
  min_subjects: number;
  status: "ok" | "insufficient_data" | "empty";
  active_30d: number;
  /** Readers active today (d1), in 7 days (d7) and in 30 days (d30). */
  active: Record<string, number>;
  usage: UsageRow[];
  funnel: FunnelStep[];
  /** Sessions started in 7 days by device class. */
  devices: Record<string, number>;
  days_active_per_week: number | null;
  errors_per_active: number | null;
  /** Only from 100 readers active in 30 days. */
  dau_mau: number | null;
}
