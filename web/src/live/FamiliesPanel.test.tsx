/// <reference types="bun" />
/**
 * PLAN F10.17 and F11.11, the families in shadow in the Admin Console (Aprendizaje, "Familias"): a database where the switch has never been on shows
 * the four families with nothing in them and says why; a family that completed the cycle shows its cycle, its card, the last word on each market with
 * the rule that grades it, what became of it and its post-mortem, and what the families remember; a rejection is not mistaken for a selection; a step
 * that raised shows its error; nothing is offered that the server did not send; and every word is in both languages.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { fmtOdds, fmtPct, fmtSignedPct } from "@/lib/i18n/format";
import type {
  FamiliesCard,
  FamiliesItem,
  FamiliesMemoryRow,
  FamiliesRecord,
  FamiliesRule,
  FamiliesStepRun,
  IntelFamilies,
} from "@/lib/api/v1/types_families";
import { bogotaDateTime } from "./aiModel";
import { FamiliesBody } from "./FamiliesPanel";

afterEach(() => setLocale("es"));

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");
/** The formatters put a no-break space before a "%" and a "pp"; the text helper above turns every space into a plain one. */
const norm = (s: string) => s.replace(/\s+/g, " ");

function render(d: IntelFamilies, open?: (id: number) => void, openId?: number): string {
  return renderToStaticMarkup(
    <FamiliesBody d={d} {...(open ? { onOpen: open } : {})} {...(openId ? { openId } : {})} />,
  );
}

/** A block of the tab, from its `data-testid` to the end of its `<section>` / `<div>`: enough for the checks of one block. */
function block(html: string, id: string): string {
  const start = html.indexOf(`data-testid="${id}"`);
  if (start < 0) throw new Error(`no block ${id}`);
  const open = html.lastIndexOf("<", start);
  const tag = /^<(\w+)/.exec(html.slice(open))?.[1] ?? "div";
  let depth = 0;
  const re = new RegExp(`<(/?)${tag}\\b[^>]*>`, "g");
  re.lastIndex = open;
  for (let m = re.exec(html); m; m = re.exec(html)) {
    depth += m[1] === "/" ? -1 : 1;
    if (depth === 0) return html.slice(open, re.lastIndex);
  }
  return html.slice(open);
}

/** The rows of the first table in a block, each as { html, text }. */
function rows(html: string): Array<{ html: string; text: string }> {
  return [...html.matchAll(/<tr\b[^>]*>(.*?)<\/tr>/gs)]
    .map((m) => ({ html: m[0], text: text(m[1] ?? "").trim() }))
    .filter((r) => !r.html.includes("<th"));
}

const RULES: Record<string, FamiliesRule> = Object.fromEntries(
  [
    ["goals_1h", "1H", "half-time score", ""],
    ["goals_2h", "2H", "goals after 90 minutes minus the half-time score", ""],
    [
      "goals_halves",
      "FT",
      "both halves",
      "HT/FT, highest scoring half and the like read both halves.",
    ],
    ["corners_ft", "FT", "corners of the match", ""],
    [
      "cards_lines_ft",
      "FT",
      "every card shown counts one",
      "The convention of the houses is not stated.",
    ],
    ["yellow_ft", "FT", "yellow cards only", ""],
  ].map(([measure, period, convention, note]) => [
    `${measure}@v1`,
    {
      key: `${measure}@v1`,
      measure,
      version: 1,
      period,
      convention,
      columns: [`${measure}_home`, `${measure}_away`],
      liquidable: true,
      note,
    } as FamiliesRule,
  ]),
);

const RULES_OF: Record<string, string[]> = {
  GOALS_HALF: ["goals_1h@v1", "goals_2h@v1", "goals_halves@v1"],
  CORNERS: ["corners_ft@v1"],
  CARDS: ["cards_lines_ft@v1"],
  YELLOW: ["yellow_ft@v1"],
};

function card(family: string, over: Partial<FamiliesCard> = {}): FamiliesCard {
  return {
    family,
    selections: 0,
    rejected: 0,
    settled: 0,
    open: 0,
    results: {},
    verdicts: {},
    rules: RULES_OF[family] ?? [],
    memory: null,
    ...over,
  };
}

