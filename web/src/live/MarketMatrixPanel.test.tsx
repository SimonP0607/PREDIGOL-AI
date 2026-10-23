/// <reference types="bun" />
/**
 * PLAN F9, the matrix of markets by family in the Admin Console: the kinds of bet under their group, the verdict each
 * earned with its reason in both languages, the priority only where the plan puts it (POR INVESTIGAR), a figure the
 * matrix could not make as a dash (never a zero) while a zero that was measured stays a zero, an estimated price
 * marked as such, the empty state before the first matrix is stored, the note on cards and the competitions list.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { hasKey, setLocale } from "@/lib/i18n";
import { localFixed, localInt, localPct } from "@/lib/i18n/format";
import type {
  IntelMarketMatrix,
  IntelMatrixCompetition,
  IntelMatrixRow,
} from "@/lib/api/v1/types_intel";
import { bogotaDateTime } from "./aiModel";
import { MarketMatrixBody } from "./MarketMatrixPanel";

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");
/** The formatters put a no-break space before a "%"; the text helper above turns every space into a plain one. */
const norm = (s: string) => s.replace(/\s+/g, " ");

function html(d: IntelMarketMatrix): string {
  return renderToStaticMarkup(<MarketMatrixBody d={d} />);
}

function render(d: IntelMarketMatrix): string {
  return text(html(d));
}

/** The markup of one row of the table, from its `<tr>` to the next one. */
function rowHtml(d: IntelMarketMatrix, key: string): string {
  const found = new RegExp(
    `<tr[^>]*data-testid="intel-market-matrix-row-${key.replace(/\./g, "\\.")}"[^>]*>(.*?)</tr>`,
    "s",
  ).exec(html(d));
  if (!found) throw new Error(`the table has no row ${key}`);
  return found[1] ?? "";
}

/** The cells of one row of the table, each as plain text. */
function cells(d: IntelMarketMatrix, key: string): string[] {
  return [...rowHtml(d, key).matchAll(/<td[^>]*>(.*?)<\/td>/gs)].map((c) =>
    text(c[1] ?? "").trim(),
  );
}

/** The classes of the verdict badge of a row (the first badge in it). */
function verdictBadge(d: IntelMarketMatrix, key: string): string {
  return /<span class="(inline-flex[^"]*)"/.exec(rowHtml(d, key))?.[1] ?? "";
}

/** The competitions block as rows of text: [name and country, finished, priced]. */
function competitionRows(d: IntelMarketMatrix): string[][] {
  const page = html(d);
  const start = page.indexOf('data-testid="intel-market-matrix-competitions"');
  if (start < 0) return [];
  const body = page.slice(page.indexOf("<tbody>", start));
  return [...body.matchAll(/<tr[^>]*>(.*?)<\/tr>/gs)].map((tr) =>
    [...(tr[1] ?? "").matchAll(/<td[^>]*>(.*?)<\/td>/gs)].map((c) => text(c[1] ?? "").trim()),
  );
}

const GROUPS: Record<string, string> = {
  A: "Resultado",
  B: "Goles",
  C: "Córners",
  D: "Tarjetas",
  E: "Jugadores",
  F: "Porteros",
  G: "Tiros, faltas y fueras de juego",
  H: "Futuros",
  Z: "Otros",
};

const GROUPS_EN: Record<string, string> = {
  A: "Result",
  B: "Goals",
  C: "Corners",
  D: "Cards",
  E: "Players",
  F: "Goalkeepers",
  G: "Shots, fouls and offsides",
  H: "Futures",
  Z: "Other",
};

type RowSeed = Partial<IntelMatrixRow> &
  Pick<IntelMatrixRow, "key" | "group" | "label" | "label_en">;

function row(seed: RowSeed): IntelMatrixRow {
  return {
    parent: null,
    bets: [1],
    extracted_bets: [1],
    api: true,
    rules: ["goals_ft@v1"],
    reasons: { ok: 1 },
    curated: false,
    results: {
      measures: ["goals_ft"],
      n_window: 8812,
      pct: 0.9791,
      pct_by_type: { league: 0.98, cup: 0.97 },
      n_total: 230112,
      since: "2018-08-11T00:00:00Z",
    },
    price: {
      source: "price_clock",
      fixtures: 412,
      base_fixtures: 430,
      coverage: 0.9581,
      houses_median: 10,
      since: "2026-09-25T04:10:00Z",
      extracted: 1,
    },
    model: { keys: [], enabled: false, calibrated: 0, decisions_14d: 0, edge: null },
    verdict: "NO VIABLE",
    priority: "",
    reason: "no_data",
    ...seed,
  };
}

