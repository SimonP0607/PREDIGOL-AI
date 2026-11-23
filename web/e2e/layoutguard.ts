/**
 * Layout guards that the whole suite shares (Plan Maestro de Correcciones, AP-Q03 and AP-Q04).
 *
 * «Texto en cascada»: the owner's audit found «Profundizar» drawn as a column of single letters at 1280-1440 px and the
 * parlay's total pressed against its label. Nothing in the suite measured a column's width, so a grid that answered to
 * the screen's width and not to its container (UX-145) went to production. These helpers measure what a reader sees:
 * a text box too narrow for its words, a block wider than the box that holds it, and a row of chips with more chips
 * than fit and no way to reach them with a mouse.
 */
import type { Page } from "@playwright/test";

/** The nine widths of the plan's tour (phones, tablets, desks). */
export const NINE_WIDTHS = [320, 390, 430, 768, 820, 1024, 1280, 1440, 1920] as const;

export interface Finding {
  kind: "cascade" | "overflow" | "strip";
  /** A stable address of the element: its test id, or its tag and first classes, and the start of its text. */
  at: string;
}

/**
 * Text boxes narrower than 48 px that need more than three lines for their text (a column of letters), inside `scope`.
 * A box that holds one short word (a badge, a number) is not a cascade: the text must have 6 letters or more.
 */
export async function cascades(page: Page, scope = "main"): Promise<Finding[]> {
  return page.evaluate((root) => {
    const out: Finding[] = [];
    const address = (el: Element, text: string): string => {
      const id = el.closest("[data-testid]")?.getAttribute("data-testid");
      const cls = (el.getAttribute("class") ?? "").split(/\s+/).slice(0, 3).join(".");
      return `${id ? `[${id}] ` : ""}${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""} «${text.slice(0, 24)}»`;
    };
    for (const container of Array.from(document.querySelectorAll(root))) {
      const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
      const seen = new Set<Element>();
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const el = n.parentElement;
        const text = (n.textContent ?? "").trim();
        if (!el || seen.has(el) || text.replace(/\s/g, "").length < 6) continue;
        seen.add(el);
        const box = el.getBoundingClientRect();
        if (box.width < 1 || box.height < 1) continue;
        const style = getComputedStyle(el);
        if (style.visibility === "hidden" || style.display === "none") continue;
        if (el.closest("[aria-hidden='true'], [hidden], svg")) continue;
        const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;
        const lines = Math.round(box.height / line);
        if (box.width < 48 && lines > 3) out.push({ kind: "cascade", at: address(el, text) });
      }
    }
    return out;
  }, scope);
}

/**
 * Blocks that stick out of the box that holds them: the page wider than the screen, or a child past its parent's right
 * edge when the parent does not scroll or clip. Pictograms, absolutely placed layers and the scroll strips (their
 * content is meant to go beyond the edge) do not count.
 */
export async function overflowing(page: Page, scope = "main"): Promise<Finding[]> {
  return page.evaluate((root) => {
    const out: Finding[] = [];
    const address = (el: Element): string => {
      const id = el.closest("[data-testid]")?.getAttribute("data-testid");
      const cls = (el.getAttribute("class") ?? "").split(/\s+/).slice(0, 3).join(".");
      const text = (el.textContent ?? "").trim().slice(0, 24);
      return `${id ? `[${id}] ` : ""}${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""} «${text}»`;
    };
    const vw = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > vw + 1)
      out.push({
        kind: "overflow",
        at: `page ${document.documentElement.scrollWidth} px > ${vw} px`,
      });
    const clips = (el: Element): boolean => {
      const s = getComputedStyle(el);
      return ["hidden", "auto", "scroll", "clip"].includes(s.overflowX);
    };
    for (const container of Array.from(document.querySelectorAll(root))) {
      for (const el of Array.from(container.querySelectorAll("*"))) {
        const parent = el.parentElement;
        if (!parent || el.closest("svg, [aria-hidden='true']")) continue;
        const s = getComputedStyle(el);
        if (s.position === "absolute" || s.position === "fixed" || s.display === "none") continue;
        if (s.visibility === "hidden" || el.tagName === "BR") continue;
        // A bar that bleeds to the screen's edge (-mx-4) is wider than its parent on purpose.
        if (parseFloat(s.marginLeft) < 0 || parseFloat(s.marginRight) < 0) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) continue;
        let clipped = false;
        for (let p: Element | null = parent; p && p !== document.body; p = p.parentElement) {
          if (clips(p)) {
            clipped = true;
            break;
          }
        }
        if (clipped) continue;
        const pr = parent.getBoundingClientRect();
        if (pr.width < 2) continue;
        if (r.right > pr.right + 2 && r.left < pr.right)
          out.push({ kind: "overflow", at: address(el) });
      }
    }
    return out;
  }, scope);
}

/**
 * A row of chips whose content is wider than the row, with the scrollbar hidden, and nothing to move it with a mouse:
 * no arrows next to it and no wrapping (AP-Q04). Only meaningful from 1024 px; a finger swipes the row on a phone.
 */
export async function unreachableStrips(page: Page): Promise<Finding[]> {
  return page.evaluate(() => {
    const out: Finding[] = [];
    for (const el of Array.from(document.querySelectorAll("*"))) {
      const s = getComputedStyle(el);
      if (!["auto", "scroll"].includes(s.overflowX)) continue;
      if (el.scrollWidth <= el.clientWidth + 2) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 1) continue;
      const bar =
        s.scrollbarWidth === "none" ||
        getComputedStyle(el, "::-webkit-scrollbar").display === "none";
      if (!bar) continue;
      // Reachable: it carries its own arrows (data-strip-arrows) or the row it sits in has previous/next buttons.
      const arrows =
        el.closest("[data-strip-arrows]") !== null ||
        el.parentElement?.querySelector("button[data-strip-arrow]") != null;
      if (arrows) continue;
      const id = el.closest("[data-testid]")?.getAttribute("data-testid");
      const cls = (el.getAttribute("class") ?? "").split(/\s+/).slice(0, 3).join(".");
      const first = (el.textContent ?? "").trim().slice(0, 24);
      out.push({
        kind: "strip",
        at: `${id ? `[${id}] ` : ""}${el.tagName.toLowerCase()}.${cls} «${first}»`,
      });
    }
    return out;
  });
}