function record(over: Partial<FamiliesRecord> = {}): FamiliesRecord {
  return {
    n: 0,
    decided: 0,
    wins: 0,
    hit: null,
    claimed: null,
    gap: null,
    z: null,
    clv_n: 0,
    clv_mean: null,
    quality: {},
    staked: 0,
    profit: 0,
    roi: null,
    verdicts: {},
    results: {},
    ...over,
  };
}

function memory(
  entity_type: string,
  entity_key: string,
  all: Partial<FamiliesRecord>,
  over: Partial<FamiliesMemoryRow> = {},
): FamiliesMemoryRow {
  return {
    entity_type,
    entity_key,
    entity_name: null,
    version: "memory-fam-v1",
    as_of_day: "2026-10-24",
    built_at: "2026-10-24T08:00:00+00:00",
    confidence: 0.4,
    stats: {
      all: record(all),
      recent: record({ n: all.n === undefined ? 0 : Math.min(all.n, 4) }),
      recent_days: 28,
    },
    delta: {},
    evidence_ref: {},
    ...over,
  };
}

const STARTED = "2026-10-24T08:15:00+00:00";

function run(step: string, over: Partial<FamiliesStepRun> = {}): FamiliesStepRun {
  return {
    step,
    job: step === "families" ? "decide" : "nightly",
    run_id: 10,
    started_at: STARTED,
    finished_at: "2026-10-24T08:15:02+00:00",
    status: "ok",
    ms: 850,
    result: {},
    error: null,
    ...over,
  };
}

function item(over: Partial<FamiliesItem> = {}): FamiliesItem {
  return {
    id: 5,
    fixture_id: 77,
    kickoff_at: "2026-10-23T19:00:00+00:00",
    known_at: "2026-10-22T19:00:00+00:00",
    checkpoint: "T-24h",
    match: "Barcelona - Real Madrid",
    home: "Barcelona",
    away: "Real Madrid",
    competition: "LaLiga",
    country: "Spain",
    family: "CORNERS",
    model_name: "family-corners_ft",
    market_key: "CORNERS_OU",
    selection: "Over",
    line: 10.5,
    odds: 1.95,
    n_bookmakers: 5,
    p_model: 0.58,
    p_market: 0.5,
    ev_raw: 0.131,
    state: "INVESTIGACION",
    stake_units: 0,
    reasons: ["family_research", "not_calibrated"],
    revisions: 1,
    forecast: {
      forecast_id: 9,
      known_at: "2026-10-22T18:00:00+00:00",
      calibration: "UNCALIBRATED",
    },
    rule: "corners_ft@v1",
    outcome: null,
    postmortem: null,
    ...over,
  };
}

function data(over: Partial<IntelFamilies> = {}): IntelFamilies {
  return {
    versions: {
      forecast: "family-v1",
      decision: "decision-fam-v1",
      outcome: "outcome-fam-v1",
      postmortem: "pm-fam-v1",
      memory: "memory-fam-v1",
    },
    window: { days: 14, from: "2026-10-10T00:00:00+00:00", to: "2026-10-24T00:00:00+00:00" },
    mode: null,
    steps: [],
    families: ["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"].map((f) => card(f)),
    items: [],
    total: 0,
    rules: RULES,
    memory: [],
    ...over,
  };
}

