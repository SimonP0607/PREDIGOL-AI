/**
 * When a guide launches by itself (plan UX-051, section 3 «Reglas contra la fatiga»), as pure functions the browser never
 * needs to test: what the reader has seen of it, and what stands between it and the screen.
 */
import type { GuideState, GuideStatus } from "@/lib/api/v1/types_guides";
import type { GuideDef } from "./registry";

export type Seen = Pick<GuideState, "version" | "status" | "step">;

/**
 * What a guide asks of the reader's next visit to its screen: `start` (never shown, or shown in an earlier version the
 * guide says to show again), `resume` (left half way), or nothing (completed or skipped at this version, or not built).
 */
export function owed(def: GuideDef, seen: Seen | undefined): "start" | "resume" | null {
  if (def.steps.length === 0) return null;
  if (!seen) return "start";
  if (seen.version < def.reshowFrom) return "start";
  switch (seen.status satisfies GuideStatus) {
    case "completed":
    case "skipped":
      return null;
    case "in_progress":
      return seen.step > 0 ? "resume" : "start";
    default:
      return "start";
  }
}

export interface Facts {
  /** A reader's account (never the owner's). */
  reader: boolean;
  /** FBI_GUIDES. */
  guidesOn: boolean;
  /** The reader's own switch for the guides of each screen. */
  auto: boolean;
  welcomeDue: boolean;
  consentsDue: boolean;
  /** A limited membership: the reader comes to renew. */
  limited: boolean;
  /** The reader arrived from a notice or an e-mail. */
  fromNotice: boolean;
  /** A guide is up already. */
  active: boolean;
  /** Another layer is open (a sheet, a slip, an explanation, a dialog). */
  layerOpen: boolean;
  /** A guide already launched on its own in this visit to a screen. */
  launchedThisVisit: boolean;
  /** Skips in a row in this session. */
  skipsInARow: number;
}

export const MAX_SKIPS = 2;

/**
 * Why a guide may not launch by itself now, or null when it may. The mandatory guide of Perfil answers to its own rules
 * (consents, limited membership, the owner, the switch): it ignores the personal switch, the visit and skip limits.
 */
export function blockedBy(def: GuideDef, f: Facts): string | null {
  if (!f.reader) return "not-a-reader";
  if (!f.guidesOn) return "switch-off";
  if (f.welcomeDue) return "welcome-due";
  if (f.consentsDue) return "consents-due";
  if (f.limited) return "limited";
  if (f.active) return "another-guide";
  if (f.layerOpen) return "layer-open";
  if (def.mandatory) return null;
  if (!f.auto && def.key !== "general") return "personal-switch";
  if (f.fromNotice) return "from-notice";
  if (f.launchedThisVisit) return "one-per-visit";
  if (f.skipsInARow >= MAX_SKIPS) return "skips";
  return null;
}
