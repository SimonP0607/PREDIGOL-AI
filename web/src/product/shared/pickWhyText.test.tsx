/// <reference types="bun" />
/** AP-T02: the risk chips of a pick pass through the guard of the server's texts (no Arabic, no rumour, no «0.473»). */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { RiskChips } from "./PickWhy";

afterEach(() => setLocale("es"));

const ARABIC = "شائعات عن إصابة لاعب الارتكاز الأساسي قبل المباراة";

describe("RiskChips and the server's text", () => {
  test("the Arabic rumour of the capture is not drawn; the good risks are", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <RiskChips
        risks={[ARABIC, "Viaja tras tres partidos en siete días", "Se rumorea una baja"]}
      />,
    );
    expect(html).not.toContain("شائعات");
    expect(html).not.toMatch(/rumorea/i);
    expect(html).toContain("Viaja tras tres partidos en siete días");
  });

  test("a decimal with a point is written with a comma in Spanish", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <RiskChips risks={["La cuota bajó a 1.95 en la última hora"]} />,
    );
    expect(html).toContain("1,95");
    expect(html).not.toContain("1.95");
  });

  test("only rumours and foreign scripts: no chips at all", () => {
    expect(renderToStaticMarkup(<RiskChips risks={[ARABIC]} />)).toBe("");
  });
});
