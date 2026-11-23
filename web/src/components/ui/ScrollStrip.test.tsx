/// <reference types="bun" />
/** AP-C02: the shared strip of chips (arrows from 1024 px, the chip that is on always in view). */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { pageStep, revealOffset, ScrollStrip } from "./ScrollStrip";

describe("the chip that is on stays in view", () => {
  const strip = { left: 100, right: 500, scrollLeft: 40 };

  test("a chip that is wholly inside the strip needs no scrolling", () => {
    expect(revealOffset(strip, { left: 150, right: 230 })).toBeNull();
  });

  test("a chip cut at the right edge brings the strip forward, with the margin", () => {
    // its right edge is 40 px past the strip's (500): 40 + the 8 px of margin
    expect(revealOffset(strip, { left: 460, right: 540 })).toBe(40 + 48);
  });

  test("a chip cut at the left edge takes the strip back", () => {
    expect(revealOffset(strip, { left: 80, right: 160 })).toBe(40 - 28);
  });

  test("from 1024 px the arrows' room is kept clear", () => {
    expect(revealOffset(strip, { left: 400, right: 480 }, 52)).toBe(40 + 32);
    expect(revealOffset(strip, { left: 400, right: 480 })).toBeNull();
  });
});

describe("what an arrow does", () => {
  test("moves most of what is in view, never less than a chip", () => {
    expect(pageStep(1000)).toBe(800);
    expect(pageStep(100)).toBe(120);
  });
});

describe("the strip", () => {
  const html = renderToStaticMarkup(
    <ScrollStrip role="tablist" aria-label="Mercados" data-testid="tabs" className="flex gap-1">
      <button role="tab" aria-selected="true">
        1X2
      </button>
    </ScrollStrip>,
  );

  test("is the element with the props given, inside a wrapper the layout guard knows", () => {
    expect(html).toContain('data-strip-arrows=""');
    expect(html).toContain('role="tablist"');
    expect(html).toContain('aria-label="Mercados"');
    expect(html).toContain('data-testid="tabs"');
    expect(html).toContain("scroll-strip");
  });

  test("has no arrows until something is hidden", () => {
    expect(html).not.toContain("data-strip-arrow=");
  });
});
