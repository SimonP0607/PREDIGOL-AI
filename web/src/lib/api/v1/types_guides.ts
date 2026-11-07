/** Types for /api/v1/me/guides/*. Mirrors fbi.api.contracts.guides (UX-027): the memory of what each reader has seen. */
import type { Iso } from "./types";

/** The closed list of guides: the general tour, one per screen and the first guide of Perfil. */
export const GUIDE_KEYS = [
  "general",
  "home",
  "matches",
  "live",
  "match",
  "picks",
  "parlays",
  "odds",
  "my_picks",
  "profile",
] as const;
export type GuideKey = (typeof GUIDE_KEYS)[number];

/** pending: the screen was visited and the guide not yet shown. Within a version the status never goes down. */
export type GuideStatus = "pending" | "in_progress" | "completed" | "skipped";

export interface GuideState {
  guide: GuideKey;
  /** The version of the content the reader saw. */
  version: number;
  status: GuideStatus;
  /** The last step reached (0-based): to resume, and to know where it was skipped. */
  step: number;
  first_seen_at: Iso;
  started_at: Iso | null;
  completed_at: Iso | null;
  skipped_at: Iso | null;
}

export interface GuideIn {
  version: number;
  status: GuideStatus;
  step: number;
}
