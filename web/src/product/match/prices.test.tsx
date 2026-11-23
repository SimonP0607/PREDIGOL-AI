/// <reference types="bun" />
/**
 * AP-P06: «Mejores cuotas» in the Resumen reads as compact rows - the selection and who offers it on the left, the
 * price on the right - and a selection without a price says so instead of showing a blank tile.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { PriceRow } from "./prices";
import type { BestPrice } from "./model";

const best = { odds: "2.05", bookmaker: "Casa Dos", books: 3 } as unknown as BestPrice;

describe("PriceRow", () => {
  test("shows the selection, the bookmaker and the price in one row", () => {
    const html = renderToStaticMarkup(
      <ul>
        <PriceRow label="Atlético Cordillera" price={best} />
      </ul>,
    );
    expect(html).toContain("<li");
    expect(html).toContain("Atlético Cordillera");
    expect(html).toContain("Casa Dos");
    expect(html).toContain("2,05");
  });

  test("a selection without a price keeps its row and shows a dash", () => {
    const html = renderToStaticMarkup(
      <ul>
        <PriceRow label="Empate" price={null} />
      </ul>,
    );
    expect(html).toContain("Empate");
    expect(html).toContain("—");
  });
});
