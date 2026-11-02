/// <reference types="bun" />
/** The server's own error page speaks the reader's language (plan UX, A1, defect F08: it was English only). */
import { describe, expect, test } from "bun:test";
import { renderErrorPage } from "./error-page";

describe("the server's error page", () => {
  test("in Spanish by default, with lang=es", () => {
    const html = renderErrorPage();
    expect(html).toContain('<html lang="es">');
    expect(html).toContain("Esta página no se ha podido cargar");
    expect(html).toContain("Reintentar");
    expect(html).not.toContain("didn't load");
  });

  test("in English when the reader reads English", () => {
    const html = renderErrorPage("en");
    expect(html).toContain('<html lang="en">');
    expect(html).toContain("This page didn't load");
    expect(html).not.toContain("Reintentar");
  });
});
