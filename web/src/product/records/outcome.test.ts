/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { parlayOutcome } from "./model";

describe("one result for a parlay: En juego, Ganado, Perdido (REVIEW point 2)", () => {
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

  test("otherwise it is in play - never 'Abierto' and 'En juego' at once", () => {
    expect(parlayOutcome("READY", "OPEN")).toBe("playing");
    expect(parlayOutcome("ACTIVE", "PARTIAL_WON")).toBe("playing");
    expect(parlayOutcome("ACTIVE", "WON")).toBe("won");
    expect(parlayOutcome("ACTIVE")).toBe("playing");
  });
});
