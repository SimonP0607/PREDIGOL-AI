/**
 * The optional four-step tour's steps and its context (plan UX, A13): which page each step opens and how a page reaches
 * the tour (./Tour.tsx draws it). Outside its provider there is no tour: nothing to show, nothing to start.
 */
import { createContext, useContext } from "react";
import type { Today } from "@/lib/api/v1/types_today";

export const TOUR_STEPS = ["home", "match", "pick", "myPicks"] as const;
export type TourStep = (typeof TOUR_STEPS)[number];

export interface TourValue {
  step: TourStep | null;
  start: () => void;
  next: () => void;
  close: () => void;
}

export const TourContext = createContext<TourValue | null>(null);

/** The page of a step. The match is the first of today's board when the page has it, else the list of matches. */
export function stepPath(step: TourStep, today: Today | null | undefined): string {
  if (step === "home") return "/home";
  if (step === "pick") return "/picks";
  if (step === "myPicks") return "/my-picks";
  const first = today?.matches.data[0];
  return first ? `/matches/${first.fixture_id}` : "/matches";
}

const NO_TOUR: TourValue = { step: null, start: () => {}, next: () => {}, close: () => {} };

/** The tour, or none outside its provider (a page rendered on its own): nothing to show, nothing to start. */
export function useTour(): TourValue & { available: boolean } {
  const ctx = useContext(TourContext);
  return ctx ? { ...ctx, available: true } : { ...NO_TOUR, available: false };
}
