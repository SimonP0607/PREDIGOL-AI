/// <reference types="bun" />
/**
 * PLAN F12, the model code against its promotions in Evolución: the plan's count ("1 de 2") and the code this server
 * runs against the one the ledger has in force; what changed since the ledger began, newest first, with the change
 * nobody decided shown as such; the promotion that covers a fingerprint (who, when, why, the evidence); the changes
 * older than the ledger listed apart and never counted; the six statuses in both languages; the ledger's own entries
 * (copied to the database? used?); the other promotions of the window; and the empty state.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import { localInt, localPct } from "@/lib/i18n/format";
import type {
  CodeFingerprint,
  CodeLedgerEntry,
  CodePromotions,
  CodeStatus,
} from "@/lib/api/v1/types_ai";
import { CodePromotionsBody } from "./CodePromotionsPanel";
import { producedText } from "./codeModel";
import { utcDateTime } from "./format";

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");

/** The formatters put a no-break space before a "%"; the text helper above turns every space into a plain one. */
const norm = (s: string) => s.replace(/\s+/g, " ");

function html(d: CodePromotions): string {
  return renderToStaticMarkup(<CodePromotionsBody d={d} />);
}

function render(d: CodePromotions): string {
  return text(html(d));
}

/** The markup of one fingerprint's card, from its `<li>` to the next one. */
function card(d: CodePromotions, fingerprint: string): string {
  const found = new RegExp(
    `<li[^>]*data-testid="code-fingerprint-${fingerprint}"[^>]*>(.*?)</li>`,
    "s",
  ).exec(html(d));
  if (!found) throw new Error(`the page has no card for ${fingerprint}`);
  return found[1] ?? "";
}

/** The part of the page between two test ids. */
function between(page: string, from: string, to: string): string {
  const start = page.indexOf(`data-testid="${from}"`);
  const end = page.indexOf(`data-testid="${to}"`, start);
  return start < 0 ? "" : page.slice(start, end < 0 ? undefined : end);
}

function fingerprint(
  code: string,
  status: CodeStatus,
  over: Partial<CodeFingerprint> = {},
): CodeFingerprint {
  return {
    fingerprint: code,
    status,
    appeared_at: "2026-10-22T13:04:00Z",
    last_use: "2026-10-24T06:51:00Z",
    in_force_now: false,
    versions: 3,
    models: ["dixon_coles", "elo_ologit", "poisson"],
    rows: { predictions: 298597 },
    promotion: null,
    ...over,
  };
}

const REASON =
  "Baseline of the ledger: the model code in force when it was started. It is the code of plan F0, in production since 22 Oct 2026.";

const BASELINE_ROW: CodePromotions["fingerprints"][number]["promotion"] = {
  id: 120,
  decided_by: "system",
  decided_at: "2026-10-22T13:00:00Z",
  reason: REASON,
  evidence: { gate: "make check green on each release", deployed: "2026-10-22T13:04Z" },
};

/** Production on 24 Oct 2026, 07:00 UTC (`promotion_trace show`): the baseline, the accidental fingerprint and five older ones. */
const FINGERPRINTS: CodeFingerprint[] = [
  fingerprint("legacy", "PRE_LEDGER", {
    appeared_at: "2026-09-25T03:16:00Z",
    last_use: "2026-10-05T07:11:00Z",
    versions: 195,
    rows: { predictions: 823241 },
  }),
  fingerprint("mc034f19d4a9", "PRE_LEDGER", {
    appeared_at: "2026-10-05T07:19:00Z",
    last_use: "2026-10-05T07:30:00Z",
    rows: { predictions: 12006 },
  }),
  fingerprint("mcec6b780838", "PRE_LEDGER", {
    appeared_at: "2026-10-05T08:11:00Z",
    last_use: "2026-10-18T07:14:00Z",
    rows: { decisions: 1, predictions: 187234 },
  }),
  fingerprint("mc1f28a88360", "PRE_LEDGER", {
    appeared_at: "2026-10-09T04:02:00Z",
    in_force_now: true,
    rows: { decisions: 20291, predictions: 1355886 },
  }),
  fingerprint("mc118f6f26d7", "PRE_LEDGER", {
    appeared_at: "2026-10-09T13:31:00Z",
    last_use: "2026-10-09T13:31:00Z",
    rows: { predictions: 89585 },
  }),
  fingerprint("mc9a7bec97ca", "BASELINE", {
    in_force_now: true,
    rows: { decisions: 4867, forecasts: 4895, predictions: 298597 },
    promotion: BASELINE_ROW,
  }),
  fingerprint("mce0abbbb30d", "UNTRACED", {
    appeared_at: "2026-10-23T02:45:00Z",
    in_force_now: true,
    rows: { decisions: 4375, forecasts: 6806, predictions: 98211 },
  }),
];

