/**
 * What the monthly survey needs to know about this visit (plan UX, B6; section 40): whether something failed - an error
 * shown to the reader, a server error, the API out of reach - and whether the survey was already offered. «Nunca tras un
 * error»: after any of those the survey waits for another visit. Both facts last as long as the tab (sessionStorage), so
 * a reload after an error does not bring the survey back either; a browser that refuses the storage keeps them in memory.
 * Nothing here leaves the browser.
 *
 * Whether the survey is owed at all - once every 30 days, counted from the reader's last answer or close - is the
 * server's (GET /me/feedback/survey); `mayOffer` puts the two together.
 */

const TROUBLE = "predigol.feedback.trouble";
const OFFERED = "predigol.feedback.offered";

/** How long after a useful moment the survey may come up: the reader has read what they opened, never mid-sentence. */
export const OFFER_AFTER_MS = 12_000;

const memory = { trouble: false, offered: false };

function read(key: string): boolean {
  try {
    return typeof window !== "undefined" && window.sessionStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function write(key: string): void {
  try {
    if (typeof window !== "undefined") window.sessionStorage.setItem(key, "1");
  } catch {
    // a private window or blocked storage: the memory keeps it for this page's life
  }
}

/** Something failed in front of the reader (or under them): no survey for the rest of this visit. */
export function markTrouble(): void {
  memory.trouble = true;
  write(TROUBLE);
}

export function hadTrouble(): boolean {
  return memory.trouble || read(TROUBLE);
}

/**
 * The survey came up (answered, closed or ignored): not again in this visit, whatever the server says. The notices'
 * offer (plan UX, B7) marks it too: one card asks the reader something in a visit, never two.
 */
export function markOffered(): void {
  memory.offered = true;
  write(OFFERED);
}

export function wasOffered(): boolean {
  return memory.offered || read(OFFERED);
}

/** A new visit, for the tests. */
export function resetFeedbackSession(): void {
  memory.trouble = false;
  memory.offered = false;
  try {
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(TROUBLE);
      window.sessionStorage.removeItem(OFFERED);
    }
  } catch {
    // nothing stored
  }
}

export interface OfferFacts {
  /** A signed-in reader - never the owner, even looking as a reader - with no consent owed. */
  reader: boolean;
  /** GET /me/feedback/survey: the owner keeps it on (FBI_FEEDBACK)… */
  enabled: boolean;
  /** …and it is owed: no answer and no close in the last 30 days. */
  due: boolean;
  /** Something failed in this visit. */
  trouble: boolean;
  /** Already offered in this visit. */
  offered: boolean;
  /** The optional tour's card is on the screen: one card at a time. */
  tour: boolean;
  /** The page is on the screen, not a tab in the background. */
  visible: boolean;
}

/** Whether the survey may come up now, after a useful moment. */
export function mayOffer(f: OfferFacts): boolean {
  return f.reader && f.enabled && f.due && !f.trouble && !f.offered && !f.tour && f.visible;
}
