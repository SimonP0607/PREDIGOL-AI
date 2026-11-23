/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { preMatchBlocks } from "./order";

describe("«Estadísticas» before kick-off (AP-P05)", () => {
  test("how they come in, then the season, then the cross in charts", () => {
    expect(preMatchBlocks(true)).toEqual(["profile", "season", "cross"]);
  });
  test("without the advanced statistics the cross is not there; the rest keeps its order", () => {
    expect(preMatchBlocks(false)).toEqual(["profile", "season"]);
  });
});
