/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { onGoldCard, STATUS_TONE, USER_STATUSES } from "./userStatus";

describe("the gold card of a pick (plan maestro UX/UI 2026, PR-13)", () => {
  test("only what PrediGol recommends, with value at the price of now", () => {
    expect(onGoldCard({ user_status: "RECOMMENDED", value_now: true })).toBe(true);
    expect(onGoldCard({ user_status: "RECOMMENDED", value_now: false })).toBe(false);
  });

  test("no other state reaches it, with or without value", () => {
    for (const user_status of USER_STATUSES.filter((s) => s !== "RECOMMENDED")) {
      expect(onGoldCard({ user_status, value_now: true })).toBe(false);
      expect(onGoldCard({ user_status, value_now: false })).toBe(false);
    }
  });

  test("the card and the seal say the same: gold is the recommended one, and only that one", () => {
    expect(STATUS_TONE.RECOMMENDED).toBe("gold");
    expect(USER_STATUSES.filter((s) => STATUS_TONE[s] === "gold")).toEqual(["RECOMMENDED"]);
  });
});