/** A family that completed the cycle: the decision, its settlement, its post-mortem and what the family remembers. */
function cycle(): IntelFamilies {
  const corners = memory("family", "CORNERS", {
    n: 12,
    decided: 12,
    wins: 7,
    hit: 0.5833,
    claimed: 0.54,
    gap: 0.0433,
    z: 0.756,
    clv_n: 10,
    clv_mean: 0.0123,
    staked: 12,
    profit: 1.9,
    roi: 0.1583,
  });
  return data({
    mode: "shadow",
    steps: [
      run("families", {
        run_id: 40,
        result: { mode: "shadow", forecasts: 120, candidates: 8, written: 3, failed: 0 },
      }),
      run("family_outcomes", {
        run_id: 31,
        result: { mode: "shadow", open: 2, settled: 5, no_close: 1, failed: 0 },
      }),
      run("family_postmortems", {
        run_id: 31,
        result: { mode: "shadow", open: 0, written: 5, unreadable: 0, failed: 0 },
      }),
      run("family_memory", {
        run_id: 31,
        result: { mode: "shadow", postmortems: 12, entities: 4, written: 4, unchanged: 0 },
      }),
    ],
    families: [
      card("GOALS_HALF"),
      card("CORNERS", {
        selections: 5,
        rejected: 2,
        settled: 3,
        open: 2,
        results: { win: 2, loss: 1 },
        verdicts: { MERECIDO: 1, SUERTE: 1, ERROR: 1 },
        memory: corners,
      }),
      card("CARDS"),
      card("YELLOW"),
    ],
    items: [
      item({
        outcome: {
          result: "win",
          profit_flat: 0.95,
          close_odds: 1.85,
          close_p_fair: 0.53,
          close_minutes_to_ko: 1410,
          clv: 0.0234,
        },
        postmortem: {
          verdict: "SUERTE",
          quality: "BAD",
          causes: ["Tarjeta roja al minuto 30", "Penalti a favor", "Cambio temprano"],
          actual: 11,
          margin: 0.5,
        },
      }),
      item({
        id: 6,
        fixture_id: 78,
        match: "Sevilla - Betis",
        home: "Sevilla",
        away: "Betis",
        kickoff_at: "2026-10-22T19:00:00+00:00",
        market_key: "CORNERS_1X2",
        selection: "Home",
        line: 0,
        state: "RECHAZADO",
        reasons: ["family_research", "price_outlier"],
        revisions: 3,
        outcome: {
          result: "loss",
          profit_flat: -1,
          close_odds: null,
          close_p_fair: null,
          close_minutes_to_ko: null,
          clv: null,
        },
      }),
    ],
    total: 7,
    memory: [
      corners,
      memory("market", "CORNERS_OU", { n: 9, hit: 0.6667, claimed: 0.55, gap: 0.1167, decided: 9 }),
      memory("competition", "11", { n: 4 }, { entity_name: "LaLiga", confidence: null }),
      memory("referee", "5", { n: 2 }, { entity_name: "Mateu Lahoz" }),
    ],
  });
}

describe("a database where the families have never run", () => {
  test("shows the four families with nothing in them, and says why", () => {
    const html = render(data());
    const page = norm(text(html));
    for (const name of ["Goles por mitad", "Córners", "Tarjetas", "Amarillas"]) {
      expect(page).toContain(name);
    }
    for (const family of ["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"]) {
      const card = norm(text(block(html, `families-card-${family}`)));
      expect(card).toContain("Sin decisiones en la ventana.");
      expect(card).toContain("Aún no recuerda nada");
    }
    expect(text(block(html, "families-mode"))).toContain("Sin pasadas");
    expect(text(block(html, "families-mode-help"))).toContain("FBI_FAMILY_DECISIONS");
    for (const step of ["families", "family_outcomes", "family_postmortems", "family_memory"]) {
      expect(text(block(html, `families-step-${step}`))).toContain(
        "Sin pasadas en los últimos 7 días",
      );
    }
    expect(text(block(html, "families-items-empty"))).toContain("Ninguna familia ha decidido");
    expect(text(block(html, "families-memory-empty"))).toContain("Aún no hay memoria");
    expect(html).not.toContain("<table");
  });

  test("names the versions of the cycle", () => {
    const page = norm(text(render(data())));
    expect(page).toContain(
      "Versiones: pronóstico family-v1 · decisión decision-fam-v1 · liquidación outcome-fam-v1 · post-mortem pm-fam-v1 · memoria memory-fam-v1",
    );
  });

  test("with the switch off the page says so and keeps what was already written", () => {
    const html = render(data({ mode: "off", items: [item()], total: 1 }));
    expect(text(block(html, "families-mode"))).toContain("Apagado");
    expect(text(block(html, "families-mode-help"))).toContain("ya estaba escrito");
    expect(html).toContain("<table");
  });

  test("in shadow there is no warning about the switch", () => {
    const html = render(data({ mode: "shadow" }));
    expect(text(block(html, "families-mode"))).toContain("En shadow");
    expect(html).not.toContain("families-mode-help");
  });
});

