/// <reference types="bun" />
/** «Del día | Multi-día» (plan de Inicio, 2.4): a switch of two buttons only a phone sees, saying which kind is open. */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { KindSwitch, kindVisibility } from "./KindSwitch";

setLocale("es");

describe("the parlay kind switch", () => {
  test("two buttons named in words, the open one pressed, and gone from md up", () => {
    const html = renderToStaticMarkup(<KindSwitch active="multiday" onChange={() => undefined} />);
    expect(html).toContain("Del día");
    expect(html).toContain("Multi-día");
    expect(html).toMatch(/data-testid="parlay-kind-multiday"[^>]*>/);
    expect(html).toMatch(/aria-pressed="true"[^>]*data-testid="parlay-kind-multiday"/);
    expect(html).toMatch(/aria-pressed="false"[^>]*data-testid="parlay-kind-daily"/);
    expect(html).toContain("md:hidden");
  });

  test("the kind that is not open is hidden on a phone and there from md up", () => {
    expect(kindVisibility("daily", "daily")).toBe("");
    expect(kindVisibility("multiday", "daily")).toBe("hidden md:block");
  });
});
