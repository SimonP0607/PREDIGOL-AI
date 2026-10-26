/// <reference types="bun" />
/**
 * PLAN UX A11, the readers' AI card in Operación · Costes: with the budget at 0 it says it spends nothing (no month bar
 * measured against nothing, no "exhausted" state), with a budget it shows its own state and bar, and its note never
 * names an internal table (the e2e's clean-page check caught "ai.user_usage" rendered as text).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { AiUserView } from "@/lib/api/v1/types_ai_layer";
import { UserAiCard } from "./AiCosts";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

function view(
  over: Partial<AiUserView["budget"]> = {},
  mode: AiUserView["mode"] = "off",
): AiUserView {
  return {
    mode,
    budget: {
      state: "EXHAUSTED",
      monthly_budget_usd: "0",
      spent_month_usd: "0",
      spent_today_usd: "0",
      daily_budget_usd: "0",
      daily_cap_usd: "0",
      remaining_month_usd: "0",
      days_left: 6,
      day: "2026-10-26",
      ...over,
    },
    today: { ok: 0, rejected: 0, failed: 0, translations: 0, calls: 0 },
  };
}

describe("the readers' AI card", () => {
  test("without a budget it spends nothing and draws no bar", () => {
    setLocale("es");
    const html = renderToStaticMarkup(<UserAiCard u={view()} />);
    const shown = text(html);
    expect(shown).toContain("Sin presupuesto: no gasta");
    expect(shown).not.toContain("EXHAUSTED");
    expect(shown).not.toContain("Tope alcanzado");
    expect(html).not.toContain('data-testid="ai-month-bar"');
    expect(shown).toContain("Con el presupuesto en 0 no se gasta nada");
  });

  test("with a budget it shows its own state and the month's bar", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <UserAiCard
        u={view({ state: "NORMAL", monthly_budget_usd: "30", spent_month_usd: "3.5" }, "shadow")}
      />,
    );
    const shown = text(html);
    expect(shown).toContain("Dentro del presupuesto");
    expect(html).toContain('data-testid="ai-month-bar"');
  });

  test("the note names no internal table and no key is left untranslated", () => {
    for (const lang of ["es", "en"] as const) {
      setLocale(lang);
      for (const u of [view(), view({ state: "REDUCED", monthly_budget_usd: "30" }, "on")]) {
        const shown = text(renderToStaticMarkup(<UserAiCard u={u} />));
        expect(shown).not.toMatch(/\bai\.user_usage\b/);
        expect(shown).not.toMatch(/\bai\.layer\./);
      }
    }
    setLocale("es");
  });
});
