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

export interface BreakdownRow {
  /** The screen's group, the market, or the id of the league or the team. */
  key: string;
  /** The league's or the team's name; null for a screen group or a market. */
  label: string | null;
  events_30d: number;
  /** Never fewer than the overview's min_subjects: a line with fewer readers behind it is not listed. */
  subjects_30d: number;
}

export interface GuideRow {
  /** The guide (general, home, matches, ..., profile). */
  guide: string;
  version: number;
  /** Readers who started it in 30 days (a line stands only with min_subjects). */
  started: number;
  completed: number;
  skipped: number;
  /** Readers who skipped it on its first card. */
  skipped_first: number;
  /** Readers who left it half way (Escape or back) to come back later. */
  paused: number;
  /** The step (0-based) where most readers skipped, if any did. */
  top_skip_step: number | null;
  top_skip_readers: number;
  /** One to look at again: descriptive and self-selected, there is no control group. */
  review: boolean;
}

export interface FunnelStep {
  step: "activated" | "onboarding_started" | "onboarding_completed" | "first_value";
  subjects: number;
}

export interface LifecycleRate {
  n: number;
  /** The cohort's size. */
  of: number;
  /** Null while the cohort is under 30 readers: never a share of a handful. */
  value: number | null;
}

export interface LifecycleMetrics {
  day: string | null;
  states: Record<string, number>;
  renewal_30d: LifecycleRate;
  activation_7d: LifecycleRate;
  retention_d7: LifecycleRate;
  retention_d30: LifecycleRate;
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
  /** Screens viewed in 30 days, by group (never an address or a search). */
  screens: BreakdownRow[];
  /** The market of the picks saved and of the legs added to a parlay, in 30 days. */
  markets: BreakdownRow[];
  /** Leagues of the matches opened in 30 days: worked out from the match, collected apart from nothing. */
  leagues: BreakdownRow[];
  /** Teams of the matches opened in 30 days: worked out from the match. */
  teams: BreakdownRow[];
  /** What came of each guide and version in 30 days (UX-054): groups only, never one reader. */
  guides: GuideRow[];
  /** The customers' lifecycle (B11). */
  lifecycle: LifecycleMetrics | null;
}
