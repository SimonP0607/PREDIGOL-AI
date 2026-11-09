/// <reference types="bun" />
/**
 * The names in a match row (UX-076, UX-082): a long name ("Club Sp. San Lorenzo") is cut with an ellipsis only from
 * `md` (768 px). Between `sm` and `md` each side of the row is about 120 px wide and the name does not fit, so it must
 * wrap there as it does on a phone. Web CI runs this; the width-by-width check of the real page is in
 * `e2e/responsive.spec.ts` (run by hand against the local stack).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { FixtureLine } from "./FixtureLine";

const side = (name: string) => ({ name, logo: null });

function nameClasses(): string[] {
  const markup = renderToStaticMarkup(
    <FixtureLine
      home={side("Club Sp. San Lorenzo")}
      away={side("Universitario de Vinto")}
      score={{ home: 1, away: 0 }}
    />,
  );
  const spans = [...markup.matchAll(/<span class="([^"]*)" data-testid="team-name"/g)];
  return spans.map((m) => m[1] ?? "");
}

describe("FixtureLine team names", () => {
  test("both names are drawn, whole", () => {
    const markup = renderToStaticMarkup(
      <FixtureLine
        home={side("Club Sp. San Lorenzo")}
        away={side("Tecnico Universitario")}
        score={null}
      />,
    );
    expect(markup).toContain("Club Sp. San Lorenzo");
    expect(markup).toContain("Tecnico Universitario");
  });

  test("a name wraps below 768 px: the ellipsis starts at md, never at sm", () => {
    const classes = nameClasses();
    expect(classes.length).toBe(2);
    for (const c of classes) {
      expect(c).toContain("md:truncate");
      expect(c).not.toContain("sm:truncate");
      expect(c).not.toMatch(/(^|\s)truncate(\s|$)/);
      expect(c).toContain("break-words");
    }
  });
});