/** No price at all: the platform stores none of this row's bets and no discovery run has seen them. */
const UNPRICED: IntelMatrixRow["price"] = {
  source: "price_clock",
  fixtures: 0,
  base_fixtures: 430,
  coverage: null,
  houses_median: null,
  since: null,
  extracted: 0,
};

/** No LISTO anywhere (no market has a validated edge), one PARCIAL, three POR INVESTIGAR, six NO VIABLE. */
const ROWS: IntelMatrixRow[] = [
  row({
    key: "result.1x2",
    group: "A",
    label: "1X2",
    label_en: "Match winner",
    verdict: "PARCIAL",
    reason: "edge_not_validated",
    model: {
      keys: ["1X2"],
      enabled: true,
      calibrated: 3,
      decisions_14d: 420,
      edge: "NOT_VALIDATED",
    },
  }),
  row({
    key: "goals_half.over_under",
    group: "B",
    label: "Goles 1.ª / 2.ª parte: Over/Under",
    label_en: "Half goals: over/under",
    bets: [6, 26],
    extracted_bets: [6, 26],
    verdict: "POR INVESTIGAR",
    priority: "alta",
    reason: "priced",
    price: {
      source: "price_clock",
      fixtures: 405,
      base_fixtures: 430,
      coverage: 0.9419,
      houses_median: 6,
      since: "2026-09-25T04:10:00Z",
      extracted: 2,
    },
  }),
  row({
    key: "goals_half.result",
    group: "B",
    label: "Goles por mitad: ganador, doble oportunidad y sin empate",
    label_en: "Half result, double chance, draw no bet",
    parent: "goals_half.over_under",
    bets: [13, 3, 20],
    extracted_bets: [13],
    verdict: "POR INVESTIGAR",
    priority: "baja",
    reason: "after_parent",
    price: {
      source: "price_clock",
      fixtures: 390,
      base_fixtures: 430,
      coverage: 0.907,
      houses_median: 1,
      since: "2026-09-25T04:10:00Z",
      extracted: 1,
    },
  }),
  row({
    key: "goals.team_total",
    group: "B",
    label: "Total por equipo",
    label_en: "Team totals",
    bets: [16, 17],
    curated: true,
    reason: "rejected_backtest",
  }),
  row({
    key: "corners.half",
    group: "C",
    label: "Córners 1.ª / 2.ª parte",
    label_en: "Corners by half",
    bets: [77, 84],
    extracted_bets: [],
    rules: ["corners_1h@v1"],
    reasons: { no_period_data: 2 },
    reason: "no_period_data",
    results: null,
    price: {
      source: "discovery",
      fixtures: 3100,
      base_fixtures: 430,
      coverage: null,
      houses_median: 3.5,
      since: null,
      extracted: 0,
    },
  }),
  row({
    key: "cards.total",
    group: "D",
    label: "Tarjetas: total (Over/Under, hándicap)",
    label_en: "Cards: total",
    bets: [80, 79, 81],
    extracted_bets: [80, 79],
    verdict: "POR INVESTIGAR",
    priority: "media",
    reason: "priced",
    price: {
      source: "price_clock",
      fixtures: 150,
      base_fixtures: 430,
      coverage: 0.3488,
      houses_median: 3,
      since: "2026-09-25T04:10:00Z",
      extracted: 2,
    },
  }),
  row({
    key: "players",
    group: "E",
    label: "Goleador, tiros, tiros a puerta, asistencia y tarjeta de jugador",
    label_en: "Player props",
    bets: [92, 93, 94],
    extracted_bets: [],
    reason: "player_level",
    results: null,
    price: UNPRICED,
  }),
  row({
    key: "shots.total",
    group: "G",
    label: "Tiros totales (equipo)",
    label_en: "Team shots",
    bets: [211, 220],
    extracted_bets: [211, 220],
    reason: "no_prices_in_window",
    results: {
      measures: ["shots_ft"],
      n_window: 6120,
      pct: 0.6801,
      pct_by_type: {},
      n_total: null,
      since: null,
    },
    price: {
      source: "price_clock",
      fixtures: 0,
      base_fixtures: 430,
      coverage: 0,
      houses_median: null,
      since: null,
      extracted: 2,
    },
  }),
  row({
    key: "futures",
    group: "H",
    label: "Campeón, descenso y otros futuros",
    label_en: "Futures",
    bets: [],
    extracted_bets: [],
    api: false,
    rules: [],
    reasons: {},
    curated: true,
    reason: "not_offered",
    results: null,
    price: UNPRICED,
  }),
  row({
    key: "timing",
    group: "Z",
    label: "Tiempos (primer gol, minuto del gol...)",
    label_en: "Timing",
    bets: [30, 31],
    extracted_bets: [],
    reason: "out_of_scope",
    results: null,
    price: UNPRICED,
  }),
];