describe("a family that completed the cycle", () => {
  test("the cycle shows when each step last worked and what it reported", () => {
    setLocale("es");
    const html = render(cycle());
    const decide = norm(text(block(html, "families-step-families")));
    expect(decide).toContain("Decidir");
    expect(decide).toContain("Bien");
    expect(decide).toContain(`Última: ${bogotaDateTime(STARTED)}`);
    expect(decide).toContain("850 ms");
    expect(decide).toContain("Pronósticos 120");
    expect(decide).toContain("Candidatas 8");
    expect(decide).toContain("Escritas 3");
    const settle = norm(text(block(html, "families-step-family_outcomes")));
    expect(settle).toContain("Liquidar");
    expect(settle).toContain("Abiertas 2");
    expect(settle).toContain("Liquidadas 5");
    expect(norm(text(block(html, "families-step-family_memory")))).toContain("Entidades 4");
    expect(text(block(html, "families-mode"))).toContain("En shadow");
  });

  test("the card of the family adds up what it did and names the rule that grades it", () => {
    const html = render(cycle());
    const corners = block(html, "families-card-CORNERS");
    const page = norm(text(corners));
    expect(page).toContain("Selecciones 5");
    expect(page).toContain("Rechazadas 2");
    expect(page).toContain("Liquidadas 3");
    expect(page).toContain("Abiertas 2");
    expect(text(block(corners, "families-card-results"))).toContain("Ganada 2");
    expect(text(block(corners, "families-card-results"))).toContain("Perdida 1");
    const verdicts = text(block(corners, "families-card-verdicts"));
    expect(verdicts).toContain("Merecido 1");
    expect(verdicts).toContain("Suerte 1");
    expect(verdicts).toContain("Error 1");
    const rules = norm(text(block(corners, "families-card-rules")));
    expect(rules).toContain("corners_ft@v1");
    expect(rules).toContain("Córners del partido");
    expect(page).not.toContain("Sin decisiones en la ventana.");
    // the families that did nothing say so
    expect(norm(text(block(html, "families-card-CARDS")))).toContain(
      "Sin decisiones en la ventana.",
    );
    // the warning about the convention of the cards is kept
    expect(norm(text(block(html, "families-card-CARDS")))).toContain("convención");
  });

  test("the card holds what the family remembers", () => {
    const html = render(cycle());
    const mem = norm(text(block(block(html, "families-card-CORNERS"), "families-card-memory")));
    expect(mem).toContain("Post-mortems 12");
    expect(mem).toContain(norm(`${fmtPct(0.5833)} / ${fmtPct(0.54)}`));
    expect(mem).toContain(norm(fmtSignedPct(0.0123, 2)));
    expect(mem).toContain(norm(fmtSignedPct(0.1583)));
    expect(mem).toContain(norm(fmtPct(0.4, 0)));
    expect(mem).toContain("Al 2026-10-24");
  });

  test("the list names the market in words and the rule that grades it, with what became of the bet", () => {
    setLocale("es");
    const html = render(cycle());
    const [won, lost] = rows(block(html, "families-items"));
    expect(won).toBeDefined();
    expect(lost).toBeDefined();
    const first = norm(won?.text ?? "");
    expect(first).toContain("Barcelona - Real Madrid");
    expect(first).toContain(`LaLiga · ${bogotaDateTime("2026-10-23T19:00:00+00:00")} · T-24h`);
    expect(first).toContain("Córners · más/menos");
    expect(first).toContain("Más de 10,5");
    expect(first).toContain("Córners");
    expect(first).toContain(norm(fmtOdds(1.95)));
    expect(first).toContain(norm(fmtPct(0.58)));
    expect(first).toContain(norm(fmtPct(0.5)));
    expect(first).toContain(norm(fmtSignedPct(0.131)));
    expect(first).toContain("Investigación");
    expect(first).toContain("Sin calibrar");
    expect(first).not.toContain("Familia en investigación");
    expect(first).toContain("corners_ft@v1");
    expect(first).toContain("Ganada");
    expect(first).toContain("+0,95 u");
    expect(first).toContain(norm(`CLV ${fmtSignedPct(0.0234)}`));
    expect(first).not.toContain("CORNERS_OU Over");
  });

  test("the post-mortem shows the verdict, the price, the count against the line and the first causes", () => {
    setLocale("es");
    const [won] = rows(block(render(cycle()), "families-items"));
    const t = norm(won?.text ?? "");
    expect(t).toContain("Suerte");
    expect(t).toContain("Precio malo");
    expect(t).toContain("11 en el partido (+0,5 sobre la línea)");
    expect(t).toContain("Tarjeta roja al minuto 30");
    expect(t).toContain("Penalti a favor");
    expect(t).not.toContain("Cambio temprano");
    expect(t).toContain("+1 más");
  });

  test("a rejection is not mistaken for a selection: its state, its reasons and its revisions are shown", () => {
    setLocale("es");
    const [, lost] = rows(block(render(cycle()), "families-items"));
    const t = norm(lost?.text ?? "");
    expect(t).toContain("Sevilla - Betis");
    expect(t).toContain("Córners · 1X2");
    expect(t).toContain("Sevilla");
    expect(t).toContain("Rechazado");
    expect(t).toContain("Precio atípico");
    expect(t).toContain("3 revisiones");
    expect(t).toContain("Perdida");
    expect(t).toContain("-1 u");
    expect(t).toContain("Aún sin post-mortem");
  });

  test("a bet that waits for its match is open and says it has no post-mortem yet", () => {
    const [open] = rows(
      block(render(data({ mode: "shadow", items: [item()], total: 1 })), "families-items"),
    );
    const t = norm(open?.text ?? "");
    expect(t).toContain("Abierta");
    expect(t).toContain("Aún sin post-mortem");
  });

  test("says how many of the last words it shows, out of how many there are", () => {
    const page = norm(text(render(cycle())));
    expect(page).toContain("Mostrando 2 de 7 · partidos de los últimos 14 días");
  });

  test("what the families remember: every entity with its record, by its name", () => {
    setLocale("es");
    const html = render(cycle());
    const table = block(html, "families-memory");
    const [family, market, competition, referee] = rows(table);
    expect(norm(family?.text ?? "")).toContain("Familia Córners");
    expect(norm(family?.text ?? "")).toContain(norm(`${fmtPct(0.5833)}`));
    expect(norm(market?.text ?? "")).toContain("Mercado Córners · más/menos");
    expect(norm(competition?.text ?? "")).toContain("Competición LaLiga");
    expect(norm(referee?.text ?? "")).toContain("Árbitro Mateu Lahoz");
    // a figure that was not measured is a dash, never a zero
    expect(norm(competition?.text ?? "")).toContain(
      "Competición LaLiga Al 2026-10-24 4 — — — — — — — 4 · —",
    );
    expect(table).toContain("Últimos 28 días");
  });
});

