/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { startedState } from "./started";

describe("the state filter of 'Ya empezaron hoy' (REVIEW point 14)", () => {
  test("in play, won, lost - and the rest", () => {
    expect(startedState({ result_status: null, phase: "live" })).toBe("live");
    expect(startedState({ result_status: "win", phase: "finished" })).toBe("won");
    expect(startedState({ result_status: "half_loss", phase: "finished" })).toBe("lost");
    expect(startedState({ result_status: "void", phase: "postponed" })).toBe("other");
    expect(startedState({ result_status: null, phase: "awaiting" })).toBe("other");
  });
});
