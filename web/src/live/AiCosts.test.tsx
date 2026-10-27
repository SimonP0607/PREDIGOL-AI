/// <reference types="bun" />
/**
 * PHASE 0 of the AI master plan, the Costs view: the three envelopes (Claude of production, Claude of the LAB, Exa) each against its own
 * budget with the joint ceiling, what the cache and the batches saved (it may be negative), what was reused instead of paid, the
 * optimisations and the evidence each rests on - in both languages - and a server that sends no envelopes (an older one) shows a note.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import type { AiEnvelopes } from "@/lib/api/v1/types_ai_layer";
import { EnvelopesBody } from "./AiCosts";
import { envelopesOf } from "./aiModel";

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

afterEach(() => setLocale("es"));

const NO_LIMIT = { active: false, until: null, hits: 0 };

function envelopes(over: Partial<AiEnvelopes> = {}): AiEnvelopes {
  const days = Array.from({ length: 14 }, (_, n) => ({
    day: `2032-08-${String(2 + n).padStart(2, "0")}`,
    production_usd: n === 13 ? "2.0000" : "5.0000",
    lab_usd: n === 13 ? "1.2500" : "0.0000",
    exa_usd: "0.0000",
  }));
  return {
    month: "2032-08-01",
    days_left: 17,
    budget_version: "v3",
    production: {
      spent_usd: "72.0000",
      budget_usd: "185",
      spent_today_usd: "2.0000",
      share: 0.3892,
      projected_usd: "155.0000",
      projection_share: 0.8378,
      state: "NORMAL",
      reserved_for_batches_usd: "0.5000",
      reserve_usd: "10",
      reserve_locked_usd: "10.0000",
      run_rate_usd: "5.0000",
      unit_cost_usd: "0.5",
      limit: NO_LIMIT,
      workspace: "PREDIGOL",
    },
    lab: {
      spent_usd: "4.0000",
      budget_usd: "55",
      spent_today_usd: "1.2500",
      allocation_usd: "55.0000",
      share: 0.0727,
      allowed: true,
      reason: "ok",
      reserved_for_batches_usd: "0.0000",
      limit: NO_LIMIT,
      workspace: "PREDIGOL-LAB",
    },
    exa: {
      spent_usd: "0.3000",
      budget_usd: "35",
      spent_today_usd: "0.3000",
      share: 0.0086,
      allowed: true,
      reason: "ok",
      searches: 20,
    },
    claude: {
      spent_usd: "76.0000",
      ceiling_usd: "190",
      share: 0.4,
      projected_usd: "159.0000",
      projection_share: 0.8368,
    },
    savings: {
      month: {
        cache_usd: "12.3400",
        batch_usd: "3.2100",
        total_usd: "15.5500",
        calls: 400,
        batch_calls: 100,
        batch_share: 0.25,
        input_tokens: 4_000_000,
        cached_tokens: 2_400_000,
        write_tokens: 150_000,
        read_share: 0.6,
      },
    },
    reuse: {
      briefs_paid: 60,
      briefs_reused: 40,
      briefs_reused_material: 25,
      reviews_reused: 18,
      reviews_batched: 90,
    },
    batch: { open_items: 4, open_batches: 1, ended_batches: 9, lost_batches: 0, items_ended: 80 },
    switches: {
      cache: { mode: "auto", on: true, why: "", gate: null },
      brief_material: { mode: "auto", on: true, why: "", gate: null },
      budget_v3: { mode: "auto", on: true, why: "", gate: null },
      batch: { mode: "auto", on: false, why: "", gate: "batch" },
      native_schema: { mode: "auto", on: false, why: "", gate: "native_schema" },
      cache_layout: { mode: "auto", on: false, why: "", gate: "cache_layout" },
      gates: {
        batch: { gate: "batch", passed: false, at: null, evidence_hash: null, models: null },
        native_schema: {
          gate: "native_schema",
          passed: true,
          at: "2026-10-27T15:00:00Z",
          evidence_hash: "abc",
          models: ["claude-haiku-5-5"],
        },
        cache_layout: {
          gate: "cache_layout",
          passed: false,
          at: "2026-10-27T15:00:00Z",
          evidence_hash: "def",
          models: null,
        },
      },
    },
    days,
    factors: { batch: "0.5" },
    ...over,
  };
}

const render = (e: AiEnvelopes) => text(renderToStaticMarkup(<EnvelopesBody e={e} />));

describe("the three envelopes", () => {
  test("each one against its own budget, and Claude as a whole against the joint ceiling", () => {
    const page = render(envelopes());
    expect(page).toContain("Las tres bolsas de gasto");
    expect(page).toContain("Claude · producción");
    expect(page).toContain("Claude · LAB (experimentos)");
    expect(page).toContain("Exa · búsquedas web");
    expect(page).toContain("Claude en total");
    expect(page).toContain("Espacio de trabajo PREDIGOL");
    expect(page).toContain("Espacio de trabajo PREDIGOL-LAB");
    // production: spent, today, projection and its share; the open batches and the reserve
    expect(page).toContain("US$ 72,00");
    expect(page).toContain("39 % de US$ 185,00");
    expect(page).toContain("US$ 155,00");
    expect(page).toContain("US$ 0,50");
    expect(page).toContain("10,00 bloqueados hasta los últimos 5 días");
    // the LAB and Exa have theirs; the joint ceiling is US$190 and holds production and the LAB, not Exa
    expect(page).toContain("US$ 4,00");
    expect(page).toContain("US$ 55,00");
    expect(page).toContain("US$ 0,30");
    expect(page).toContain("US$ 76,00");
    expect(page).toContain("US$ 190,00");
    expect(page).toContain("Corre hoy");
    expect(page).toContain("Puede buscar");
  });

  test("the bars say how much of each envelope is spent", () => {
    const html = renderToStaticMarkup(<EnvelopesBody e={envelopes()} />);
    for (const id of ["production", "lab", "exa", "claude"]) {
      expect(html).toContain(`data-testid="ai-envelope-${id}"`);
    }
    expect(html).toContain('aria-valuenow="39"');
    expect(html).toContain('aria-valuenow="7"');
    expect(html).toContain('aria-valuenow="1"');
    expect(html).toContain('aria-valuenow="40"');
  });

  test("the budget's new state AJUSTE has its label and nothing breaks on a state the page does not know", () => {
    const base = envelopes();
    expect(render(envelopes({ production: { ...base.production, state: "AJUSTE" } }))).toContain(
      "Ajuste (misma calidad)",
    );
    const odd = envelopes({
      production: { ...base.production, state: "SOMETHING_NEW" as never },
      lab: { ...base.lab, reason: "unforeseen" },
    });
    const page = render(odd);
    expect(page).toContain("SOMETHING_NEW");
    expect(page).toContain("unforeseen");
  });

  test("a spent limit says until when no call is made; the LAB that yields and Exa that is spent say why", () => {
    const base = envelopes();
    const page = render(
      envelopes({
        production: {
          ...base.production,
          state: "EXHAUSTED",
          limit: { active: true, until: "2032-08-15T17:30:00Z", hits: 2 },
        },
        lab: { ...base.lab, allowed: false, reason: "yields_to_production" },
        exa: { ...base.exa, allowed: false, reason: "month_spent", share: 1 },
      }),
    );
    expect(page).toContain("El proveedor dijo que el límite está agotado: sin llamadas hasta");
    expect(page).toContain("Agotado (solo reglas)");
    expect(page).toContain("Cede ante producción");
    expect(page).toContain("La bolsa del mes está gastada");
  });

  test("the last 14 days, the newest first", () => {
    const html = renderToStaticMarkup(<EnvelopesBody e={envelopes()} />);
    const rows = html.match(/<tr/g) ?? [];
    expect(rows.length).toBeGreaterThanOrEqual(15); // the header and 14 days
    const page = text(html);
    expect(page.indexOf("US$ 2,00")).toBeLessThan(page.indexOf("US$ 5,00"));
  });
});

describe("what the cache and the batches saved", () => {
  test("the saving of the month, split in cache and batch, with the share each one worked on", () => {
    const page = render(envelopes());
    expect(page).toContain("Lo que ahorran la caché y los lotes");
    expect(page).toContain("US$ 15,55");
    expect(page).toContain("US$ 12,34");
    expect(page).toContain("US$ 3,21");
    expect(page).toContain("60 % de los tokens de entrada se leyeron de la caché");
    expect(page).toContain("25 % de las llamadas con tokens fueron en lote");
  });

  test("a cache write nobody has read yet makes the saving negative, and it is shown in red", () => {
    const base = envelopes();
    const html = renderToStaticMarkup(
      <EnvelopesBody
        e={envelopes({
          savings: {
            month: { ...base.savings.month, cache_usd: "-0.0500", total_usd: "-0.0500" },
          },
        })}
      />,
    );
    expect(html).toContain("text-negative");
    expect(text(html)).toContain("-0,05");
  });

  test("what was reused instead of paid, and the batches still open or lost", () => {
    const page = render(envelopes());
    expect(page).toContain("Resúmenes reutilizados");
    expect(page).toContain("25 por no haber cambio material · 60 pagados");
    expect(page).toContain("90 enviadas en lote");
    expect(page).toContain("4 tareas esperando resultado · 9 terminados este mes");
    const lost = render(envelopes({ batch: { ...envelopes().batch, lost_batches: 2 } }));
    expect(lost).toContain("Lotes perdidos");
  });
});

describe("the optimisations and the evidence they rest on", () => {
  test("which ones are in force and why, in plain words", () => {
    const page = render(envelopes());
    expect(page).toContain("Optimizaciones de la Fase 0");
    expect(page).toContain("Caché de prompts");
    expect(page).toContain(
      "Activa por defecto: cambia lo que se factura o se reutiliza, nunca un veredicto.",
    );
    expect(page).toContain("Lotes (Batch)");
    expect(page).toContain("Espera la evidencia de su prueba real.");
    expect(page).toContain("Bloque compartido del partido");
    expect(page).toContain("necesita su propia prueba de equivalencia");
  });

  test("the evidence of a gate: passed (and when), failed (and when), or none yet", () => {
    const page = render(envelopes());
    expect(page).toContain("Evidencia: todavía sin evidencia"); // batch
    expect(page).toContain("Evidencia: pasó el"); // native_schema
    expect(page).toContain("Evidencia: no pasó"); // cache_layout
  });

  test("the owner's switches: forced on, turned off", () => {
    const base = envelopes();
    const page = render(
      envelopes({
        switches: {
          ...base.switches,
          batch: { mode: "on", on: true, why: "", gate: "batch" },
          cache: { mode: "off", on: false, why: "", gate: null },
        },
      }),
    );
    expect(page).toContain("Forzada por el dueño.");
    expect(page).toContain("Apagada por el dueño.");
  });

  test("the same page in English", () => {
    setLocale("en");
    const page = render(envelopes());
    expect(page).toContain("The three spending envelopes");
    expect(page).toContain("Claude · production");
    expect(page).toContain("Exa · web search");
    expect(page).toContain("What the cache and the batches save");
    expect(page).toContain("Phase 0 optimisations");
    expect(page).toContain("Waiting for the evidence of its real test.");
  });
});

describe("a server that sends no envelopes", () => {
  test("there is nothing to draw: the view shows its note instead", () => {
    expect(envelopesOf({})).toBeNull();
    expect(envelopesOf({ envelopes: {} })).toBeNull();
    for (const lang of ["es", "en"] as const) {
      setLocale(lang);
      expect(hasKey("ai.layer.envelopes.empty")).toBe(true);
    }
  });
});
