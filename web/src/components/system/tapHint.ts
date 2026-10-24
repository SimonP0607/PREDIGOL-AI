/**
 * The native `title` attribute is a mouse's tooltip: it shows when a pointer rests on the element and never on a phone or a
 * tablet, so on a touch screen every explanation kept in one was out of reach (mobile UX audit, plan F13: 90 of them). The tap
 * hint (TitleTap) shows the same text when a finger taps a titled element. What decides, and where the hint goes, is here so
 * that it can be tested without a browser.
 */

/** What of an element the decisions need: a DOM element has all of it. */
export interface TitleNode {
  tagName: string;
  parentElement: TitleNode | null;
  getAttribute(name: string): string | null;
  matches(selector: string): boolean;
}

/** A tap on a control, or inside one, does what the control does and shows no hint. */
export const CONTROLS =
  "a[href], button, input, select, textarea, summary, label, [role='button'], [role='link'], [role='tab'], [role='menuitem'], [role='switch'], [role='checkbox'], [role='option']";

/** Elements whose `title` names the element rather than explaining it. */
const NOT_A_TOOLTIP = new Set(["iframe", "object", "embed", "svg"]);

export interface Titled<N extends TitleNode = TitleNode> {
  node: N;
  text: string;
}

/** The nearest element at or above the tapped one that carries a `title`; null when a control is in the way or none has one. */
export function titledTarget<N extends TitleNode>(start: N | null): Titled<N> | null {
  for (let node: N | null = start; node; node = node.parentElement as N | null) {
    if (node.matches(CONTROLS)) return null;
  }
  for (let node: N | null = start; node; node = node.parentElement as N | null) {
    const text = node.getAttribute("title")?.trim();
    if (text && !NOT_A_TOOLTIP.has(node.tagName.toLowerCase())) return { node, text };
  }
  return null;
}

export interface Touch {
  x: number;
  y: number;
  at: number;
}

/** A tap is a finger that went down and up on the same spot, quickly: not a scroll, not a long press. */
export const TAP_MOVE = 10;
export const TAP_MS = 600;

export function isTap(down: Touch, up: Touch): boolean {
  return Math.hypot(up.x - down.x, up.y - down.y) <= TAP_MOVE && up.at - down.at <= TAP_MS;
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface Size {
  width: number;
  height: number;
}

/** Where the hint goes: centred under the element, above it when there is no room below, and always inside the screen. */
export function place(
  target: Box,
  hint: Size,
  view: Size,
  gap = 6,
  margin = 8,
): { left: number; top: number } {
  const centre = target.left + target.width / 2;
  const left = Math.min(
    Math.max(centre - hint.width / 2, margin),
    Math.max(view.width - hint.width - margin, margin),
  );
  const below = target.top + target.height + gap;
  const fits = below + hint.height + margin <= view.height;
  const top = fits ? below : Math.max(target.top - gap - hint.height, margin);
  return { left, top };
}
