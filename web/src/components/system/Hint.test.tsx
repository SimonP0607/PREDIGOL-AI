/// <reference types="bun" />
/**
 * Plan F13, a word of help that works on a phone: the text is wrapped in a control that opens on a tap, hover and focus, and
 * a screen reader reads the help after it. With no help it is the text alone. The table header takes its definition the same way.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { TH } from "@/components/primitives/DataTable";
import { Hint } from "./Hint";

describe("Hint", () => {
  test("a control around the text, the help read after it, and no native title", () => {
    const out = renderToStaticMarkup(<Hint text="Partidos jugados">PJ</Hint>);
    expect(out).toContain("<button");
    expect(out).toContain('type="button"');
    expect(out).toContain(">PJ<");
    expect(out).toContain(": Partidos jugados</span>");
    expect(out).toContain('class="sr-only"');
    expect(out).not.toContain("title=");
  });

  test("no help, no control: the children as they are", () => {
    expect(renderToStaticMarkup(<Hint text={null}>PJ</Hint>)).toBe("PJ");
    expect(renderToStaticMarkup(<Hint text={undefined}>PJ</Hint>)).toBe("PJ");
    expect(renderToStaticMarkup(<Hint text="   ">PJ</Hint>)).toBe("PJ");
    expect(renderToStaticMarkup(<Hint text="">PJ</Hint>)).toBe("PJ");
  });

  test("asChild puts the trigger on the element given, focusable, and adds no control of its own", () => {
    const out = renderToStaticMarkup(
      <Hint text="El partido ya empezó" asChild>
        <div className="cell">1,90</div>
      </Hint>,
    );
    expect(out).toContain('<div class="cell"');
    expect(out).toContain('tabindex="0"');
    expect(out).toContain('data-state="closed"');
    expect(out).not.toContain("<button");
    expect(out).not.toContain("title=");
  });

  test("asChild without help is the element itself", () => {
    expect(
      renderToStaticMarkup(
        <Hint text={null} asChild>
          <div className="cell">1,90</div>
        </Hint>,
      ),
    ).toBe('<div class="cell">1,90</div>');
  });
});

describe("a table header with a definition", () => {
  test("is a header whose text opens the definition, not a native title", () => {
    const out = renderToStaticMarkup(
      <table>
        <thead>
          <tr>
            <TH align="right" title="Valoración media de los jugadores del partido">
              Rating
            </TH>
            <TH>Equipo</TH>
          </tr>
        </thead>
      </table>,
    );
    expect(out).toContain('<th scope="col"');
    expect(out).toContain("<button");
    expect(out).toContain(": Valoración media de los jugadores del partido</span>");
    expect(out).not.toContain("title=");
    // the header without a definition is the plain text
    expect(out).toMatch(/<th[^>]*>Equipo<\/th>/);
  });
});
