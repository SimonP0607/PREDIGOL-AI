import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Button, buttonVariants } from "./button";

describe("the button of «Noche de partido»", () => {
  test("it is a button that does not submit a form unless told to", () => {
    const html = renderToStaticMarkup(<Button>Guardar</Button>);
    expect(html).toContain('type="button"');
    expect(renderToStaticMarkup(<Button type="submit">Entrar</Button>)).toContain('type="submit"');
  });

  test("busy: it says so, takes no press and keeps its words", () => {
    const html = renderToStaticMarkup(<Button loading>Guardando</Button>);
    expect(html).toContain('aria-busy="true"');
    expect(html).toMatch(/<button[^>]* disabled=""/);
    expect(html).toContain("animate-spin");
    expect(html).toContain("Guardando");
    expect(renderToStaticMarkup(<Button>Guardar</Button>)).not.toContain("aria-busy=");
  });

  test("the five kinds are told apart, and the older names draw the same ones", () => {
    const kinds = ["primary", "secondary", "text", "gold", "danger"] as const;
    expect(new Set(kinds.map((variant) => buttonVariants({ variant }))).size).toBe(5);
    expect(buttonVariants({ variant: "default" })).toBe(buttonVariants({ variant: "primary" }));
    expect(buttonVariants({ variant: "outline" })).toBe(buttonVariants({ variant: "secondary" }));
    expect(buttonVariants({ variant: "destructive" })).toBe(buttonVariants({ variant: "danger" }));
  });

  test("every kind shows the keyboard's focus, and the small heights reach 44 px under a finger", () => {
    for (const variant of [
      "primary",
      "secondary",
      "text",
      "gold",
      "danger",
      "ghost",
      "link",
    ] as const)
      expect(buttonVariants({ variant })).toContain("focus-visible:outline-2");
    expect(buttonVariants({ size: "sm" })).toContain("tap-y");
    expect(buttonVariants({ size: "xs" })).toContain("tap-y");
    expect(buttonVariants({ size: "default" })).toContain("h-12");
  });

  test("as a link it keeps the link's own element", () => {
    const html = renderToStaticMarkup(
      <Button asChild variant="secondary">
        <a href="/help">Ayuda</a>
      </Button>,
    );
    expect(html).toMatch(/^<a [^>]*href="\/help"/);
    expect(html).not.toContain("<button");
  });
});
