/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { detailText } from "./auditDetail";

describe("audit detail", () => {
  afterAll(() => setLocale("es"));

  test("keys and known values in Spanish; a change reads before -> after", () => {
    setLocale("es");
    expect(detailText({ fields: ["language", "timezone"] })).toBe("campos: idioma, zona horaria");
    expect(detailText({ to: "USER", from: "SUPER_ADMIN" })).toBe(
      "antes: SUPER_ADMIN · ahora: USER",
    );
    expect(detailText({ reason: "unknown_email" })).toBe("motivo: email desconocido");
  });

  test("English, and unknown keys or values shown as they came", () => {
    setLocale("en");
    expect(detailText({ to: "disabled", from: "active" })).toBe("from: active · to: disabled");
    expect(detailText({ something_new: "odd_value", n: 3 })).toBe(
      "something_new: odd_value · n: 3",
    );
  });
});
