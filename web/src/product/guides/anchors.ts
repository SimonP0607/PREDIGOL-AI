/**
 * Where a guide step rests (plan UX-051): the first visible element carrying one of its `data-guide` values. The tab bar and the
 * top bar are both in the page and one of them is always hidden, so "the element" is the one that has a box on the screen.
 */
import type { StepDef } from "./registry";

/** The element of an anchor that is on the screen now, or null: hidden (display none, zero size) ones do not count. */
export function findAnchor(
  anchors: readonly string[],
  root: ParentNode = document,
): HTMLElement | null {
  for (const name of anchors) {
    for (const el of Array.from(root.querySelectorAll<HTMLElement>(`[data-guide="${name}"]`))) {
      if (el.getClientRects().length === 0) continue;
      const box = el.getBoundingClientRect();
      if (box.width > 0 && box.height > 0) return el;
    }
  }
  return null;
}

/** Whether a step can be shown now: a card of its own always can; a step on an element only when the element is on the screen. */
export function resolvable(
  step: StepDef,
  find: (anchors: readonly string[]) => unknown = findAnchor,
): boolean {
  return step.anchors.length === 0 || Boolean(find(step.anchors));
}

const LAYERS =
  '[role="dialog"]:not([data-guide-card]), [role="alertdialog"], [data-radix-popper-content-wrapper]';

/**
 * Another layer is open over the page (a sheet, the slip, «Explícame», a dialog): a guide never goes over it. A layer that is
 * closing does not count (UX-070): «Más» stays in the page for its exit animation (`data-state="closed"`) while the screen it
 * opened is already there, and that screen's guide must not wait for a sheet the reader already closed.
 */
export function anotherLayerOpen(root: ParentNode = document): boolean {
  for (const layer of Array.from(root.querySelectorAll<HTMLElement>(LAYERS))) {
    const state =
      layer.getAttribute("data-state") ?? layer.firstElementChild?.getAttribute("data-state");
    if (state !== "closed") return true;
  }
  return false;
}

/** Where the card goes (plan UX-051, section 8): a box in the viewport's pixels, kept clear of the edges. */
export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface Placement {
  top: number;
  left: number;
}

/**
 * The ring's frame (AP-P03, audit P1): the union of what the element really shows, clipped to its own box. The audit found
 * the ring around a whole row where only a few chips stood («matches-status», «match-tabs»), because the anchor is a
 * block that is as wide as its row. The union ignores the empty room; the layer adds its 6 px of margin around it.
 */
export function unionBox(own: Box, parts: readonly Box[]): Box {
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const p of parts) {
    if (p.width <= 0 || p.height <= 0) continue;
    left = Math.min(left, p.left);
    top = Math.min(top, p.top);
    right = Math.max(right, p.left + p.width);
    bottom = Math.max(bottom, p.top + p.height);
  }
  // a strip that scrolls has children past its box: only what is inside the box can be ringed
  left = Math.max(left, own.left);
  top = Math.max(top, own.top);
  right = Math.min(right, own.left + own.width);
  bottom = Math.min(bottom, own.top + own.height);
  if (!(right > left && bottom > top)) return own;
  return { left, top, width: right - left, height: bottom - top };
}

/** Elements that are one thing to the eye however many boxes they hold: their own box is the content. */
const ATOMIC = new Set([
  "button",
  "a",
  "input",
  "select",
  "textarea",
  "svg",
  "img",
  "picture",
  "canvas",
  "video",
  "progress",
  "meter",
]);

function rect(el: Element | Range): Box {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

/** Whether the element draws something of its own (a fill, a border, a shadow): then its box is part of what is seen. */
function paints(el: Element): boolean {
  const cs = getComputedStyle(el);
  const fill = cs.backgroundColor;
  if (fill !== "" && fill !== "transparent" && !/^rgba\(\s*0,\s*0,\s*0,\s*0\s*\)$/.test(fill))
    return true;
  if (cs.backgroundImage !== "none") return true;
  if (cs.boxShadow !== "none") return true;
  return ["Top", "Right", "Bottom", "Left"].some((side) => {
    const w = Number.parseFloat(cs.getPropertyValue(`border-${side.toLowerCase()}-width`));
    return w > 0 && cs.getPropertyValue(`border-${side.toLowerCase()}-style`) !== "none";
  });
}

function gather(node: Element, out: Box[]): void {
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType === 3) {
      if (!child.textContent?.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(child);
      for (const r of Array.from(range.getClientRects()))
        out.push({ top: r.top, left: r.left, width: r.width, height: r.height });
      continue;
    }
    if (child.nodeType !== 1) continue;
    const el = child as HTMLElement;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || cs.position === "fixed") continue;
    // «display: contents» has no box of its own: what it holds is looked at in its place
    if (cs.display === "contents") {
      gather(el, out);
      continue;
    }
    if (el.getClientRects().length === 0) continue;
    if (ATOMIC.has(el.localName) || paints(el)) {
      const r = rect(el);
      if (r.width > 0 && r.height > 0) out.push(r);
      continue;
    }
    gather(el, out);
  }
}

/** What the reader sees of an anchor: its own box when it draws one (a card), else the union of what it holds. */
export function contentBox(el: HTMLElement): Box {
  const own = rect(el);
  // a button, a link or a drawing is one thing: its own box, tap target included, is what the reader touches
  if (ATOMIC.has(el.localName) || paints(el)) return own;
  const parts: Box[] = [];
  gather(el, parts);
  return parts.length > 0 ? unionBox(own, parts) : own;
}

const GAP = 12;
const EDGE = 12;

/**
 * Beside the element on a desk: below it when there is room, else above, else docked to the bottom left; the card never
 * leaves the viewport. (Below 1024 px the card is docked to the bottom by the page's own classes, over the tab bar.)
 */
export function placeCard(
  anchor: Box | null,
  card: { width: number; height: number },
  view: { width: number; height: number },
): Placement {
  const maxLeft = Math.max(EDGE, view.width - card.width - EDGE);
  const maxTop = Math.max(EDGE, view.height - card.height - EDGE);
  if (!anchor) {
    return {
      top: Math.round(Math.min(maxTop, Math.max(EDGE, (view.height - card.height) / 2))),
      left: Math.round(Math.min(maxLeft, Math.max(EDGE, (view.width - card.width) / 2))),
    };
  }
  const left = Math.round(Math.min(maxLeft, Math.max(EDGE, anchor.left)));
  const below = anchor.top + anchor.height + GAP;
  if (below + card.height <= view.height - EDGE) return { top: Math.round(below), left };
  const above = anchor.top - GAP - card.height;
  if (above >= EDGE) return { top: Math.round(above), left };
  return { top: Math.round(maxTop), left: EDGE };
}
