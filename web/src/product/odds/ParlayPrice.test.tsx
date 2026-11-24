/// <reference types="bun" />
/**
 * The price toggle of Cuotas (plan Cuotas, ola 0, E7): its accessible name says what a tap does now. It lived beside the old
 * board's tests (`OddsBoard.test.tsx`), retired with that page (PM-13-07, UX-232); the toggle is the explorer's too.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { ParlayToggle } from "./ParlayPrice";

setLocale("es");
afterAll(() => setLocale("es"));

describe("a price toggle (E7)", () => {
  const state = (inSlip: boolean) => ({
    inSlip,
    block: null,
    replaces: false,
    toggle: () => undefined,
  });

  test("a screen reader hears «Quitar de mi parlay» once the selection is in", () => {
    const inside = renderToStaticMarkup(
      <ParlayToggle state={state(true)} srLabel="Brighton -0,25: 1,67">
        1,67
      </ParlayToggle>,
    );
    expect(inside).toContain('aria-pressed="true"');
    expect(inside).toContain(
      '<span class="sr-only">Brighton -0,25: 1,67 Quitar de mi parlay</span>',
    );
    const outside = renderToStaticMarkup(
      <ParlayToggle state={state(false)} srLabel="Brighton -0,25: 1,67">
        1,67
      </ParlayToggle>,
    );
    expect(outside).toContain(
      '<span class="sr-only">Brighton -0,25: 1,67 Agregar a mi parlay</span>',
    );
  });
});