const LEDGER: CodeLedgerEntry[] = [
  {
    fingerprint: "mc9a7bec97ca",
    decided_at: "2026-10-22T13:00:00Z",
    decided_by: "system",
    phase: "F0",
    reason: REASON,
    baseline: true,
    evidence: { gate: "make check green on each release" },
    recorded: true,
    used: true,
  },
];

function page(over: Partial<CodePromotions> = {}): CodePromotions {
  return {
    now: "2026-10-24T07:00:47Z",
    since: "2026-09-24T07:00:47Z",
    days: 30,
    running_code: "mc9a7bec97ca",
    ledger_in_force: "mc9a7bec97ca",
    ledger_since: "2026-10-22T13:00:00Z",
    in_force_matches_running: true,
    fingerprints: FINGERPRINTS,
    counts: {
      fingerprints: 7,
      counted: 2,
      traced: 1,
      untraced: 1,
      pending_sync: 0,
      after_use: 0,
      pre_ledger: 5,
    },
    coverage: 0.5,
    ledger: LEDGER,
    other: { calibrator: 108, goal_spec: 1, market_edge: 11, neutral_rule: 0 },
    ...over,
  };
}

const STATUSES: CodeStatus[] = [
  "BASELINE",
  "PROMOTED",
  "AFTER_USE",
  "PENDING_SYNC",
  "UNTRACED",
  "PRE_LEDGER",
];

afterEach(() => setLocale("es"));

