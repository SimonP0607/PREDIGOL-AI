/// <reference types="bun" />
/**
 * Plan F13, the tap hint: a native `title` never shows on a touch screen, so a tap on a titled element shows its text. What it
 * decides - which element, when it stays quiet, where it goes - is held here without a browser.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { CONTROLS, hintProps, isTap, place, titledTarget, type TitleNode } from "./tapHint";

class Fake implements TitleNode {
  constructor(
    readonly tagName: string,
    private readonly attrs: Record<string, string> = {},
    readonly parentElement: Fake | null = null,
  ) {}

  getAttribute(name: string): string | null {
    return this.attrs[name] ?? null;
  }

  /** Enough of a selector for CONTROLS: `tag`, `tag[attr]` and `[attr='value']`, comma separated. */
  matches(selector: string): boolean {
    return selector.split(",").some((part) => {
      const m = /^\s*([a-z]*)(?:\[([a-z-]+)(?:='([^']*)')?\])?\s*$/.exec(part);
      if (!m) return false;
      const [, tag = "", attr, value] = m;
      if (tag && tag !== this.tagName.toLowerCase()) return false;
      if (!attr) return tag !== "";
      const have = this.attrs[attr];
      return value === undefined ? have !== undefined : have === value;
    });
  }
}

const body = new Fake("BODY");
const cell = new Fake("TD", {}, body);

describe("titledTarget", () => {
  test("the tapped element's own title", () => {
    const span = new Fake("SPAN", { title: "Partidos jugados" }, cell);
    expect(titledTarget(span)).toEqual({ node: span, text: "Partidos jugados" });
  });

  test("a tap on something inside a titled element finds the nearest title above it", () => {
    const outer = new Fake("DIV", { title: "outer" }, cell);
    const inner = new Fake("SPAN", { title: "inner" }, outer);
    const text = new Fake("EM", {}, inner);
    expect(titledTarget(text)?.text).toBe("inner");
    expect(titledTarget(new Fake("EM", {}, outer))?.text).toBe("outer");
  });

  test("a control is a control: a tap on a link, a button or a field shows nothing, wherever the title is", () => {
    const link = new Fake("A", { href: "/matches/1", title: "the link's own" }, cell);
    expect(titledTarget(link)).toBeNull();
    const titled = new Fake("SPAN", { title: "reason" }, link);
    expect(titledTarget(titled)).toBeNull();
    const button = new Fake("BUTTON", {}, cell);
    expect(titledTarget(new Fake("SPAN", { title: "reason" }, button))).toBeNull();
    const role = new Fake("DIV", { role: "button" }, cell);
    expect(titledTarget(new Fake("SPAN", { title: "reason" }, role))).toBeNull();
    // an anchor without an href is not a link
    const plain = new Fake("A", {}, cell);
    expect(titledTarget(new Fake("SPAN", { title: "reason" }, plain))?.text).toBe("reason");
  });

  test("a blank title, or the title of an element that only names itself, is not a hint", () => {
    expect(titledTarget(new Fake("SPAN", { title: "   " }, cell))).toBeNull();
    expect(titledTarget(new Fake("SPAN", {}, cell))).toBeNull();
    expect(titledTarget(new Fake("IFRAME", { title: "Map" }, cell))).toBeNull();
    expect(titledTarget(new Fake("svg", { title: "Chart" }, cell))).toBeNull();
    expect(titledTarget(null)).toBeNull();
  });

  test("a data-hint speaks even inside a card's link, and says so, so that tap does not follow the link", () => {
    // plan UX, A1 (F16): a card is one link; the help on its figures could never be read with a finger
    const link = new Fake("A", { href: "/matches/1" }, cell);
    const figure = new Fake(
      "SPAN",
      { "data-hint": "Valor esperado", title: "Valor esperado" },
      link,
    );
    const glyph = new Fake("svg", {}, figure);
    expect(titledTarget(figure)).toEqual({ node: figure, text: "Valor esperado", inControl: true });
    expect(titledTarget(glyph)?.text).toBe("Valor esperado");
    // the rest of the card still opens the match
    expect(titledTarget(new Fake("SPAN", {}, link))).toBeNull();
    // outside a control it is a hint like a title
    expect(titledTarget(new Fake("SPAN", { "data-hint": "x" }, cell))?.inControl).toBe(false);
    // a button's own data-hint is the button's business: the button acts
    const button = new Fake("BUTTON", { "data-hint": "y" }, cell);
    expect(titledTarget(button)).toBeNull();
    expect(titledTarget(new Fake("SPAN", { "data-hint": "  " }, link))).toBeNull();
  });

  test("hintProps gives a figure both: a title for a mouse, a data-hint for a finger", () => {
    expect(hintProps(" Valor esperado ")).toEqual({
      title: "Valor esperado",
      "data-hint": "Valor esperado",
    });
    expect(hintProps("")).toEqual({});
    expect(hintProps(null)).toEqual({});
  });

  test("the list of controls is the one the selector says", () => {
    for (const part of ["a[href]", "button", "input", "select", "textarea", "summary", "label"]) {
      expect(CONTROLS).toContain(part);
    }
  });
});

describe("isTap", () => {
  const down = { x: 100, y: 100, at: 1000 };

  test("a finger that went down and up on the same spot, quickly", () => {
    expect(isTap(down, { x: 103, y: 104, at: 1120 })).toBe(true);
  });

  test("a scroll or a swipe is not a tap", () => {
    expect(isTap(down, { x: 100, y: 160, at: 1120 })).toBe(false);
  });

  test("neither is a long press", () => {
    expect(isTap(down, { x: 100, y: 100, at: 1900 })).toBe(false);
  });
});

describe("place", () => {
  const view = { width: 390, height: 800 };
  const hint = { width: 200, height: 40 };

  test("centred under the element", () => {
    expect(place({ left: 150, top: 100, width: 90, height: 20 }, hint, view)).toEqual({
      left: 95,
      top: 126,
    });
  });

  test("kept inside the screen on both sides", () => {
    expect(place({ left: 0, top: 100, width: 20, height: 20 }, hint, view).left).toBe(8);
    expect(place({ left: 370, top: 100, width: 20, height: 20 }, hint, view).left).toBe(182);
  });

  test("above the element when there is no room below", () => {
    expect(place({ left: 150, top: 770, width: 90, height: 20 }, hint, view)).toEqual({
      left: 95,
      top: 724,
    });
  });

  test("never off the top either", () => {
    expect(
      place({ left: 150, top: 10, width: 90, height: 20 }, hint, { width: 390, height: 60 }).top,
    ).toBe(8);
  });
});

describe("the root mounts it", () => {
  test("__root.tsx renders <TitleTap />, once, inside the app", () => {
    const root = readFileSync(join(import.meta.dir, "..", "..", "routes", "__root.tsx"), "utf8");
    expect(root.match(/<TitleTap \/>/g)?.length).toBe(1);
    expect(root).toContain('from "@/components/system/TitleTap"');
  });
});
