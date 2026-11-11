import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { RADII, TEXT_SIZES, cn } from "./utils";

const css = readFileSync(join(import.meta.dir, "..", "styles.css"), "utf8");

describe("cn() and the design system's own utilities", () => {
  test("a text size of styles.css survives next to a colour", () => {
    for (const size of TEXT_SIZES)
      expect(cn(`text-${size}`, "text-muted-foreground")).toBe(
        `text-${size} text-muted-foreground`,
      );
    // the bug of UX-100: the chip's size was dropped and it took the body's
    expect(cn("text-micro font-medium", "text-warning")).toBe(
      "text-micro font-medium text-warning",
    );
  });

  test("of two text sizes the last one wins, as with Tailwind's own", () => {
    expect(cn("text-micro", "text-caption")).toBe("text-caption");
    expect(cn("text-sm", "text-body")).toBe("text-body");
    expect(cn("text-title", "text-xs")).toBe("text-xs");
  });

  test("a named radius replaces a radius", () => {
    for (const radius of RADII)
      expect(cn("rounded-md", `rounded-${radius}`)).toBe(`rounded-${radius}`);
    expect(cn("rounded-card", "rounded-lg")).toBe("rounded-lg");
  });

  test("every text size of styles.css is registered, and nothing else", () => {
    const declared = [...css.matchAll(/^@utility text-([a-z-]+) \{/gm)].map((m) => m[1]!).sort();
    const registered: string[] = [...TEXT_SIZES];
    expect(registered.sort()).toEqual(declared);
  });

  test("every named radius of styles.css is registered, and nothing else", () => {
    const named = [...css.matchAll(/^ {2}--radius-([a-z]+): [\d.]+rem;/gm)]
      .map((m) => m[1]!)
      .sort();
    const registered: string[] = [...RADII];
    expect(registered.sort()).toEqual(named);
  });
});

describe("the typefaces", () => {
  test("titles and figures are drawn in Archivo, served from PrediGol", () => {
    expect(css).toContain('@import "@fontsource-variable/archivo/wdth.css";');
    expect(css).toMatch(/--font-display:\s+"Archivo Variable", "Archivo", Arial,/);
    expect(css).not.toContain("fonts.googleapis.com/css");
  });
});
