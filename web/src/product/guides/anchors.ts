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

/** Another layer is open over the page (a sheet, the slip, «Explícame», a dialog): a guide never goes over it. */
export function anotherLayerOpen(root: ParentNode = document): boolean {
  return Boolean(
    root.querySelector(
      '[role="dialog"]:not([data-guide-card]), [role="alertdialog"], [data-radix-popper-content-wrapper]',
    ),
  );
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