function competitions(): IntelMatrixCompetition[] {
  // Seventeen, the smallest first, one of them without a name: the panel must sort them and keep fifteen.
  return Array.from({ length: 17 }, (_, n) => 16 - n).map((i) => ({
    competition_id: 100 + i,
    name: i === 3 ? null : `Liga ${i + 1}`,
    country: i === 3 ? null : "Colombia",
    type: "league",
    finished: 1000 - i * 10,
    priced: 40 - i,
    results: {},
    price: {},
  }));
}

function matrix(over: Partial<IntelMarketMatrix> = {}): IntelMarketMatrix {
  return {
    run: {
      id: 7,
      generated_at: "2026-10-19T09:00:00Z",
      matrix_version: "matrix-v1",
      taxonomy_version: "tax-v1",
      window_days: 8,
      duration_ms: 41_500,
    },
    current_version: "matrix-v1",
    groups: GROUPS,
    keys: { keys: 62, followed: 21, modelled: 5 },
    rules: { rules: 21, can_grade: 18 },
    rows: ROWS,
    coverage: {
      results_days: 365,
      price_days: 8,
      totals: { finished: 9000, priced: 430 },
      competitions: competitions(),
    },
    summary: {
      by_verdict: { PARCIAL: 1, "POR INVESTIGAR": 3, "NO VIABLE": 6 },
      by_priority: { alta: 1, media: 1, baja: 1 },
      definitions: 338,
      extracted: 41,
      with_rule: 120,
      rules: 21,
      liquidable_rules: 18,
      cards: {
        matches_with_events: 4210,
        matches_with_a_dismissal: 308,
        convention_sensitive_pct: 0.0732,
        events_vs_statistics_compared: 3980,
        events_equal_statistics_pct: 0.9412,
      },
    },
    ...over,
  };
}

/** What the endpoint answers before the weekly job (or `scripts.markets matrix --store`) has stored a matrix. */
const NOTHING_STORED: Partial<IntelMarketMatrix> = {
  run: null,
  rows: [],
  coverage: null,
  summary: null,
};

function withCards(cards: NonNullable<IntelMarketMatrix["summary"]>["cards"]): IntelMarketMatrix {
  const base = matrix();
  return matrix({ summary: { ...(base.summary as NonNullable<typeof base.summary>), cards } });
}

afterEach(() => setLocale("es"));

