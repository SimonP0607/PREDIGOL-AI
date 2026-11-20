/// <reference types="bun" />
/**
 * Plan PM, PM-14-01 (I12): every one of C-16's seven states lands in one of the five states a screen draws, in C-16's order (after
 * the first «no» the next are not evaluated), and a screen gets one note per state, never one per block.
 */
import { describe, expect, test } from "bun:test";
import type {
  BlockAvailability,
  LevelCell,
  MarketAvailability,
  MatchAvailability,
} from "@/lib/api/v1/types_availability";
import matchExample from "@/lib/api/v1/fixtures/c16_match.json";
import {
  AVAILABILITY_STEPS,
  blockUnavailable,
  cellUnavailable,
  firstFailingStep,
  groupUnavailable,
  marketSteps,
  marketUnavailable,
  moduleKind,
} from "./availabilityState";

const match = (matchExample as unknown as { match: MatchAvailability }).match;

const OK: MarketAvailability = {
  key: "1X2",
  matrix_market: "1X2",
  exists: true,
  coverage_ok: true,
  level: "A",
  price_in_force: true,
  prob_computed: true,
  prob_authorised: true,
  settleable: true,
  reason: "ninguno",
  modules: [
    { module: "mi_parlay", ok: true, reason: "ok" },
    { module: "picks", ok: true, reason: "ok" },
    { module: "cuotas", ok: true, reason: "ok" },
  ],
};

function block(over: Partial<BlockAvailability>): BlockAvailability {
  return {
    key: "xg",
    exists: true,
    level: "A",
    n: 120,
    provisional: false,
    reason: "ninguno",
    ...over,
  };
}

function cell(over: Partial<LevelCell>): LevelCell {
  return {
    key: "corners",
    level: "A",
    n: 40,
    with_data: 40,
    pct: 100,
    provisional: false,
    reason: "ninguno",
    measured_at: "2026-11-21T08:04:00Z",
    ...over,
  };
}

describe("the seven states, in order", () => {
  test("a market that passes all seven is available", () => {
    expect(firstFailingStep(OK)).toBeNull();
    expect(marketUnavailable(OK)).toBeNull();
    expect(Object.values(marketSteps(OK))).toEqual(Array(7).fill("si"));
  });

  test("after the first «no» the next states are «sin evaluar», as I11 draws them", () => {
    const steps = marketSteps({ ...OK, price_in_force: false, settleable: false });
    expect(AVAILABILITY_STEPS.map((s) => steps[s])).toEqual([
      "si",
      "si",
      "no",
      "sin_evaluar",
      "sin_evaluar",
      "sin_evaluar",
      "sin_evaluar",
    ]);
  });

  test("each state that fails first lands in its screen state", () => {
    const cases: Array<[Partial<MarketAvailability>, string, string]> = [
      [{ exists: false, reason: "no_entregado", level: "D" }, "existe", "no_existe"],
      [{ exists: false, reason: "sin_ventana" }, "existe", "pendiente"],
      [
        { coverage_ok: false, level: "C", reason: "menos_de_5_casas" },
        "cobertura",
        "cobertura_parcial",
      ],
      [
        { coverage_ok: false, level: "MI", reason: "muestra_insuficiente" },
        "cobertura",
        "muestra_insuficiente",
      ],
      [{ coverage_ok: false, level: "D", reason: "sin_cobertura" }, "cobertura", "no_existe"],
      [{ price_in_force: false }, "cuota", "pendiente"],
      [{ prob_computed: false }, "probabilidad", "pendiente"],
      [{ prob_authorised: false }, "autorizada", "en_revision"],
      [{ settleable: false, reason: "sin_regla" }, "liquidable", "no_existe"],
    ];
    for (const [over, step, kind] of cases) {
      const got = marketUnavailable({ ...OK, ...over });
      expect({ step: got?.step, kind: got?.kind }).toEqual({ step, kind } as never);
    }
  });

  test("state 7: the module's own «no», for one module or for any", () => {
    const m: MarketAvailability = {
      ...OK,
      modules: [
        { module: "mi_parlay", ok: true, reason: "ok" },
        { module: "picks", ok: false, reason: "MERCADO_NO_EVALUABLE" },
        { module: "cuotas", ok: true, reason: "ok" },
      ],
    };
    expect(marketUnavailable(m, "cuotas")).toBeNull();
    expect(marketUnavailable(m, "picks")).toMatchObject({
      step: "reglas",
      kind: "en_revision",
      module: "picks",
      reason: "MERCADO_NO_EVALUABLE",
    });
    expect(marketUnavailable(m)?.module).toBe("picks");
    expect(moduleKind("menos_de_3_casas")).toBe("pendiente");
    expect(moduleKind("started")).toBe("no_existe");
  });

  test("the contract's own example: 1X2 visible, corners without PrediGol's probability, shots not offered", () => {
    const [x12, corners, shots] = match.markets as [
      MarketAvailability,
      MarketAvailability,
      MarketAvailability,
    ];
    expect(marketUnavailable(x12)).toBeNull();
    expect(marketUnavailable(corners)).toMatchObject({ step: "autorizada", kind: "en_revision" });
    expect(marketUnavailable(corners, "mi_parlay")).toMatchObject({ step: "autorizada" });
    expect(marketUnavailable(shots)).toMatchObject({ step: "cobertura", kind: "no_existe" });
  });
});

