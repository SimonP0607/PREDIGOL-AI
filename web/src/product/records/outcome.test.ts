/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { countLegs, parlayOutcome } from "./model";

describe("one result for a parlay: Por empezar, En juego, Va ganando, Ganado, Perdido (plan Inicio 1.3)", () => {
  test("settled: won (a voided leg still wins the rest), lost, void", () => {
    expect(parlayOutcome("WON")).toBe("won");
    expect(parlayOutcome("PARTIAL_VOID")).toBe("won");
    expect(parlayOutcome("LOST")).toBe("lost");
    expect(parlayOutcome("VOID")).toBe("void");
    expect(parlayOutcome("BUILDING")).toBe("building");
  });

  test("a lost leg decides it at once, even with legs still to play", () => {
    expect(parlayOutcome("ACTIVE", "PARTIAL_LOST")).toBe("lost");
    expect(parlayOutcome("ACTIVE", "LOST")).toBe("lost");
  });

  test("built but no leg has kicked off: Por empezar, never 'En juego'", () => {
    expect(parlayOutcome("READY", "OPEN")).toBe("scheduled");
    expect(parlayOutcome("READY")).toBe("scheduled");
  });

  test("a leg has kicked off and nothing is decided: En juego; legs won and none lost: Va ganando", () => {
    expect(parlayOutcome("ACTIVE", "OPEN")).toBe("playing");
    expect(parlayOutcome("ACTIVE")).toBe("playing");
    expect(parlayOutcome("ACTIVE", "PARTIAL_WON")).toBe("winning");
    expect(parlayOutcome("ACTIVE", "WON")).toBe("won");
  });
});

describe("how the legs stand: '1 fallada · 5 pendientes', not '0 de 6 acertadas'", () => {
  test("counts won, lost, pending and void from the legs' own results", () => {
    const legs = [
      { status: "LOSS" },
      { status: "PENDING" },
      { status: "PENDING" },
      { status: "PENDING" },
      { status: "PENDING" },
      { status: "PENDING" },
    ] as const;
    expect(countLegs(legs)).toEqual({ won: 0, lost: 1, pending: 5, void: 0, total: 6 });
  });

  test("half results count with their side, a push or void apart", () => {
    const legs = [
      { status: "WIN" },
      { status: "HALF_WIN" },
      { status: "HALF_LOSS" },
      { status: "PUSH" },
      { status: "VOID" },
    ] as const;
    expect(countLegs(legs)).toEqual({ won: 2, lost: 1, pending: 0, void: 2, total: 5 });
  });
});
