/// <reference types="bun" />
/**
 * Plan UX, A7: the token of a one-use link travels in the address's fragment, is read once by its page and leaves
 * the address at once, without a new entry in the history.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { forgetLinkFromAddress, readLinkToken, resetLinkToken } from "./linkToken";

const TOKEN = "Ab3_-".repeat(8) + "xyz"; // 43 characters of base64url, the shape the server makes

describe("a one-use link's token", () => {
  afterEach(resetLinkToken);

  test("comes from the fragment, in the shape the server makes, and nothing else", () => {
    expect(readLinkToken({ hash: `#t=${TOKEN}`, pathname: "/activate" })).toBe(TOKEN);
    resetLinkToken();
    expect(readLinkToken({ hash: `#x=1&t=${TOKEN}`, pathname: "/unlock" })).toBe(TOKEN);
    resetLinkToken();
    for (const hash of ["", "#t=short", `#t=${TOKEN}<b>`, `#token=${TOKEN}`, `#t=${TOKEN}%20`]) {
      expect(readLinkToken({ hash, pathname: "/activate" }), hash).toBeNull();
    }
  });

  test("is remembered for its own page once the address is clean, and not for another", () => {
    readLinkToken({ hash: `#t=${TOKEN}`, pathname: "/reset-password" });
    expect(readLinkToken({ hash: "", pathname: "/reset-password" })).toBe(TOKEN);
    expect(readLinkToken({ hash: "", pathname: "/activate" })).toBeNull();
  });

  test("is nothing while the page renders on the server", () => {
    expect(readLinkToken(undefined)).toBeNull();
  });

  test("leaves the address in place: the same entry of the history, without the fragment", () => {
    const calls: unknown[][] = [];
    const win = (hash: string) =>
      ({
        location: { hash, pathname: "/unlock", search: "?lang=en" },
        history: { state: { k: 1 }, replaceState: (...args: unknown[]) => calls.push(args) },
      }) as unknown as Pick<Window, "location" | "history">;
    forgetLinkFromAddress(win(`#t=${TOKEN}`));
    expect(calls).toEqual([[{ k: 1 }, "", "/unlock?lang=en"]]);
    forgetLinkFromAddress(win(""));
    expect(calls).toHaveLength(1);
  });
});
