/// <reference types="bun" />
/**
 * The customers' lifecycle in the owner's words (plan UX, B11): every state and every reason code of the backend's closed
 * list has its text in Spanish and in English, the two new views have their names, a code this page does not know is left
 * out (never shown raw), and a share of a cohort under 30 readers is never shown as a percentage.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import en from "@/locales/en/admin.json";
import es from "@/locales/es/admin.json";
import enSupport from "@/locales/en/support.json";
import esSupport from "@/locales/es/support.json";
import { CUSTOMER_VIEWS } from "@/lib/api/v1/types_customers";
import { setLocale } from "@/lib/i18n";
import {
  COHORT_MIN,
  CUSTOMER_STATES,
  LIFECYCLE_REASONS,
  lifecycleReasons,
  rateText,
} from "./lifecycleFigures";

afterEach(() => setLocale("es"));

describe("the words of the lifecycle", () => {
  for (const [lang, tree] of [
    ["es", es],
    ["en", en],
  ] as const) {
    test(`every state, reason and view has its text in ${lang}`, () => {
      for (const s of CUSTOMER_STATES) {
        expect(tree.customers.lifecycle.state[s], `${lang} state ${s}`).toBeTruthy();
      }
      for (const r of LIFECYCLE_REASONS) {
        const text = (tree.customers.lifecycle.reason as Record<string, string>)[r];
        expect(text, `${lang} reason ${r}`).toBeTruthy();
      }
      for (const v of CUSTOMER_VIEWS)
        expect(tree.customers.views[v], `${lang} view ${v}`).toBeTruthy();
      expect(Object.keys(tree.customers.lifecycle.reason).sort()).toEqual(
        [...LIFECYCLE_REASONS].sort(),
      );
    });
  }

  test("the reason codes are the backend's closed list", () => {
    const py = readFileSync(
      new URL("../../../backend/src/fbi/customer/lifecycle.py", import.meta.url),
      "utf8",
    );
    const block = py.slice(
      py.indexOf("REASONS: Final"),
      py.indexOf("})", py.indexOf("REASONS: Final")),
    );
    const codes = [...block.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]!);
    expect(codes.sort()).toEqual([...LIFECYCLE_REASONS].sort());
  });

  test("the queue says why a request is first", () => {
    expect(esSupport.admin.atRisk).toBeTruthy();
    expect(enSupport.admin.atRiskHint).toBeTruthy();
  });

  test("a code the page does not know is left out, never shown raw", () => {
    setLocale("es");
    const out = lifecycleReasons(["silent_7d", "a_code_from_the_future"]);
    expect(out).toEqual(["sin actividad en 7 días"]);
    expect(out.join(" ")).not.toContain("admin.");
  });
});

describe("the rates", () => {
  test("under 30 readers there is no percentage", () => {
    setLocale("es");
    expect(COHORT_MIN).toBe(30);
    const text = rateText({ n: 3, of: 12, value: null });
    expect(text).toContain("Datos insuficientes");
    expect(text).not.toContain("%");
  });
  test("from 30 readers, the share with its counts", () => {
    setLocale("en");
    expect(rateText({ n: 15, of: 30, value: 0.5 })).toBe("50.0% (15/30)");
  });
});
