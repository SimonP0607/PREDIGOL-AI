/// <reference types="bun" />
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { formatTime } from "@/lib/time";
import { Freshness, OddsPill, ProbCompare } from "./Bits";
import { priceVariants } from "./price";

setLocale("es");

function words(node: React.ReactElement): string {
  return renderToStaticMarkup(node)
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

describe("the price chip (plan maestro UX/UI 2026, PR-12)", () => {
  test("three heights, one family of figures", () => {
    expect(priceVariants({ size: "sm" })).toContain("h-8");
    expect(priceVariants({ size: "md" })).toContain("h-10");
    expect(priceVariants({ size: "lg" })).toContain("h-[3.25rem]");
    for (const size of ["sm", "md", "lg"] as const) {
      expect(priceVariants({ size })).toContain("numeric");
      expect(priceVariants({ size })).toContain("tabular-nums");
    }
  });

  test("gold is PrediGol's choice, green is the best of a comparison, and neither is the other", () => {
    expect(priceVariants({ tone: "gold" })).toContain("text-gold-strong");
    expect(priceVariants({ tone: "best" })).toContain("text-primary");
    expect(priceVariants({ tone: "best" })).not.toContain("gold");
    expect(priceVariants({ tone: "chosen" })).toContain("bg-gold");
  });

  test("the pill writes the price it is given, as before: decimal, two places, the reader's comma", () => {
    expect(words(<OddsPill odds="2.05" />)).toBe("2,05");
    expect(words(<OddsPill odds={1.9} best size="lg" />)).toBe("1,90");
    expect(words(<OddsPill odds={null} />)).toBe("—");
  });
});

describe("PrediGol against the market, as one bar", () => {
  test("both figures are written; the bar and its mark only draw them", () => {
    const html = renderToStaticMarkup(<ProbCompare model="0.56" market="0.47" />);
    expect(words(<ProbCompare model="0.56" market="0.47" />)).toBe(
      "Prob. modelo 56,0 % Prob. mercado 47,0 %",
    );
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain("width:56%");
    expect(html).toContain("left:47%");
  });

  test("a number that is missing is a dash and draws nothing: never a zero", () => {
    const html = renderToStaticMarkup(<ProbCompare model={null} market="0.47" />);
    expect(html).not.toContain("width:");
    expect(html).toContain("left:47%");
    expect(words(<ProbCompare model={null} market={null} />)).toBe(
      "Prob. modelo — Prob. mercado —",
    );
  });

  test("a figure outside 0-100 % never draws outside the bar", () => {
    const html = renderToStaticMarkup(<ProbCompare model="1.4" market="-0.2" />);
    expect(html).toContain("width:100%");
    expect(html).toContain("left:0%");
  });
});

describe("how old a price is", () => {
  const recent = new Date(Date.now() - 7 * 60_000).toISOString();
  const old = new Date(Date.now() - 5 * 60_000).toISOString();

  test("a fresh price: a dot and how long ago, no hour", () => {
    const html = renderToStaticMarkup(<Freshness at={recent} level="fresh" hint={false} />);
    expect(html).toContain('data-freshness="fresh"');
    expect(html).not.toContain("lucide-clock");
    expect(words(<Freshness at={recent} level="fresh" hint={false} />)).not.toContain("·");
  });

  test("an old price always carries a clock and its exact hour", () => {
    const html = renderToStaticMarkup(<Freshness at={old} level="stale" hint={false} />);
    expect(html).toContain('data-freshness="stale"');
    expect(html).toContain("lucide-clock");
    expect(html).toContain("text-warning");
    expect(words(<Freshness at={old} level="stale" hint={false} />)).toContain(
      `· ${formatTime(old)}`,
    );
  });

  test("no capture: it says so, with no clock and no hour", () => {
    const html = renderToStaticMarkup(<Freshness at={null} level="stale" hint={false} />);
    expect(html).not.toContain("lucide-clock");
    expect(words(<Freshness at={null} hint={false} />)).not.toContain("·");
  });
});
