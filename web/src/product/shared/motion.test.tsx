/// <reference types="bun" />
/**
 * The motion system (closing plan 5.1), without a browser: the three durations are the same in the code and in the CSS,
 * «reduce motion» still every animation and transition (a spinner aside), a score only flashes when it changes (never
 * on the first render), no animation needs a library, and the screens cross-fade where the browser can.
 */
import { readFileSync } from "node:fs";
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { GoalDigit } from "./GoalDigit";
import { FLASH_MS, MOTION } from "./motion";

const css = readFileSync(new URL("../../styles.css", import.meta.url), "utf8");
const router = readFileSync(new URL("../../router.tsx", import.meta.url), "utf8");
const pkg = JSON.parse(readFileSync(new URL("../../../package.json", import.meta.url), "utf8")) as {
  dependencies: Record<string, string>;
};

describe("durations", () => {
  test("120, 200 and 300 ms, the same in the code and in the CSS", () => {
    expect(MOTION).toEqual({ fast: 120, base: 200, slow: 300 });
    expect(css).toContain("--motion-fast: 120ms");
    expect(css).toContain("--motion-base: 200ms");
    expect(css).toContain("--motion-slow: 300ms");
    expect(FLASH_MS).toBe(1200);
    expect(css).toContain("motion-goal 1200ms");
  });

  test("no animation library came with it", () => {
    for (const name of Object.keys(pkg.dependencies)) {
      expect(name).not.toMatch(/framer-motion|motion$|react-spring|gsap|lottie|auto-animate/);
    }
  });
});

describe("reduced motion", () => {
  const block = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
  test("every animation and transition is cut to nothing, view transitions too", () => {
    expect(block).toContain("animation-duration: 0.01ms !important");
    expect(block).toContain("animation-iteration-count: 1 !important");
    expect(block).toContain("transition-duration: 0.01ms !important");
    expect(block).toContain("::view-transition-old(*)");
  });
  test("a spinner keeps turning: it says «loading»", () => {
    expect(block).toMatch(/\.animate-spin\s*\{[^}]*infinite/);
  });
});

describe("screens and marks", () => {
  test("the router cross-fades between screens", () => {
    expect(router).toContain("defaultViewTransition: true");
  });

  test("a score never flashes on the first render, and shows its number", () => {
    const out = renderToStaticMarkup(<GoalDigit value={2} className="numeric" />);
    expect(out).toContain(">2<");
    expect(out).not.toContain("motion-goal");
    expect(renderToStaticMarkup(<GoalDigit value={null}>–</GoalDigit>)).toContain("–");
  });
});