describe("the model code against its promotions", () => {
  test("gives the plan's count and the code the server runs against the one the ledger has in force", () => {
    setLocale("es");
    const out = render(page());
    expect(out).toContain("Cambios con promoción");
    expect(out).toContain("1 de 2");
    expect(out).toContain(
      `${norm(localPct(0.5, 0))} de los cambios de código desde que empezó el registro`,
    );
    expect(out).toContain("La meta del plan es el 100 %.");
    expect(out).toContain("Código que corre ahora mc9a7bec97ca");
    expect(out).toContain("Es el que el registro tiene en vigor.");
    expect(out).toContain("Huellas en la ventana 7");
    expect(out).toContain("5 anteriores al registro: se listan y no cuentan.");
    expect(out).toContain(`Registro iniciado ${utcDateTime("2026-10-22T13:00:00Z")}`);
    expect(out).toContain("Ventana de 30 días hacia atrás.");
    expect(out).toContain(`Medido ${utcDateTime("2026-10-24T07:00:47Z")}`);
  });

  test("the count is red while a change has no promotion, amber while one is only waiting, green at 100 %", () => {
    setLocale("es");
    const tile = (p: CodePromotions) => /<dd class="([^"]*)">1 de 2<\/dd>/.exec(html(p))?.[1] ?? "";
    expect(tile(page())).toContain("text-negative");
    const waiting = page({
      counts: { ...page().counts, untraced: 0, pending_sync: 1 },
      coverage: 0.5,
    });
    expect(tile(waiting)).toContain("text-warning");
    const whole = page({
      counts: { ...page().counts, untraced: 0, traced: 2 },
      coverage: 1,
    });
    const full = /<dd class="([^"]*)">2 de 2<\/dd>/.exec(html(whole))?.[1] ?? "";
    expect(full).toContain("text-positive");
    expect(render(whole)).toContain(`${norm(localPct(1, 0))} de los cambios de código`);
  });

  test("lists what changed since the ledger began, the newest first, and says plainly that nobody decided the accidental one", () => {
    setLocale("es");
    const d = page();
    const counted = between(html(d), "code-counted", "code-before");
    expect(counted.indexOf("code-fingerprint-mce0abbbb30d")).toBeGreaterThan(-1);
    expect(counted.indexOf("code-fingerprint-mce0abbbb30d")).toBeLessThan(
      counted.indexOf("code-fingerprint-mc9a7bec97ca"),
    );
    const untraced = card(d, "mce0abbbb30d");
    expect(html(d)).toContain('data-status="UNTRACED"');
    expect(text(untraced)).toContain("mce0abbbb30d Sin promoción");
    expect(untraced).toContain("text-negative");
    expect(text(untraced)).toContain(
      "Ninguna decisión lo cubre: es el cambio que el plan dice que no debe ocurrir.",
    );
    expect(text(untraced)).toContain("Ninguna decisión registrada cubre este código.");
    expect(text(untraced)).toContain("3 versiones de dixon_coles, elo_ologit, poisson");
    expect(text(untraced)).toContain(
      `predicciones ${localInt(98211)} · pronósticos ${localInt(6806)} · decisiones ${localInt(4375)}`,
    );
    expect(text(untraced)).toContain(`Apareció ${utcDateTime("2026-10-23T02:45:00Z")}`);
    expect(text(untraced)).toContain(`último uso ${utcDateTime("2026-10-24T06:51:00Z")}`);
  });

  test("a fingerprint the server runs says so; one only used lately says that, and not that it is in force", () => {
    setLocale("es");
    const d = page();
    const running = text(card(d, "mc9a7bec97ca"));
    expect(running).toContain("Corre ahora");
    expect(running).not.toContain("Usado en los últimos 2 días");
    const lately = text(card(d, "mce0abbbb30d"));
    expect(lately).toContain("Usado en los últimos 2 días");
    expect(lately).not.toContain("Corre ahora");
    // the code that runs is not the ledger's: nobody is told "Corre ahora" about the ledger's own
    const drifted = page({ running_code: "mcffffffffff", in_force_matches_running: false });
    expect(html(drifted).split("Corre ahora").length - 1).toBe(0);
  });

  test("the promotion that covers a fingerprint shows who decided it, when, why and on what evidence", () => {
    setLocale("es");
    const covered = card(page(), "mc9a7bec97ca");
    const out = text(covered);
    expect(out).toContain(
      `Promoción n.º 120 · decidida por system · ${utcDateTime("2026-10-22T13:00:00Z")}`,
    );
    expect(out).toContain(REASON);
    expect(out).toContain("Base del registro");
    expect(out).toContain("El código que ya estaba en vigor cuando empezó el registro");
    expect(covered).toContain("text-info");
    // the evidence is kept whole, for whoever opens it
    expect(covered).toContain("<details");
    expect(covered).toContain("make check green on each release");
    expect(covered).toContain("2026-10-22T13:04Z");
    expect(out).not.toContain("Ninguna decisión registrada cubre este código.");
  });

  test("the changes older than the ledger are listed apart, said not to count, and the commit-keyed ones say what they are", () => {
    setLocale("es");
    const d = page();
    const before = html(d).slice(html(d).indexOf('data-testid="code-before"'));
    const beforeText = text(before.slice(0, before.indexOf('data-testid="code-ledger"')));
    expect(beforeText).toContain("Anteriores al registro · 5");
    expect(beforeText).toContain("el pasado no se puede decidir después");
    for (const code of ["mc034f19d4a9", "mcec6b780838", "mc1f28a88360", "mc118f6f26d7"]) {
      expect(before).toContain(`code-fingerprint-${code}`);
    }
    expect(beforeText).toContain("Versiones por commit (antes del 5 de octubre de 2026)");
    expect(beforeText).toContain("195 versiones de dixon_coles, elo_ologit, poisson");
    // none of them is in the counted section, and none is called "sin promoción": they are not changes the plan counts
    const counted = between(html(d), "code-counted", "code-before");
    for (const code of ["legacy", "mc034f19d4a9", "mcec6b780838", "mc1f28a88360", "mc118f6f26d7"]) {
      expect(counted).not.toContain(`code-fingerprint-${code}`);
    }
    expect(text(card(d, "mc1f28a88360"))).not.toContain(
      "Ninguna decisión registrada cubre este código.",
    );
    expect(text(card(d, "mc1f28a88360"))).toContain("Anterior al registro");
  });

  test("a window with nothing before the ledger draws no such section, and one with no change says so", () => {
    setLocale("es");
    const lone = page({
      fingerprints: [FINGERPRINTS[5] as CodeFingerprint],
      counts: {
        fingerprints: 1,
        counted: 1,
        traced: 1,
        untraced: 0,
        pending_sync: 0,
        after_use: 0,
        pre_ledger: 0,
      },
      coverage: 1,
    });
    const out = render(lone);
    expect(html(lone)).not.toContain('data-testid="code-before"');
    expect(out).toContain("Todas son posteriores al inicio del registro.");
    expect(out).toContain("1 de 1");
    const quiet = page({
      fingerprints: [],
      counts: {
        fingerprints: 0,
        counted: 0,
        traced: 0,
        untraced: 0,
        pending_sync: 0,
        after_use: 0,
        pre_ledger: 0,
      },
      coverage: null,
    });
    const nothing = render(quiet);
    expect(nothing).toContain("Cambios con promoción Ninguno");
    expect(nothing).toContain("No hubo cambios de código desde que empezó el registro.");
    expect(nothing).toContain(
      "Ningún código pronosticó en la ventana desde que empezó el registro.",
    );
    expect(html(quiet)).toContain("text-muted-foreground");
  });

  test("the code that runs not being the ledger's is said in an amber tile, with the code the ledger has", () => {
    setLocale("es");
    const drifted = page({ running_code: "mcffffffffff", in_force_matches_running: false });
    const out = render(drifted);
    expect(out).toContain("Código que corre ahora mcffffffffff");
    expect(out).toContain("No es el que el registro tiene en vigor (mc9a7bec97ca).");
    expect(/<dd class="([^"]*)">mcffffffffff<\/dd>/.exec(html(drifted))?.[1]).toContain(
      "text-warning",
    );
    expect(/<dd class="([^"]*)">mc9a7bec97ca<\/dd>/.exec(html(page()))?.[1]).not.toContain(
      "text-warning",
    );
  });

  test("each of the six statuses has its own words and tone in both languages", () => {
    const expected: Record<CodeStatus, { es: string; en: string; tone: string }> = {
      BASELINE: { es: "Base del registro", en: "Ledger baseline", tone: "text-info" },
      PROMOTED: { es: "Promovido", en: "Promoted", tone: "text-positive" },
      AFTER_USE: { es: "Decidido después", en: "Decided after use", tone: "text-warning" },
      PENDING_SYNC: { es: "Sin copiar a la base", en: "Not copied yet", tone: "text-warning" },
      UNTRACED: { es: "Sin promoción", en: "No promotion", tone: "text-negative" },
      PRE_LEDGER: {
        es: "Anterior al registro",
        en: "Older than the ledger",
        tone: "text-muted-foreground",
      },
    };
    for (const status of STATUSES) {
      expect(hasKey(`ai.evolution.code.status.${status}`)).toBe(true);
      expect(hasKey(`ai.evolution.code.statusHelp.${status}`)).toBe(true);
      const d = page({
        fingerprints: [fingerprint("mc0123456789", status)],
        counts: { ...page().counts, fingerprints: 1 },
      });
      for (const locale of ["es", "en"] as const) {
        setLocale(locale);
        const one = card(d, "mc0123456789");
        expect(text(one)).toContain(expected[status][locale]);
        expect(one).toContain(expected[status].tone);
      }
    }
  });

  test("the ledger's own entries say whether they are in the database and whether production used them, newest first", () => {
    setLocale("es");
    const next: CodeLedgerEntry = {
      fingerprint: "mc1234567890",
      decided_at: "2026-10-26T10:00:00Z",
      decided_by: "owner",
      phase: "F12",
      reason:
        "A decision a person can look back on, longer than the forty characters the ledger asks for.",
      baseline: false,
      evidence: { hypothesis_id: 5, experiment_ids: [7, 8] },
      recorded: false,
      used: false,
    };
    const d = page({ ledger: [...LEDGER, next] });
    const ledger = html(d).slice(html(d).indexOf('data-testid="code-ledger"'));
    expect(ledger.indexOf("code-ledger-mc1234567890")).toBeLessThan(
      ledger.indexOf("code-ledger-mc9a7bec97ca"),
    );
    const pending = text(
      /<li[^>]*code-ledger-mc1234567890[^>]*>(.*?)<\/li>/s.exec(ledger)?.[1] ?? "",
    );
    expect(pending).toContain("Sin copiar a la base");
    expect(pending).toContain("Aún sin usar");
    expect(pending).toContain(
      `Decidida por owner · fase F12 · ${utcDateTime("2026-10-26T10:00:00Z")}`,
    );
    expect(pending).not.toContain("Base del registro");
    const first = text(
      /<li[^>]*code-ledger-mc9a7bec97ca[^>]*>(.*?)<\/li>/s.exec(ledger)?.[1] ?? "",
    );
    expect(first).toContain("Base del registro");
    expect(first).toContain("Copiada a la base");
    expect(first).toContain("Usada en la ventana");
    expect(ledger).toContain("hypothesis_id");
    expect(render(page({ ledger: [] }))).toContain("El registro está vacío.");
  });

  test("the other promotions of the window are listed by name in the plan's order, a zero stays a zero", () => {
    setLocale("es");
    const out = text(between(html(page()), "code-other", "never-there"));
    const order = [
      "Calibradores 108",
      "Especificación de goles 1",
      "Ventaja sobre el mercado 11",
      "Regla de sede neutral 0",
    ].map((s) => out.indexOf(s));
    expect(order.every((at) => at >= 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(render(page({ other: { ...page().other, novel_kind: 3 } }))).toContain("novel_kind 3");
    expect(html(page({ other: {} }))).not.toContain('data-testid="code-other"');
  });

  test("what a fingerprint produced is read in the plan's order, whatever order the server sends it", () => {
    setLocale("es");
    expect(producedText({ decisions: 4867, predictions: 298597, forecasts: 4895 })).toBe(
      `predicciones ${localInt(298597)} · pronósticos ${localInt(4895)} · decisiones ${localInt(4867)}`,
    );
    expect(producedText({ zeta: 1, predictions: 2, alfa: 3 })).toBe(
      `predicciones 2 · alfa 3 · zeta 1`,
    );
    setLocale("en");
    expect(producedText({ decisions: 4867, forecasts: 3 })).toBe(
      `forecasts 3 · decisions ${localInt(4867)}`,
    );
  });

  test("in English it is the same page in English words", () => {
    setLocale("en");
    const out = render(page());
    expect(out).toContain("Changes with a promotion");
    expect(out).toContain("1 of 2");
    expect(out).toContain("Code running now mc9a7bec97ca");
    expect(out).toContain("It is the one the ledger has in force.");
    expect(out).toContain("5 older than the ledger: listed, not counted.");
    expect(out).toContain("Older than the ledger · 5");
    expect(out).toContain("Commit-keyed versions (before 5 October 2026)");
    expect(out).toContain("No decision on record covers this code.");
    expect(out).toContain("Promotion no. 120 · decided by system");
    expect(out).toContain("Ledger decisions");
    expect(out).toContain("Other promotions in the window");
    expect(out).toContain("Calibrators 108");
    expect(out).toContain("Neutral-venue rule 0");
    expect(out).toContain("Looking at this screen changes nothing.");
    expect(out).not.toContain("Cambios con promoción");
  });

  test("it only reads: the page has no form, no input and no button of its own", () => {
    setLocale("es");
    const out = html(page());
    expect(out).not.toMatch(/<(form|input|textarea|select|button)\b/);
    expect(text(out)).toContain("Mirar esta pantalla no cambia nada.");
  });
});
