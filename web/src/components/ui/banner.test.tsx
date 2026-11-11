import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Banner, type BannerTone } from "./banner";

const TONES: BannerTone[] = ["info", "success", "warning", "danger", "gold", "neutral"];

describe("the banner of «Noche de partido»", () => {
  test("each tone has its own icon and its own colours: the colour never says it alone", () => {
    const drawn = TONES.map((tone) => renderToStaticMarkup(<Banner tone={tone}>x</Banner>));
    for (const html of drawn) expect(html).toContain("<svg");
    const boxes = drawn.map((html) => /class="([^"]*)"/.exec(html)?.[1] ?? "");
    expect(new Set(boxes).size).toBe(TONES.length);
    const icons = drawn.map((html) => /<svg[^>]*class="([^"]*)"/.exec(html)?.[1] ?? "");
    expect(new Set(icons).size).toBeGreaterThanOrEqual(5);
  });

  test("an error is announced at once; the others belong to the page unless told otherwise", () => {
    expect(renderToStaticMarkup(<Banner tone="danger">x</Banner>)).toContain('role="alert"');
    expect(renderToStaticMarkup(<Banner tone="warning">x</Banner>)).not.toContain("role=");
    expect(
      renderToStaticMarkup(
        <Banner tone="success" role="status">
          x
        </Banner>,
      ),
    ).toContain('role="status"');
  });

  test("closing it is a named button, and it is there only when the band can be closed", () => {
    const html = renderToStaticMarkup(
      <Banner onDismiss={() => undefined} dismissLabel="Cerrar aviso">
        Mantenimiento el jueves
      </Banner>,
    );
    expect(html).toMatch(/<button[^>]*aria-label="Cerrar aviso"/);
    expect(renderToStaticMarkup(<Banner>x</Banner>)).not.toContain("<button");
  });

  test("its action sits at the end, and no icon when asked for none", () => {
    const html = renderToStaticMarkup(
      <Banner tone="warning" icon={false} action={<a href="/profile">Cómo renovar</a>}>
        Tu membresía termina el viernes
      </Banner>,
    );
    expect(html).not.toContain("<svg");
    expect(html.indexOf("Tu membresía")).toBeLessThan(html.indexOf("Cómo renovar"));
  });
});
