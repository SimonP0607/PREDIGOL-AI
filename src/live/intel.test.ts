/// <reference types="bun" />
/** PrediGol Intelligence in the Admin Console: every state, context, filter and market status has its words in both
 * languages, and the console links to the page. */
import { describe, expect, test } from "bun:test";
import { hasKey } from "@/lib/i18n";
import { adminNav } from "@/components/layout/nav";

const STATES = [
  "RECHAZADO",
  "INVESTIGACION",
  "CAUTELA",
  "APROBADO",
  "PICK_DEL_DIA",
  "CANDIDATO_PARLAY",
  "PICK_PREMIUM",
];
const CONTEXTS = ["FULL", "PARTIAL", "LIMITED", "PENDING", "AI_OFF"];
const FILTERS = [
  "data",
  "model",
  "market",
  "calibration",
  "ev",
  "context",
  "risk",
  "correlation",
  "price",
  "final",
];
const MARKET_STATUS = ["ACTIVE", "RESEARCH", "CANDIDATE", "NOT_MODELABLE"];
const CRITERIA = [
  "coverage",
  "history",
  "real_price",
  "model",
  "calibration",
  "backtest",
  "vs_market",
  "shadow",
  "volume",
  "stability",
];

describe("PrediGol Intelligence words", () => {
  test("states, contexts, the ten filters, market statuses and the ten criteria exist in es and en", () => {
    for (const locale of ["es", "en"] as const) {
      for (const s of STATES) expect(hasKey(`intel.state.${s}`, locale)).toBe(true);
      for (const c of CONTEXTS) expect(hasKey(`intel.context.${c}`, locale)).toBe(true);
      for (const f of FILTERS) expect(hasKey(`intel.filter.${f}`, locale)).toBe(true);
      for (const m of MARKET_STATUS) expect(hasKey(`intel.markets.status.${m}`, locale)).toBe(true);
      for (const c of CRITERIA) expect(hasKey(`intel.markets.criteria.${c}`, locale)).toBe(true);
      expect(hasKey("admin.nav.intelligence", locale)).toBe(true);
    }
  });

  test("the Admin Console links to PrediGol Intelligence, in the intelligence group", () => {
    const group = adminNav.find((g) => g.label === "admin.groups.intelligence");
    expect(group?.items.some((i) => i.to === "/admin/intelligence")).toBe(true);
  });
});
