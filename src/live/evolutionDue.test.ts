/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { dueReason } from "./evolutionDue";

describe("research due reason", () => {
  afterAll(() => setLocale("es"));

  test("by its code, with its values, in Spanish", () => {
    setLocale("es");
    expect(
      dueReason({
        v2_due: "the model code changed (mc1 -> mc2)",
        v2_due_code: "model_code_changed",
        v2_due_vars: { before: "mc1", after: "mc2" },
      }),
    ).toBe("cambió el código de los modelos (mc1 → mc2)");
    expect(
      dueReason({
        v2_due: "a new dataset version is MODEL_READY (none recorded -> DATASET_V2)",
        v2_due_code: "new_dataset",
        v2_due_vars: { before: "", after: "DATASET_V2" },
      }),
    ).toBe("hay una versión de datos MODEL_READY nueva (ninguna registrada → DATASET_V2)");
  });

  test("an older backend without a code: its English sentence; nothing due: empty", () => {
    setLocale("en");
    expect(dueReason({ v2_due: "the code changed (a -> b)" })).toBe("the code changed (a -> b)");
    expect(dueReason({ v2_due: null })).toBe("");
  });
});
