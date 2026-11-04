/// <reference types="bun" />
/**
 * Plan UX, A7 (R11 of the security plan): the page's password meter says what the server will say. The cases are the
 * backend's own (backend/tests/unit/password_rule_cases.json, checked there against fbi/auth/passwords.py); only the
 * common-password list is the server's alone.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  checkPassword,
  folded,
  minLength,
  passwordReady,
  trivial,
  type PasswordProblem,
} from "./passwordRule";

interface Case {
  password: string;
  email?: string;
  name?: string;
  has_mfa?: boolean;
  problems: PasswordProblem[];
}

const CASES = (
  JSON.parse(
    readFileSync(
      join(
        import.meta.dir,
        "..",
        "..",
        "..",
        "..",
        "backend",
        "tests",
        "unit",
        "password_rule_cases.json",
      ),
      "utf8",
    ),
  ) as { cases: Case[] }
).cases;

describe("the password rule on the page", () => {
  test("agrees with the backend, case by case", () => {
    expect(CASES.length).toBeGreaterThan(15);
    for (const c of CASES) {
      const found = checkPassword(c.password, {
        email: c.email,
        name: c.name,
        hasMfa: c.has_mfa,
      }).problems;
      expect({ password: c.password, problems: found }).toEqual({
        password: c.password,
        problems: c.problems,
      });
    }
  });

  test("asks 15 characters, or 12 with a second factor", () => {
    expect(minLength(false)).toBe(15);
    expect(minLength(true)).toBe(12);
    expect(checkPassword("doce-car-xyz", { hasMfa: true }).problems).toEqual([]);
    expect(checkPassword("doce-car-xyz").problems).toEqual(["password_too_short"]);
  });

  test("measures: nothing, not enough, enough, good, very good", () => {
    expect(checkPassword("").strength).toBe(0);
    expect(checkPassword("corta").strength).toBe(1);
    expect(checkPassword("quince letras ok").strength).toBe(2);
    expect(checkPassword("tres palabras largas bastan").strength).toBe(4);
    expect(checkPassword("una-frase-de-veinte!").strength).toBe(4);
    expect(checkPassword("abcdefghijklmnopq").strength).toBe(1); // a run: not enough, whatever its length
  });

  test("folds accents and separators, and finds trivial runs", () => {
    expect(folded("María-José")).toBe("mariajose");
    expect(trivial("123456789012345")).toBe(true);
    expect(trivial("la-final-se-juega-en-mayo")).toBe(false);
  });

  test("sends only a password the rule accepts, typed the same twice", () => {
    const good = "la-final-se-juega-en-mayo";
    expect(passwordReady(good, good, { email: "ana@example.org" })).toBe(true);
    expect(passwordReady(good, `${good}!`, { email: "ana@example.org" })).toBe(false);
    expect(passwordReady("", "", {})).toBe(false);
    expect(
      passwordReady("anabel-de-siempre-2026", "anabel-de-siempre-2026", { name: "Anabel" }),
    ).toBe(false);
    expect(passwordReady("corto-pero-12", "corto-pero-12", { hasMfa: true })).toBe(true);
  });
});
