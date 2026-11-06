/// <reference types="bun" />
/**
 * The one line and the chips of a compact pick (plan de cierre UX, 2.3): the line needs both of the pick's own numbers, the
 * chips are the review's risks - two at most, none without any - and nothing is drawn for what is not there.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { MAX_RISK_CHIPS, PickWhyLine, RiskChips } from "./PickWhy";

setLocale("es");
afterEach(() => setLocale("es"));

const plain = (html: string) => html.replace(/[\u00a0\u202f]/g, " ");

describe("the line of why", () => {
  test("PrediGol's probability beside the market's, from the pick's own numbers (strings or numbers)", () => {
    const html = plain(renderToStaticMarkup(<PickWhyLine model="0.523" market={0.452} />));
    expect(html).toContain('data-testid="pick-why-line"');
    expect(html).toContain("PrediGol le da 52 % y el mercado, 45 %.");
    setLocale("en");
    expect(plain(renderToStaticMarkup(<PickWhyLine model={0.523} market={0.452} />))).toContain(
      "PrediGol gives it 52%; the market, 45%.",
    );
  });

  test("without either number, no line at all", () => {
    for (const [model, market] of [
      ["0.5", null],
      [null, 0.4],
      ["0.5", ""],
      ["abc", 0.4],
      [undefined, undefined],
    ] as const)
      expect(renderToStaticMarkup(<PickWhyLine model={model} market={market} />)).toBe("");
  });

  test("it promises nothing: no certainty in its words, in either language", () => {
    const words = /\b(seguro|segura|fijo|fija|garantizad[oa]s?|sure|guaranteed|lock)\b/i;
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      expect(renderToStaticMarkup(<PickWhyLine model={0.6} market={0.5} />)).not.toMatch(words);
    }
  });
});

describe("the risk chips", () => {
  test("the review's risks, two at most, each with its whole text for a long press or a hover", () => {
    const html = renderToStaticMarkup(
      <RiskChips risks={["Alineaciones sin confirmar", "Dos bajas importantes", "Un tercero"]} />,
    );
    expect(html).toContain('data-testid="risk-chips"');
    expect(html.match(/<li /g)?.length).toBe(MAX_RISK_CHIPS);
    expect(html).toContain('title="Alineaciones sin confirmar"');
    expect(html).not.toContain("Un tercero");
    expect(html).toContain('aria-label="Riesgos que vio la revisión de contexto"');
  });

  test("none without risks - or with only blanks: never a chip that says nothing", () => {
    for (const risks of [undefined, null, [], ["", "   "]])
      expect(renderToStaticMarkup(<RiskChips risks={risks} />)).toBe("");
  });

  test("blanks do not use up the two places", () => {
    const html = renderToStaticMarkup(<RiskChips risks={["  ", "Uno", "Dos", "Tres"]} />);
    expect(html).toContain("Uno");
    expect(html).toContain("Dos");
    expect(html).not.toContain("Tres");
  });
});
