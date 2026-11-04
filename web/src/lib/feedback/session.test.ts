/// <reference types="bun" />
/**
 * When the monthly survey may come up (plan UX, B6; section 40), without a browser: «una vez cada 30 días, tras un momento
 * útil; nunca en el login ni tras un error; si se cierra, no vuelve ese mes». The 30 days are the server's (GET
 * /me/feedback/survey says whether it is owed; backend/tests/integration/test_customer_feedback.py proves them); here, the
 * visit's part - once offered, never again in it; after an error, never in it; never to the owner; never over the tour -
 * and the frequency both give together. Which pages can bring it is pinned too: only the plan's useful moments.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import {
  OFFER_AFTER_MS,
  hadTrouble,
  markOffered,
  markTrouble,
  mayOffer,
  resetFeedbackSession,
  wasOffered,
  type OfferFacts,
} from "./session";

const OWED: OfferFacts = {
  reader: true,
  enabled: true,
  due: true,
  trouble: false,
  offered: false,
  tour: false,
  visible: true,
};

afterEach(() => resetFeedbackSession());

describe("whether it may come up now", () => {
  test("a reader it is owed to, after a useful moment, nothing failed: yes", () => {
    expect(mayOffer(OWED)).toBe(true);
  });

  test.each([
    ["the owner, even looking as a reader, or consents owed", { reader: false }],
    ["the owner turned it off (FBI_FEEDBACK=0)", { enabled: false }],
    ["answered or closed in the last 30 days", { due: false }],
    ["something failed in this visit", { trouble: true }],
    ["already offered in this visit", { offered: true }],
    ["the tour's card is up", { tour: true }],
    ["a tab in the background", { visible: false }],
  ] as const)("never when %s", (_why, change) => {
    expect(mayOffer({ ...OWED, ...change })).toBe(false);
  });

  test("it waits for the reader to read what they opened: never mid-sentence", () => {
    expect(OFFER_AFTER_MS).toBeGreaterThanOrEqual(10_000);
  });
});

describe("the visit", () => {
  test("once offered, never again in it - answered, closed or ignored, whatever the server says", () => {
    expect(wasOffered()).toBe(false);
    markOffered();
    expect(wasOffered()).toBe(true);
    expect(mayOffer({ ...OWED, offered: wasOffered() })).toBe(false);
  });

  test("after an error - shown, from the server or the API out of reach - never in it", () => {
    expect(hadTrouble()).toBe(false);
    markTrouble();
    expect(hadTrouble()).toBe(true);
    expect(mayOffer({ ...OWED, trouble: hadTrouble() })).toBe(false);
  });

  test("a new visit starts clean", () => {
    markOffered();
    markTrouble();
    resetFeedbackSession();
    expect([wasOffered(), hadTrouble()]).toEqual([false, false]);
  });
});

test("frequency: 120 days of daily visits with useful moments - one survey every 30 days, none on a day with an error", () => {
  // the server's rule (fbi.customer.feedback): owed while there is no answer or close in the last 30 days
  let last: number | null = null;
  const offered: number[] = [];
  const errorDays = new Set([30, 31]);
  for (let day = 0; day < 120; day++) {
    resetFeedbackSession(); // a new visit each day
    if (errorDays.has(day)) markTrouble(); // something failed before the useful moment
    for (let moment = 0; moment < 3; moment++) {
      const due = last === null || day - last >= 30;
      if (mayOffer({ ...OWED, due, trouble: hadTrouble(), offered: wasOffered() })) {
        markOffered();
        offered.push(day);
        last = day; // answered or closed: the server keeps it away for 30 days
      }
    }
  }
  // day 30 and 31 had an error: it waited for the first visit without one
  expect(offered).toEqual([0, 32, 62, 92]);
  for (let i = 1; i < offered.length; i++)
    expect(offered[i]! - offered[i - 1]!).toBeGreaterThanOrEqual(30);
});

describe("only the plan's useful moments bring it", () => {
  const SRC = join(import.meta.dir, "..", "..");
  const files = (dir: string): string[] =>
    readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return files(path);
      return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
    });

  test("opening a match's analysis, a match's result, one's own results - never signing in, the welcome or Inicio", () => {
    const uses: Array<[string, string]> = [];
    for (const file of files(SRC)) {
      for (const m of readFileSync(file, "utf8").matchAll(/useUsefulMoment\(\s*"([a-z_]+)"/g))
        uses.push([relative(SRC, file), m[1]!]);
    }
    expect(uses.sort()).toEqual([
      ["product/match/PostmatchTab.tsx", "result_seen"],
      ["product/reading/ReadingBlock.tsx", "analysis_opened"],
      ["product/records/MyPicksPage.tsx", "result_seen"],
    ]);
  });
});