describe("a step that raised", () => {
  test("shows its error and its status", () => {
    const failed = run("family_memory", {
      status: "partial",
      result: {},
      error: "family_memory: ValueError: boom",
    });
    const html = render(data({ mode: "shadow", steps: [failed] }));
    const memoryStep = block(html, "families-step-family_memory");
    expect(norm(text(memoryStep))).toContain("Parcial");
    expect(text(block(html, "families-error-family_memory"))).toContain(
      "Falló: family_memory: ValueError: boom",
    );
    // the steps that did not raise show no error
    expect(html).not.toContain("families-error-families");
  });
});

describe("what the server sent is what is shown", () => {
  test("a family the page does not know has a card under its own name, and a rule missing from the list is skipped", () => {
    const html = render(
      data({
        families: [card("PENALTIES", { selections: 1, open: 1, rules: ["penalties_ft@v1"] })],
      }),
    );
    const penalties = norm(text(block(html, "families-card-PENALTIES")));
    expect(penalties).toContain("PENALTIES");
    expect(penalties).toContain("Selecciones 1");
    expect(penalties).not.toContain("penalties_ft@v1");
  });

  test("a market and a rule no one has words for are shown as they came", () => {
    const html = render(
      data({
        items: [item({ market_key: "PENALTIES_OU", selection: "Over", line: 0.5, rule: null })],
        total: 1,
      }),
    );
    const [row] = rows(block(html, "families-items"));
    const t = norm(row?.text ?? "");
    expect(t).toContain("PENALTIES_OU");
    expect(t).toContain("Over 0,5");
    expect(t).toContain("Sin regla");
  });

  test("a figure the server could not make is a dash, not a zero", () => {
    const html = render(
      data({
        items: [item({ odds: null, p_model: null, p_market: null, ev_raw: null })],
        total: 1,
      }),
    );
    const [row] = rows(block(html, "families-items"));
    expect(norm(row?.text ?? "")).toMatch(/— — — —/);
  });
});

