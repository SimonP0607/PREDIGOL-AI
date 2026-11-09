/**
 * The welcome just finished (UX-081, Sentry PREDIGOL-WEB-8): on finishing, the page navigated to Inicio at the API's answer, a
 * moment before the cached account (read by the gate) had caught up, so the gate sent the reader back to /welcome for an instant
 * (/welcome -> /home -> /welcome -> /home in under 100 ms). The page now leaves only when the account it shares with the gate
 * says the welcome is done.
 */
import { readFileSync } from "node:fs";
import { describe, expect, test } from "bun:test";
import { afterWelcome, welcomeExit } from "./next";

describe("leaving the welcome (UX-081)", () => {
  test("not while the account still says the welcome is owed, whatever was asked", () => {
    expect(welcomeExit(true, "/home")).toBeNull();
    expect(welcomeExit(true, null)).toBeNull();
  });

  test("once the account agrees, to where the reader was going", () => {
    expect(welcomeExit(false, "/home")).toBe("/home");
    expect(welcomeExit(false, afterWelcome("?next=%2Fmatches"))).toBe("/matches");
    expect(welcomeExit(false, "/transparency")).toBe("/transparency");
  });

  test("nowhere to go: nothing happens (a reader who arrives with nothing owed is sent on by the page's own rule)", () => {
    expect(welcomeExit(false, null)).toBeNull();
  });

  test("the page no longer navigates at the API's answer: it only decides where, and the account's change moves it", () => {
    const page = readFileSync(new URL("./WelcomePage.tsx", import.meta.url), "utf8");
    const finish = page.slice(
      page.indexOf("async function finish"),
      page.indexOf("function advance"),
    );
    expect(finish).toContain("setLeaving(");
    expect(finish).not.toContain("navigate(");
    expect(page).toContain("welcomeExit(due, leaving)");
  });
});