describe("blocks and cells", () => {
  test("a block at A or B is drawn; one not delivered disappears; a C block is drawn with its note", () => {
    expect(blockUnavailable(block({}))).toBeNull();
    expect(blockUnavailable(block({ level: "B" }))).toBeNull();
    expect(
      blockUnavailable(block({ exists: false, level: "D", reason: "no_entregado" }))?.kind,
    ).toBe("no_existe");
    expect(blockUnavailable(block({ level: "C" }))?.kind).toBe("cobertura_parcial");
    expect(blockUnavailable(block({ level: "MI", reason: "muestra_insuficiente" }))?.kind).toBe(
      "muestra_insuficiente",
    );
    const blocks = match.blocks.map(blockUnavailable);
    expect(blocks.map((b) => b?.kind ?? null)).toEqual([null, null, "no_existe", null]);
  });

  test("a cell: its sample and percentage travel with the state", () => {
    expect(cellUnavailable(cell({}))).toBeNull();
    expect(cellUnavailable(cell({ level: "C", pct: 62, with_data: 25 }))).toMatchObject({
      kind: "cobertura_parcial",
      pct: 62,
      n: 40,
    });
    expect(
      cellUnavailable(cell({ level: "D", with_data: 0, pct: 0, reason: "no_entregado" }))?.kind,
    ).toBe("no_existe");
    expect(cellUnavailable(cell({ level: "MI", reason: "muestra_insuficiente", n: 6 }))?.kind).toBe(
      "muestra_insuficiente",
    );
    expect(cellUnavailable(cell({ level: "D", reason: "sin_medir", with_data: 0 }))?.kind).toBe(
      "pendiente",
    );
  });
});

describe("one note per screen", () => {
  test("states grouped in the order of the five, each subject once, available ones left out", () => {
    const groups = groupUnavailable([
      {
        subject: "remates",
        state: blockUnavailable(block({ exists: false, level: "D", reason: "no_entregado" })),
      },
      {
        subject: "posesión",
        state: blockUnavailable(block({ exists: false, level: "D", reason: "no_entregado" })),
      },
      {
        subject: "árbitro",
        state: blockUnavailable(block({ level: "MI", reason: "muestra_insuficiente" })),
      },
      {
        subject: "remates",
        state: blockUnavailable(block({ exists: false, level: "D", reason: "no_entregado" })),
      },
      { subject: "goles", state: null },
      { subject: "córners", state: marketUnavailable({ ...OK, prob_authorised: false }) },
    ]);
    expect(groups.map((g) => [g.kind, g.subjects])).toEqual([
      ["no_existe", ["remates", "posesión"]],
      ["muestra_insuficiente", ["árbitro"]],
      ["en_revision", ["córners"]],
    ]);
    expect(groupUnavailable([{ subject: "goles", state: null }])).toEqual([]);
  });
});