describe("opening a decision", () => {
  test("a row is a button when the tab can open its detail, and plain when it cannot", () => {
    const withOpen = block(
      render(cycle(), () => undefined),
      "families-items",
    );
    expect(rows(withOpen).every((r) => r.html.includes('tabindex="0"'))).toBe(true);
    const plain = block(render(cycle()), "families-items");
    expect(rows(plain).some((r) => r.html.includes("tabindex"))).toBe(false);
  });

  test("the row whose detail is open is marked", () => {
    const [open, other] = rows(
      block(
        render(cycle(), () => undefined, 5),
        "families-items",
      ),
    );
    expect(open?.html).toContain("bg-primary/8");
    expect(other?.html).not.toContain("bg-primary/8");
  });
});

describe("in English", () => {
  test("the cycle, the card, the list and the memory read in English", () => {
    setLocale("en");
    const html = render(cycle());
    const page = norm(text(html));
    expect(page).toContain("Versions: forecast family-v1");
    expect(norm(text(block(html, "families-step-families")))).toContain("Decide");
    expect(norm(text(block(html, "families-step-families")))).toContain("Forecasts 120");
    const corners = norm(text(block(html, "families-card-CORNERS")));
    expect(corners).toContain("Selections 5");
    expect(corners).toContain("Won 2");
    expect(corners).toContain("Lost 1");
    expect(corners).toContain("Corners of the match");
    const cards = norm(text(block(html, "families-card-CARDS")));
    expect(cards).toContain("Every card shown counts one");
    expect(cards).toContain("The provider does not state the convention");
    const [won, lost] = rows(block(html, "families-items"));
    const first = norm(won?.text ?? "");
    expect(first).toContain("Corners · over/under");
    expect(first).toContain("Over 10.5");
    expect(first).toContain("+0.95 u");
    expect(first).toContain("Investigation");
    expect(first).toContain("Not calibrated");
    expect(first).toContain("Bad price");
    expect(first).toContain("11 in the match (+0.5 over the line)");
    expect(first).toContain("+1 more");
    const second = norm(lost?.text ?? "");
    expect(second).toContain("Rejected");
    expect(second).toContain("Outlier price");
    expect(second).toContain("3 revisions");
    expect(second).toContain("No post-mortem yet");
    expect(norm(text(block(html, "families-memory")))).toContain("Market Corners · over/under");
    expect(page).toContain("Showing 2 of 7 · matches of the last 14 days");
  });

  test("the empty page is in English too", () => {
    setLocale("en");
    const html = render(data());
    expect(text(block(html, "families-mode"))).toContain("No passes");
    expect(text(block(html, "families-mode-help"))).toContain("7 days");
    expect(text(block(html, "families-items-empty"))).toContain("No family has decided");
    expect(text(block(html, "families-memory-empty"))).toContain("no memory yet");
  });
});
