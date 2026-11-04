/**
 * The moments a page tells the notices' offer about (plan UX, B7; section 34: «permiso en contexto, nunca al abrir … al
 * tocar la campana de un partido, seguir un equipo o guardar un pick»). The provider that listens is PushProvider.tsx;
 * the bell of a match asks on its own, in its own sheet.
 *
 * «Ahora no» keeps the offer away from this device for LATER_DAYS (the profile and the bell can still turn notices on),
 * and at most one card asks the reader anything in a visit - the survey of B6 or this offer.
 */
import { createContext, useContext } from "react";

export type PushMoment = { reason: "follow"; team: string } | { reason: "save" };

export interface PushOfferValue {
  moment: (m: PushMoment) => void;
}

export const PushOfferContext = createContext<PushOfferValue | null>(null);

/** «This was a moment to offer notices»: nothing happens outside the provider (the console, a test). */
export function usePushMoment(): (m: PushMoment) => void {
  const value = useContext(PushOfferContext);
  return value?.moment ?? noop;
}

function noop(): void {
  // no provider: no offer
}

const AHEAD_MS = 7 * 86_400_000;

/** The bell of a match rings for a match that starts in the future, within the next 7 days (the server's own limit). */
export function bellOffered(kickoffAt: string, now: number = Date.now()): boolean {
  const at = Date.parse(kickoffAt);
  return Number.isFinite(at) && at > now && at - now <= AHEAD_MS;
}

export const LATER_DAYS = 30;
const LATER_KEY = "predigol.push.later";

type Store = Pick<Storage, "getItem" | "setItem"> | null | undefined;

function storage(): Store {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** «Ahora no» on this device: the offer stays away for LATER_DAYS. */
export function markLater(now: Date = new Date(), store: Store = storage()): void {
  try {
    store?.setItem(LATER_KEY, now.toISOString());
  } catch {
    // storage refused: the visit's own limit still holds
  }
}

export function saidLater(now: Date = new Date(), store: Store = storage()): boolean {
  try {
    const raw = store?.getItem(LATER_KEY);
    if (!raw) return false;
    const at = Date.parse(raw);
    return Number.isFinite(at) && now.getTime() - at < LATER_DAYS * 86_400_000;
  } catch {
    return false;
  }
}

export interface OfferFacts {
  /** A signed-in reader with nothing owed - never the owner. */
  reader: boolean;
  /** GET /me/push: notices can be offered (FBI_PUSH and PrediGol's key). */
  available: boolean;
  /** What this browser is (lib/push.ts), null while unknown. */
  device: "unsupported" | "needs_install" | "denied" | "on" | "off" | null;
  /** The account already receives on another device. */
  hasDevices: boolean;
  /** «Ahora no» in the last LATER_DAYS on this device. */
  later: boolean;
  /** A card already asked something in this visit (the survey or this offer). */
  asked: boolean;
  /** The optional tour's card is up. */
  tour: boolean;
}

/** Whether a moment may bring the offer: never twice in a visit, never over another card, never to a blocked browser. */
export function mayOfferPush(f: OfferFacts): boolean {
  if (!f.reader || !f.available || f.later || f.asked || f.tour) return false;
  if (f.device === "off") return true;
  // An iPhone in Safari: the install guide - unless the account already receives on another device.
  return f.device === "needs_install" && !f.hasDevices;
}
