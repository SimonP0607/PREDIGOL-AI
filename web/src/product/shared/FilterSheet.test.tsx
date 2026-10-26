/// <reference types="bun" />
/**
 * The filters' sheet on a phone (plan UX, A15): a «Filtros» button that says how many filters are on - in digits and
 * in words for a screen reader -, drawn only below 1024 px (at a desk the page shows the controls in its own row), and
 * whose sheet is not in the page until it is opened. The browser half (open, change, «Ver N», clear) is
 * e2e/responsive.spec.ts.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { FilterSheet, SheetField } from "./FilterSheet";

afterAll(() => setLocale("es"));

function button(html: string): string {
  return /<button[^>]*data-testid="x-open"[^>]*>[\s\S]*?<\/button>/.exec(html)?.[0] ?? "";
}

describe("the «Filtros» button", () => {
  test("with filters on: their number, and the words for a screen reader", () => {
    setLocale("es");
    const out = renderToStaticMarkup(
      <FilterSheet testId="x" active={2} onReset={() => {}}>
        <SheetField label="País">
          <select aria-label="País" />
        </SheetField>
      </FilterSheet>,
    );
    const b = button(out);
    expect(b).toContain("Filtros");
    expect(b).toMatch(/data-testid="x-count"[^>]*>2</);
    expect(b).toContain("2 filtros activos");
    expect(b).toContain('aria-haspopup="dialog"');
    expect(b).toContain('aria-expanded="false"');
    expect(b).toContain("lg:hidden");
    // the sheet and its controls are not in the page until it opens
    expect(out).not.toContain("x-sheet");
    expect(out).not.toContain("País");
  });

  test("with none on: no number, and it reads as a plain button", () => {
    setLocale("en");
    const out = renderToStaticMarkup(
      <FilterSheet testId="x" active={0} onReset={() => {}}>
        <span />
      </FilterSheet>,
    );
    const b = button(out);
    expect(b).toContain("Filters");
    expect(b).not.toContain("x-count");
    expect(b).not.toContain("filters on");
    setLocale("es");
  });
});
