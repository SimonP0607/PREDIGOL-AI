/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { PriceNow } from "@/lib/api/v1/types_records";
import { PriceNowLine } from "./PriceNowLine";

setLocale("es");

const AS_OF = new Date(Date.now() - 12 * 60_000).toISOString();

function now(over: Partial<PriceNow> = {}): PriceNow {
  return { odds: "2.070", as_of: AS_OF, freshness: "fresh", change: "-0.1000", ...over };
}

function words(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

describe("the price now beside the price taken (plan CUOTAS, phase 6)", () => {
  test("no price now: nothing at all", () => {
    expect(renderToStaticMarkup(<PriceNowLine now={null} />)).toBe("");
    expect(renderToStaticMarkup(<PriceNowLine now={undefined} />)).toBe("");
  });

  test("a fresh price: the odds, the move and how long ago", () => {
    const text = words(<PriceNowLine now={now()} />);
    expect(text).toContain("Ahora 2,07");
    expect(text).toContain("(-10,0");
    expect(renderToStaticMarkup(<PriceNowLine now={now()} />)).toContain('data-freshness="fresh"');
    expect(text).not.toContain("precio antiguo");
  });

  test("an old price says it is old, it never passes as the current one", () => {
    const text = words(<PriceNowLine now={now({ freshness: "stale" })} />);
    expect(text).toContain("precio antiguo");
    expect(renderToStaticMarkup(<PriceNowLine now={now({ freshness: "stale" })} />)).toContain(
      'data-freshness="stale"',
    );
  });

  test("without a price taken there is no move to state", () => {
    expect(words(<PriceNowLine now={now({ change: null })} />)).not.toContain("(");
  });

  test("it names no bookmaker and makes no claim of value", () => {
    const text = words(<PriceNowLine now={now()} />).toLowerCase();
    for (const word of ["valor", "ventaja", "value", "edge", "casa"]) {
      expect(text).not.toContain(word);
    }
  });
});
