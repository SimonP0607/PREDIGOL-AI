/// <reference types="bun" />
/**
 * Plan UX, A3: a word that opens its definition. Rendered on the server it is a plain button around the reader's
 * own words - the same markup whichever way it will open (a card on a desk, a sheet on a phone), so the page never
 * hydrates differently - and it says it opens a dialog. Nothing of the definition is in the page until it opens.
 * The opening itself, the keyboard and the 320 px sheet are checked in the browser (e2e/glossary.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { GlossaryTerm } from "./GlossaryTerm";
import { ExplainLayers } from "@/product/shared/ExplainLayers";

describe("GlossaryTerm", () => {
  test("a button that opens a dialog, closed, named by the text on the screen", () => {
    setLocale("es");
    const out = renderToStaticMarkup(<GlossaryTerm term="expectedValue">VE +4,2 %</GlossaryTerm>);
    expect(out).toContain("<button");
    expect(out).toContain('type="button"');
    expect(out).toContain('aria-haspopup="dialog"');
    expect(out).toContain('aria-expanded="false"');
    expect(out).toContain('data-glossary="expectedValue"');
    expect(out).toContain(">VE +4,2 %</button>");
    // the definition is not in the page until it is opened
    expect(out).not.toContain("Lo que se ganaría o perdería");
    expect(out).not.toContain("<a ");
  });

  test("without children, the term's own name in the reader's language", () => {
    setLocale("es");
    expect(renderToStaticMarkup(<GlossaryTerm term="fairOdds" />)).toContain(
      ">Cuota justa</button>",
    );
    setLocale("en");
    expect(renderToStaticMarkup(<GlossaryTerm term="fairOdds" />)).toContain(">Fair odds</button>");
    setLocale("es");
  });

  test("a finger reaches it: the 44 px touch target and a visible focus", () => {
    const out = renderToStaticMarkup(<GlossaryTerm term="pick" />);
    expect(out).toMatch(/class="[^"]*\btap\b[^"]*\brelative\b/);
    expect(out).toContain("focus-visible:ring-1");
  });
});

describe("ExplainLayers", () => {
  test("forecast, value and pick, in that order, each word opening its definition", () => {
    setLocale("es");
    const out = renderToStaticMarkup(<ExplainLayers />);
    const terms = [...out.matchAll(/data-glossary="(\w+)"/g)].map((m) => m[1]);
    expect(terms).toEqual(["forecast", "value", "pick"]);
    expect(out).toContain("<ol");
    expect(out).toContain("¿Qué es probable?");
    expect(out).toContain("¿Está bien pagado?");
    expect(out).toContain("¿Lo recomienda PrediGol?");
    expect(out).toMatch(/<h2[^>]*>Pronóstico, valor y pick/);
  });

  test("inside a block the heading is one level down", () => {
    setLocale("es");
    expect(renderToStaticMarkup(<ExplainLayers compact />)).toMatch(
      /<h3[^>]*>Pronóstico, valor y pick/,
    );
  });
});
