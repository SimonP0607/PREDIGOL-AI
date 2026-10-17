/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { healthReason } from "./labels";

describe("health reasons", () => {
  afterAll(() => setLocale("es"));

  test("a known code is said in the reader's language, with its values", () => {
    setLocale("es");
    expect(
      healthReason({
        detail: "alive, last beat 0 min ago",
        code: "worker_alive",
        vars: { minutes: 0 },
      }),
    ).toBe("vivo, último latido hace 0 min");
    expect(
      healthReason({
        detail: "15269/60000 requests today",
        code: "provider_ok",
        vars: { spent: 15269, budget: 60000 },
      }),
    ).toBe("15.269 de 60.000 peticiones hoy (nuestro límite)");
  });

  test("a job is named by its label, not its code", () => {
    setLocale("en");
    expect(
      healthReason({
        detail: "last odds_capture failed",
        code: "worker_last_failed",
        vars: { job: "odds_capture" },
      }),
    ).toBe("last “Odds capture” failed");
  });

  test("no code, or a code this page does not know: the backend's own words", () => {
    setLocale("es");
    expect(healthReason({ detail: "running" })).toBe("running");
    expect(healthReason({ detail: "something new", code: "brand_new_reason" })).toBe(
      "something new",
    );
  });
});

describe("decision-rule rejections", () => {
  test("known reasons in Spanish with their numbers; an unknown one as it came", async () => {
    const { rejectionReason } = await import("./labels");
    setLocale("es");
    expect(rejectionReason("odds outside [1.50, 5.00]")).toBe("cuota fuera de [1.50, 5.00]");
    expect(rejectionReason("expected value below 0.05")).toBe("valor esperado por debajo de 0.05");
    expect(rejectionReason("probability edge below 0.02")).toBe(
      "ventaja de probabilidad por debajo de 0.02",
    );
    expect(rejectionReason("something new")).toBe("something new");
  });
});
