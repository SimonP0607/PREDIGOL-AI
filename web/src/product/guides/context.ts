/**
 * The guides' context and the hooks that reach it (plan UX-051). Outside its provider (a page rendered on its own) there are
 * no guides: nothing is shown, started or asked.
 */
import { createContext, useContext, useEffect } from "react";
import type { GuideKey, GuideState } from "@/lib/api/v1/types_guides";

export type Trigger = "auto" | "replay" | "resume";
export type LeaveMethod = "button" | "escape" | "navigate";

export interface ActiveGuide {
  key: GuideKey;
  /** The card now: the position in the guide's cards (the welcome is 0). */
  index: number;
  /** step: a card of the guide; resume: «¿Seguimos?» before going on from `index`. */
  mode: "step" | "resume";
  trigger: Trigger;
}

export interface GuidesValue {
  active: ActiveGuide | null;
  seen: (guide: GuideKey) => GuideState | undefined;
  /** Start a guide now (the reader asked: «?», Ayuda). */
  start: (guide: GuideKey, trigger?: Trigger, from?: number) => void;
  /** Take the reader to the guide's screen and start it there, once the screen has its data (Ayuda > «Ver»). */
  request: (guide: GuideKey, from?: number) => void;
  next: () => void;
  back: () => void;
  skip: (method?: LeaveMethod) => void;
  finish: () => void;
  /** Escape or the system's back: pauses the mandatory guide, skips an optional one. */
  dismiss: (method: LeaveMethod) => void;
  resume: () => void;
  declineResume: () => void;
  screenReady: (screen: string) => void;
}

export const GuidesContext = createContext<GuidesValue | null>(null);

const NONE: GuidesValue = {
  active: null,
  seen: () => undefined,
  start: () => {},
  request: () => {},
  next: () => {},
  back: () => {},
  skip: () => {},
  finish: () => {},
  dismiss: () => {},
  resume: () => {},
  declineResume: () => {},
  screenReady: () => {},
};

export function useGuides(): GuidesValue & { available: boolean } {
  const ctx = useContext(GuidesContext);
  return ctx ? { ...ctx, available: true } : { ...NONE, available: false };
}

/** A screen says it has its data: the guide that opens on it may launch (once per visit, by the rules of fatigue). */
export function useGuideScreen(screen: string, options: { ready: boolean }): void {
  const ctx = useContext(GuidesContext);
  const { ready } = options;
  const screenReady = ctx?.screenReady;
  useEffect(() => {
    if (ready && screenReady) screenReady(screen);
  }, [ready, screen, screenReady]);
}
