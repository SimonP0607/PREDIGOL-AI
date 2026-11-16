/// <reference types="bun" />
/** Sheets P09 and P10 (UX-145): two columns at a desk, one on a phone in the sheet's order. */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { OrderedColumns } from "./SummaryTab";

describe("the ordered columns", () => {
  test("each block carries its phone order; the columns read as one on a phone", () => {
    const html = renderToStaticMarkup(
      <OrderedColumns
        testId="x"
        main={[
          { key: "result", node: <p>r</p>, order: 1 },
          { key: "forecast", node: <p>f</p>, order: 3 },
        ]}
        side={[{ key: "picks", node: <p>p</p>, order: 2 }]}
      />,
    );
    expect(html).toMatch(/data-block="result" class="[^"]*order-1/);
    expect(html).toMatch(/data-block="picks" class="[^"]*order-2/);
    expect(html).toMatch(/data-block="forecast" class="[^"]*order-3/);
    expect(html.match(/class="contents /g)).toHaveLength(2);
  });
});
