import { describe, expect, test } from "bun:test";
import { amountOk, approveBody, flagsOf, needsTick, noteOk, who } from "./paymentQueue";

const base = {
  amount_matches: true,
  same_reference: 0,
  overdue: false,
  previous_rejections: 0,
  new_account: false,
  phone_elsewhere: 0,
  status: "submitted" as const,
};

describe("the queue's flags", () => {
  test("a clean notice has none", () => expect(flagsOf(base)).toEqual([]));
  test("each oddity is its own flag", () => {
    expect(flagsOf({ ...base, amount_matches: false })).toEqual(["amount"]);
    expect(flagsOf({ ...base, same_reference: 2 })).toEqual(["duplicate"]);
    expect(flagsOf({ ...base, overdue: true })).toEqual(["overdue"]);
    expect(flagsOf({ ...base, amount_matches: false, same_reference: 1, overdue: true })).toEqual([
      "amount",
      "duplicate",
      "overdue",
    ]);
  });
  test("the person's own signs: a refusal before, a day-old account, a mobile shared (UX-098)", () => {
    expect(flagsOf({ ...base, previous_rejections: 1 })).toEqual(["refused_before"]);
    expect(flagsOf({ ...base, new_account: true })).toEqual(["new_account"]);
    expect(flagsOf({ ...base, phone_elsewhere: 2 })).toEqual(["shared_phone"]);
    expect(
      flagsOf({ ...base, previous_rejections: 3, new_account: true, phone_elsewhere: 1 }),
    ).toEqual(["refused_before", "new_account", "shared_phone"]);
    expect(flagsOf({ ...base, same_reference: 1, new_account: true })).toEqual([
      "duplicate",
      "new_account",
    ]);
  });
  test("a decided notice raises nothing", () => {
    expect(flagsOf({ ...base, status: "approved", amount_matches: false })).toEqual([]);
    expect(
      flagsOf({ ...base, status: "rejected", previous_rejections: 2, new_account: true }),
    ).toEqual([]);
  });
  test("amount and duplicate ask for a tick; lateness and the person's signs do not", () => {
    expect(needsTick(["amount"])).toBe(true);
    expect(needsTick(["duplicate"])).toBe(true);
    expect(needsTick(["overdue"])).toBe(false);
    expect(needsTick(["refused_before", "new_account", "shared_phone"])).toBe(false);
    expect(needsTick([])).toBe(false);
  });
});

describe("what the owner types", () => {
  test("notes of 3 to 200 characters", () => {
    expect(noteOk("  ab ")).toBe(false);
    expect(noteOk("abc")).toBe(true);
    expect(noteOk("x".repeat(200))).toBe(true);
    expect(noteOk("x".repeat(201))).toBe(false);
  });
  test("amounts are plain numbers", () => {
    expect(amountOk("150000")).toBe(true);
    expect(amountOk("150000.50")).toBe(true);
    expect(amountOk("150.000")).toBe(false);
    expect(amountOk("1.500,00")).toBe(false);
    expect(amountOk("0")).toBe(false);
    expect(amountOk("-5")).toBe(false);
    expect(amountOk("")).toBe(false);
  });
  test("the received amount travels only when it differs", () => {
    expect(approveBody("150000", "150000", 1)).toEqual({ months: 1 });
    expect(approveBody("150000.00", "150000", 2)).toEqual({ months: 2 });
    expect(approveBody("150000", "140000", 1)).toEqual({ received_amount: "140000", months: 1 });
  });
  test("the name falls back to the alias and the e-mail", () => {
    expect(
      who({ first_name: "Ana", last_name: "Ruiz", display_name: "ana", email: "a@x.co" }),
    ).toBe("Ana Ruiz");
    expect(who({ first_name: null, last_name: null, display_name: "ana", email: "a@x.co" })).toBe(
      "ana",
    );
    expect(who({ first_name: null, last_name: null, display_name: "", email: "a@x.co" })).toBe(
      "a@x.co",
    );
  });
});
