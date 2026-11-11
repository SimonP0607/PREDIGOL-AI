import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { fieldVariants } from "./field";
import { Field } from "./form-field";
import { Input } from "./input";
import { Segmented } from "./segmented";
import { Textarea } from "./textarea";

describe("the field of «Noche de partido»", () => {
  test("16 px text at every size on a phone, so the phone does not zoom in on it", () => {
    for (const size of ["default", "sm", "area"] as const)
      expect(fieldVariants({ size }).split(" ")).toContain("text-base");
  });

  test("the field's own border, a visible focus and a red edge for a wrong value", () => {
    const recipe = fieldVariants();
    expect(recipe).toContain("border-input");
    expect(recipe).toContain("focus-visible:ring-[3px]");
    expect(recipe).toContain("aria-invalid:border-negative");
    expect(fieldVariants({ size: "sm" })).toContain("pointer-coarse:h-11");
  });

  test("Input and Textarea are the recipe, and take what the page adds", () => {
    const input = renderToStaticMarkup(<Input name="alias" className="mt-1" />);
    expect(input).toContain("h-12");
    expect(input).toContain("mt-1");
    expect(renderToStaticMarkup(<Input fieldSize="sm" />)).toContain("h-10");
    expect(renderToStaticMarkup(<Textarea rows={4} />)).toContain("min-h-[6.5rem]");
  });
});

describe("a field with its label, help and error", () => {
  const draw = (error?: string) =>
    renderToStaticMarkup(
      <Field id="mail" label="Correo" hint="Solo para tu cuenta." error={error}>
        {(control) => <input type="email" {...control} />}
      </Field>,
    );

  test("the label names the control and the help describes it", () => {
    const html = draw();
    expect(html).toMatch(/<label[^>]*for="mail"[^>]*>Correo<\/label>/);
    expect(html).toMatch(/<input[^>]*id="mail"[^>]*aria-describedby="mail-hint"/);
    expect(html).toContain('id="mail-hint"');
    expect(html).not.toContain("aria-invalid");
  });

  test("an error takes the help's place, in words with an icon, and marks the control", () => {
    const html = draw("Escribe un correo válido.");
    expect(html).toMatch(/<input[^>]*aria-describedby="mail-error"[^>]*aria-invalid="true"/);
    expect(html).toMatch(/<p[^>]*role="alert"[^>]*id="mail-error"/);
    expect(html).toContain("<svg");
    expect(html).toContain("Escribe un correo válido.");
    expect(html).not.toContain("Solo para tu cuenta.");
  });
});

describe("the segmented control", () => {
  const draw = (value: string) =>
    renderToStaticMarkup(
      <Segmented
        label="Idioma"
        value={value}
        onChange={() => undefined}
        testId="lang"
        options={[
          { value: "es", label: "ES", name: "Español" },
          { value: "en", label: "EN", name: "English" },
        ]}
      />,
    );

  test("a named radio group with one segment chosen and one stop of Tab", () => {
    const html = draw("en");
    expect(html).toMatch(/<div[^>]*role="radiogroup"[^>]*aria-label="Idioma"/);
    // the visible label stays in the accessible name (WCAG 2.5.3): «EN English», never an aria-label in its place
    expect(html).toMatch(
      /role="radio"[^>]*aria-checked="true"[^>]*>EN<span class="sr-only">English<\/span>/,
    );
    expect(html).not.toContain('aria-label="English"');
    expect(html.match(/tabindex="0"/g)?.length).toBe(1);
    expect(html.match(/tabindex="-1"/g)?.length).toBe(1);
    expect(html).toContain('data-testid="lang-es"');
  });

  test("with nothing chosen the first segment still takes the keyboard", () => {
    const html = draw("fr");
    expect(html).not.toContain('aria-checked="true"');
    expect(html).toMatch(/aria-checked="false"[^>]*tabindex="0"[^>]*>ES</);
  });
});