describe("the matrix of markets", () => {
  test("puts every kind of bet under its group, in order, with a row of its own", () => {
    setLocale("es");
    const page = html(matrix());
    expect(page).toContain('data-testid="intel-market-matrix"');
    for (const r of ROWS) expect(page).toContain(`data-testid="intel-market-matrix-row-${r.key}"`);
    const out = text(page);
    const heads = [
      "A · Resultado",
      "B · Goles",
      "C · Córners",
      "D · Tarjetas",
      "E · Jugadores",
      "G · Tiros, faltas y fueras de juego",
      "H · Futuros",
      "Z · Otros",
    ];
    let last = -1;
    for (const head of heads) {
      const at = out.indexOf(head);
      expect(at).toBeGreaterThan(last);
      last = at;
    }
    // F (porteros) has no row in this matrix: no empty group is drawn.
    expect(out).not.toContain("F · Porteros");
    // A row sits in the group it belongs to.
    const fromB = page.slice(page.indexOf('data-testid="intel-market-matrix-group-B"'));
    const inB = fromB.slice(0, fromB.indexOf('data-testid="intel-market-matrix-group-C"'));
    expect(inB).toContain("intel-market-matrix-row-goals.team_total");
    expect(inB).not.toContain("intel-market-matrix-row-corners.half");
  });

  test("a group letter the server sends keeps the server's name, or stands alone without one", () => {
    setLocale("es");
    const odd = row({ key: "novel", group: "Q", label: "Algo nuevo", label_en: "Something new" });
    expect(
      render(matrix({ rows: [...ROWS, odd], groups: { ...GROUPS, Q: "Experimentos" } })),
    ).toContain("Q · Experimentos");
    const nameless = render(matrix({ rows: [...ROWS, odd] }));
    expect(nameless).toContain("Q Algo nuevo");
    expect(nameless).not.toContain("Q ·");
  });

  test("says when it was generated, how many keys and rules exist and what the provider offers", () => {
    setLocale("es");
    const out = render(matrix());
    expect(out).toContain("Generada (hora de Bogotá)");
    expect(out).toContain(bogotaDateTime("2026-10-19T09:00:00Z"));
    expect(out).toContain("Versión matrix-v1 · taxonomía tax-v1");
    expect(out).toContain(`Claves en el catálogo ${localInt(62)} 21 seguidas, 5 modeladas`);
    expect(out).toContain(`Reglas de liquidación ${localInt(21)} 18 pueden liquidar`);
    expect(out).toContain(
      `Apuestas del proveedor ${localInt(338)} 41 con precio guardado, 120 con regla de liquidación`,
    );
  });

  test("counts the verdicts from the rows, LISTO at zero because nobody has earned it", () => {
    setLocale("es");
    const strip = text(html(matrix()).split("intel-market-matrix-verdicts")[1] ?? "");
    const order = ["Listo 0", "Parcial 1", "Por investigar 3", "No viable 6"].map((s) =>
      strip.indexOf(s),
    );
    expect(order.every((at) => at >= 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  test("a verdict is a badge in its own tone: LISTO positive, PARCIAL info, POR INVESTIGAR warning, NO VIABLE neutral", () => {
    setLocale("es");
    const ready = row({ key: "r", group: "A", label: "R", label_en: "R", verdict: "LISTO" });
    const d = matrix({ rows: [...ROWS, ready] });
    expect(cells(d, "result.1x2")[1]).toBe("Parcial");
    expect(cells(d, "r")[1]).toBe("Listo");
    expect(verdictBadge(d, "r")).toContain("text-positive");
    expect(verdictBadge(d, "result.1x2")).toContain("text-info");
    expect(verdictBadge(d, "goals_half.over_under")).toContain("text-warning");
    expect(verdictBadge(d, "goals.team_total")).toContain("text-muted-foreground");
  });

  test("the priority is shown next to POR INVESTIGAR and nowhere else", () => {
    setLocale("es");
    const d = matrix();
    expect(cells(d, "goals_half.over_under")[1]).toBe("Por investigar Prioridad alta");
    expect(cells(d, "goals_half.result")[1]).toBe("Por investigar Prioridad baja");
    expect(cells(d, "cards.total")[1]).toBe("Por investigar Prioridad media");
    expect(cells(d, "result.1x2")[1]).toBe("Parcial");
    // A priority on any other verdict is not drawn.
    const stray = matrix({
      rows: [row({ key: "x", group: "A", label: "X", label_en: "X", priority: "alta" })],
    });
    expect(cells(stray, "x")[1]).toBe("No viable");
    setLocale("en");
    expect(cells(d, "goals_half.over_under")[1]).toBe("To investigate High priority");
    expect(cells(d, "cards.total")[1]).toBe("To investigate Medium priority");
  });

  test("says why, in the reader's language", () => {
    setLocale("es");
    const d = matrix();
    expect(cells(d, "corners.half")[2]).toBe("no hay dato por mitad: no se puede liquidar");
    expect(cells(d, "goals_half.over_under")[2]).toBe("con precio y resultados: se puede medir");
    expect(cells(d, "goals_half.result")[2]).toBe("se mide después del total");
    expect(cells(d, "players")[2]).toBe("se liquida con datos de un jugador");
    expect(cells(d, "timing")[2]).toBe("fuera del plan (tiempo, especiales, otros deportes)");
    expect(cells(d, "shots.total")[2]).toBe("sin precios esta semana");
    expect(cells(d, "result.1x2")[2]).toBe("modelada, sin ventaja validada");
    setLocale("en");
    expect(cells(d, "corners.half")[2]).toBe("no per-half data: it cannot be settled");
    expect(cells(d, "goals_half.over_under")[2]).toBe(
      "priced and with results: it can be measured",
    );
    expect(cells(d, "players")[2]).toBe("settled on one player's figures");
    expect(cells(d, "shots.total")[2]).toBe("no prices this week");
  });

  test("a verdict set by hand says so; one the data gave does not", () => {
    setLocale("es");
    const d = matrix();
    expect(cells(d, "goals.team_total")[2]).toBe("rechazada por el backtest (fijado a mano)");
    expect(cells(d, "futures")[2]).toBe("el proveedor no la ofrece (fijado a mano)");
    expect(cells(d, "players")[2]).not.toContain("fijado a mano");
    setLocale("en");
    expect(cells(d, "goals.team_total")[2]).toBe("rejected by the backtest (set by hand)");
  });

  test("a reason or a verdict the interface has no word for is shown as the server sent it", () => {
    setLocale("es");
    const d = matrix({
      rows: [
        row({
          key: "novel",
          group: "A",
          label: "Algo nuevo",
          label_en: "Something new",
          reason: "brand_new_reason",
          // A verdict outside the four of the plan.
          verdict: "EN PAUSA" as unknown as IntelMatrixRow["verdict"],
        }),
      ],
    });
    const c = cells(d, "novel");
    expect(c[1]).toBe("EN PAUSA");
    expect(c[2]).toBe("brand_new_reason");
    // It is counted too, after the four of the plan.
    expect(render(d)).toContain("EN PAUSA 1");
  });

  test("a figure the matrix could not make is a dash, never a zero", () => {
    setLocale("es");
    const d = matrix();
    // The futures nobody offers: no bets, no results, no price, no model.
    expect(cells(d, "futures")).toEqual([
      "Campeón, descenso y otros futuros",
      "No viable",
      "el proveedor no la ofrece (fijado a mano)",
      "0 / 0",
      "—",
      "—",
      "—",
    ]);
    // The players and the timing: the platform stores none of their prices and nothing settles them.
    expect(cells(d, "players").slice(3)).toEqual(["0 / 3", "—", "—", "—"]);
    expect(cells(d, "timing").slice(4)).toEqual(["—", "—", "—"]);
  });

  test("a houses median or a coverage that is null is a dash inside a price that was measured", () => {
    setLocale("es");
    const d = matrix({
      rows: [
        row({
          key: "half",
          group: "B",
          label: "Mitades",
          label_en: "Halves",
          results: null,
          price: {
            source: "price_clock",
            fixtures: 12,
            base_fixtures: 0,
            coverage: null,
            houses_median: null,
            since: null,
            extracted: 1,
          },
        }),
      ],
    });
    const c = cells(d, "half");
    expect(c[4]).toBe(`Partidos ${localInt(12)} Casas — Cobertura —`);
    expect(c[5]).toBe("—");
  });

  test("a zero that was measured is a zero: prices were looked for and none was found", () => {
    setLocale("es");
    const c = cells(matrix(), "shots.total");
    expect(c[4]).toBe(`Partidos 0 Casas — Cobertura ${norm(localPct(0, 1))}`);
    expect(c[5]).toBe(`Partidos ${localInt(6120)} Del total ${norm(localPct(0.6801, 1))}`);
  });

  test("prices, results and bets are shown with their sizes", () => {
    setLocale("es");
    const d = matrix();
    const c = cells(d, "result.1x2");
    expect(c[3]).toBe("1 / 1");
    expect(c[4]).toBe(
      `Partidos ${localInt(412)} Casas ${localInt(10)} Cobertura ${norm(localPct(0.9581, 1))}`,
    );
    expect(c[4]).not.toContain("estimado");
    expect(c[5]).toBe(`Partidos ${localInt(8812)} Del total ${norm(localPct(0.9791, 1))}`);
    // The bets column is "with a stored price / all the provider offers".
    expect(cells(d, "goals_half.result")[3]).toBe("1 / 3");
    expect(cells(d, "cards.total")[3]).toBe("2 / 3");
    setLocale("en");
    expect(cells(d, "result.1x2")[4]).toBe(
      `Matches ${localInt(412)} Houses ${localInt(10)} Coverage ${localPct(0.9581, 1)}`,
    );
  });

  test("a median of houses that falls between two whole houses keeps its half", () => {
    setLocale("es");
    expect(cells(matrix(), "corners.half")[4]).toContain(`Casas ${localFixed(3.5, 1)}`);
    setLocale("en");
    expect(cells(matrix(), "corners.half")[4]).toContain("Houses 3.5");
  });

  test("a price from the discovery run is marked as an estimate", () => {
    setLocale("es");
    const d = matrix();
    expect(cells(d, "corners.half")[4]).toBe(
      `Partidos ${localInt(3100)} Casas ${localFixed(3.5, 1)} Cobertura — estimado`,
    );
    expect(cells(d, "result.1x2")[4]).not.toContain("estimado");
    setLocale("en");
    expect(cells(d, "corners.half")[4]).toEndWith("estimated");
  });

  test("a kind of bet measured after its parent is indented under it", () => {
    setLocale("es");
    const d = matrix();
    expect(cells(d, "goals_half.result")[0]).toBe(
      "↳ Goles por mitad: ganador, doble oportunidad y sin empate",
    );
    expect(cells(d, "goals_half.over_under")[0]).toBe("Goles 1.ª / 2.ª parte: Over/Under");
    const child = rowHtml(d, "goals_half.result");
    expect(child.slice(0, child.indexOf("</td>"))).toContain("pl-4");
    const parent = rowHtml(d, "goals_half.over_under");
    expect(parent.slice(0, parent.indexOf("</td>"))).not.toContain("pl-4");
  });

  test("a model shows that it exists and whether its edge is validated", () => {
    setLocale("es");
    const d = matrix();
    expect(cells(d, "result.1x2")[6]).toBe("Modelado sin ventaja validada");
    expect(cells(d, "goals_half.over_under")[6]).toBe("—");
    const modelled = matrix({
      rows: [
        row({
          key: "v",
          group: "A",
          label: "V",
          label_en: "V",
          verdict: "LISTO",
          reason: "edge_validated",
          model: { keys: ["V"], enabled: true, calibrated: 1, decisions_14d: 9, edge: "VALIDATED" },
        }),
        row({
          key: "w",
          group: "A",
          label: "W",
          label_en: "W",
          verdict: "PARCIAL",
          reason: "edge_not_validated",
          model: { keys: ["W"], enabled: true, calibrated: 0, decisions_14d: 0, edge: null },
        }),
      ],
    });
    expect(cells(modelled, "v")[1]).toBe("Listo");
    expect(cells(modelled, "v")[2]).toBe("con ventaja validada");
    expect(cells(modelled, "v")[6]).toBe("Modelado ventaja validada");
    expect(cells(modelled, "w")[6]).toBe("Modelado ventaja sin evaluar");
    setLocale("en");
    expect(cells(modelled, "v")[6]).toBe("Modelled edge validated");
    expect(cells(modelled, "w")[6]).toBe("Modelled edge not assessed");
    expect(cells(d, "result.1x2")[6]).toBe("Modelled edge not validated");
  });

  test("a matrix of an earlier version says it is renewed by the weekly run", () => {
    setLocale("es");
    expect(render(matrix())).not.toContain("versión anterior");
    const old = render(matrix({ current_version: "matrix-v2" }));
    expect(old).toContain("Matriz de una versión anterior (matrix-v1; la vigente es matrix-v2)");
    expect(old).toContain("se renueva con la corrida semanal");
    setLocale("en");
    expect(render(matrix({ current_version: "matrix-v2" }))).toContain(
      "Matrix from an earlier version (matrix-v1; the current one is matrix-v2)",
    );
  });

  test("with no matrix stored it says one is made every week, in both languages", () => {
    setLocale("es");
    const empty = html(matrix(NOTHING_STORED));
    expect(empty).toContain('data-testid="intel-market-matrix"');
    expect(empty).toContain('data-testid="intel-market-matrix-empty"');
    expect(empty).not.toContain("<table");
    expect(empty).not.toContain("intel-market-matrix-stats");
    expect(text(empty)).toContain(
      "Aún no hay una matriz guardada: se genera cada semana (o con python -m scripts.markets matrix --store).",
    );
    setLocale("en");
    const en = render(matrix(NOTHING_STORED));
    expect(en).toContain("No matrix has been stored yet: one is built every week");
    expect(en).not.toContain("Aún no hay");
  });

  test("a matrix that is stored shows no empty state", () => {
    setLocale("es");
    expect(html(matrix())).not.toContain("intel-market-matrix-empty");
  });

  test("states plainly that it only reads and decides nothing", () => {
    setLocale("es");
    expect(render(matrix())).toContain("Es solo lectura");
    setLocale("en");
    expect(render(matrix())).toContain("Reading only");
  });

  test("explains that the houses count cards differently, with the share of matches it touches", () => {
    setLocale("es");
    const page = html(matrix());
    expect(page).toContain("intel-market-matrix-cards");
    const out = text(page);
    expect(out).toContain("Las casas no cuentan las tarjetas igual");
    expect(out).toContain(
      `se liquidaría distinto el ${norm(localPct(0.0732, 1))} de los ${localInt(4210)} partidos con eventos de tarjeta`,
    );
    expect(out).toContain(
      `coinciden en el ${norm(localPct(0.9412, 1))} de los ${localInt(3980)} partidos`,
    );
    setLocale("en");
    expect(render(matrix())).toContain("Houses do not count cards the same way");
  });

  test("without matches that have card events there is nothing to explain about cards", () => {
    setLocale("es");
    const bare = withCards({
      matches_with_events: 0,
      matches_with_a_dismissal: 0,
      convention_sensitive_pct: null,
      events_vs_statistics_compared: 0,
      events_equal_statistics_pct: null,
    });
    expect(html(bare)).not.toContain("intel-market-matrix-cards");
    expect(render(bare)).not.toContain("Las casas no cuentan");
  });

  test("when no match could be compared, the cards note says nothing of events against statistics", () => {
    setLocale("es");
    const out = render(
      withCards({
        matches_with_events: 120,
        matches_with_a_dismissal: 9,
        convention_sensitive_pct: 0.075,
        events_vs_statistics_compared: 0,
        events_equal_statistics_pct: null,
      }),
    );
    expect(out).toContain("Las casas no cuentan las tarjetas igual");
    expect(out).not.toContain("coinciden en el");
  });

  test("lists the fifteen competitions with the most finished matches, the biggest first", () => {
    setLocale("es");
    const d = matrix();
    const rows = competitionRows(d);
    expect(rows).toHaveLength(15);
    expect(rows[0]).toEqual(["Liga 1 Colombia", localInt(1000), localInt(40)]);
    expect(rows[14]?.[0]).toBe("Liga 15 Colombia");
    const names = rows.map((r) => r[0]);
    expect(names).not.toContain("Liga 16 Colombia");
    expect(names).not.toContain("Liga 17 Colombia");
    const finished = rows.map((r) => Number((r[1] ?? "").replace(/\D/g, "")));
    expect(finished).toEqual([...finished].sort((a, b) => b - a));
    // The one without a name is still a row, known by its number.
    expect(rows[3]).toEqual(["#103", localInt(970), localInt(37)]);
    const out = render(d);
    expect(out).toContain("Cobertura por competición");
    expect(out).toContain("Terminados (365 d)");
    expect(out).toContain("Con precio (8 d)");
    expect(out).toContain(`${localInt(9000)} partidos terminados y ${localInt(430)} con precio`);
  });

  test("without a coverage or a summary the rest of the matrix still reads", () => {
    setLocale("es");
    const d = matrix({ coverage: null, summary: null });
    const page = html(d);
    expect(page).not.toContain("intel-market-matrix-competitions");
    expect(page).not.toContain("intel-market-matrix-cards");
    expect(cells(d, "result.1x2")[1]).toBe("Parcial");
    // The count of provider bets comes from the summary: a dash, not a zero, when there is none.
    expect(text(page)).toContain("Apuestas del proveedor —");
  });

  test("a stored matrix without rows shows its figures and no table of rows", () => {
    setLocale("es");
    const page = html(matrix({ rows: [] }));
    expect(page).toContain("intel-market-matrix-stats");
    expect(page).not.toContain("intel-market-matrix-group-");
    expect(page).not.toContain("intel-market-matrix-row-");
  });

  test("keys and rules the server could not count are dashes", () => {
    setLocale("es");
    const out = render(
      matrix({
        keys: { keys: null, followed: null, modelled: null },
        rules: { rules: null, can_grade: null },
      }),
    );
    expect(out).toContain("Claves en el catálogo — — seguidas, — modeladas");
    expect(out).toContain("Reglas de liquidación — — pueden liquidar");
  });

  test("English reads in English: the kinds of bet, the groups, the verdicts and the columns", () => {
    setLocale("en");
    const d = matrix();
    const out = render(d);
    expect(cells(d, "result.1x2")[0]).toBe("Match winner");
    expect(cells(d, "goals_half.result")[0]).toBe("↳ Half result, double chance, draw no bet");
    expect(cells(d, "result.1x2")[1]).toBe("Partial");
    expect(cells(d, "futures")[1]).toBe("Not viable");
    for (const letter of ["A", "B", "C", "D", "E", "G", "H", "Z"]) {
      expect(out).toContain(`${letter} · ${GROUPS_EN[letter]}`);
    }
    expect(out).toContain("Ready 0");
    expect(out).toContain("Keys in the catalogue");
    expect(out).toContain("21 followed, 5 modelled");
    expect(out).toContain("Settlement rules");
    expect(out).toContain("Coverage by competition");
    for (const spanish of ["Veredicto", "Motivo", "Apuestas", "Resultados", "Modelo", "Mercado"]) {
      expect(out).not.toContain(spanish);
    }
  });

  test("a row with no English label falls back to the Spanish one", () => {
    setLocale("en");
    const d = matrix({
      rows: [row({ key: "n", group: "A", label: "Solo en español", label_en: "" })],
    });
    expect(cells(d, "n")[0]).toBe("Solo en español");
  });
});

describe("the closed vocabularies the server sends are all named in both languages", () => {
  const REASONS = [
    "priced",
    "edge_validated",
    "edge_not_validated",
    "no_prices_in_window",
    "thin_price",
    "after_parent",
    "not_extracted",
    "not_offered",
    "no_period_data",
    "player_level",
    "out_of_scope",
    "no_data",
    "rejected_backtest",
    "low_information",
    "kind_not_graded",
    "not_understood",
  ];
  const VERDICTS = ["ready", "partial", "investigate", "notViable"];
  const PRIORITIES = ["alta", "media", "baja"];
  const LETTERS = Object.keys(GROUPS);
  const EDGES = ["VALIDATED", "NOT_VALIDATED", "unknown"];
  const keys = [
    ...REASONS.map((k) => `intel.markets.matrix.reason.${k}`),
    ...VERDICTS.map((k) => `intel.markets.matrix.verdict.${k}`),
    ...PRIORITIES.map((k) => `intel.markets.matrix.priority.${k}`),
    ...LETTERS.map((k) => `intel.markets.matrix.group.${k}`),
    ...EDGES.map((k) => `intel.markets.matrix.model.edge.${k}`),
  ];

  test.each(["es", "en"] as const)(
    "%s names every reason, verdict, priority, group and edge",
    (lang) => {
      const missing = keys.filter((k) => !hasKey(k, lang));
      expect(missing).toEqual([]);
    },
  );

  test("every group the server names reads the same in Spanish as the server says it, and in English too", () => {
    const every = matrix({
      rows: LETTERS.map((g) => row({ key: `k${g}`, group: g, label: g, label_en: g })),
    });
    setLocale("es");
    const es = render(every);
    for (const g of LETTERS) expect(es).toContain(`${g} · ${GROUPS[g]}`);
    setLocale("en");
    const en = render(every);
    for (const g of LETTERS) expect(en).toContain(`${g} · ${GROUPS_EN[g]}`);
  });
});
