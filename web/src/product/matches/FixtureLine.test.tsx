/// <reference types="bun" />
/**
 * The names in a match row (UX-076, UX-082, UX-094): the line follows the room its row gives it - a container query,
 * not the screen's width. It goes on one line from 30 rem of line and a long name ("Club Sp. San Lorenzo") is cut with
 * an ellipsis only from 40 rem, where each side has 240 px; below that it wraps as it does on a phone. Before UX-094
 * the one line started at the screen's `sm` and left 114 px a side at 640 px. Web CI runs this; the width-by-width check
 * of the real page is in `e2e/responsive.spec.ts` (run by hand against the local stack).
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

  test("a name wraps until its line has 40 rem: the ellipsis follows the container, never the screen", () => {
    const classes = nameClasses();
    expect(classes.length).toBe(2);
    for (const c of classes) {
      expect(c).toContain("@min-[40rem]:truncate");
      expect(c).not.toMatch(/(^|\s)(sm|md|lg):truncate/);
      expect(c).not.toMatch(/(^|\s)truncate(\s|$)/);
      expect(c).toContain("break-words");
    }
  });

  test("the line is its own container and goes on one line from 30 rem of it, not from a screen width", () => {
    const markup = renderToStaticMarkup(
      <FixtureLine home={side("A")} away={side("B")} score={{ home: 1, away: 0 }} />,
    );
    expect(markup).toMatch(/^<div class="@container /);
    expect(markup).toContain("@min-[30rem]:grid-cols-[minmax(0,1fr)_4.75rem_minmax(0,1fr)]");
    expect(markup).not.toMatch(/\bsm:grid-cols/);
  });
});
