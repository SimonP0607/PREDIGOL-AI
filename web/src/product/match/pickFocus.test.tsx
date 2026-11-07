/// <reference types="bun" />
/** «Más sobre este pick» (plan de Inicio, 2.3): the pick a link names is read from the address, and only a real one. */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { PickAnchor, focusedPickOf } from "./pickFocus";

describe("the pick a link names", () => {
  test("a number in ?pick=, with or without the section beside it", () => {
    expect(focusedPickOf("?pick=45")).toBe(45);
    expect(focusedPickOf("?s=resumen&pick=45")).toBe(45);
  });

  test("nothing, zero, a negative, a decimal or text: no pick", () => {
    for (const q of ["", "?s=resumen", "?pick=", "?pick=0", "?pick=-3", "?pick=2.5", "?pick=abc"])
      expect(focusedPickOf(q)).toBeNull();
  });
});

describe("the anchor of a pick", () => {
  test("it carries the pick's id, and the mark only when the link named it", () => {
    const on = renderToStaticMarkup(
      <PickAnchor pickId={7} focused>
        <p>card</p>
      </PickAnchor>,
    );
    expect(on).toContain('id="pick-7"');
    expect(on).toContain('data-focused="true"');
    const off = renderToStaticMarkup(
      <PickAnchor pickId={8} focused={false}>
        <p>card</p>
      </PickAnchor>,
    );
    expect(off).toContain('id="pick-8"');
    expect(off).not.toContain("data-focused");
  });
});
