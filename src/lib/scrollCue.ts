/**
 * A horizontal strip that scrolls - the Match Center's tabs, a row of chips, a day picker - says so on a phone:
 * its edge fades out where more content waits beyond it (the `scroll-strip` utility draws the fade from the
 * data-fade-start / data-fade-end attributes this hook keeps up to date). Without it the last tab is simply cut
 * at the screen's edge and nothing tells the reader that "Alineaciones" is there (mobile UX audit, Oct 2026).
 */
import { useEffect, type RefObject } from "react";

export interface ScrollCue {
  /** Content hidden before the left edge. */
  start: boolean;
  /** Content hidden past the right edge. */
  end: boolean;
}

/** Where a strip hides content, from its scroll position and sizes (1 px of tolerance for sub-pixel layouts). */
export function scrollCue(scrollLeft: number, scrollWidth: number, clientWidth: number): ScrollCue {
  const max = scrollWidth - clientWidth;
  if (max <= 1) return { start: false, end: false };
  return { start: scrollLeft > 1, end: scrollLeft < max - 1 };
}

function mark(el: HTMLElement, name: string, on: boolean): void {
  if (on) el.setAttribute(name, "");
  else el.removeAttribute(name);
}

/** Keeps the strip's fade attributes in step with its scroll position, its size and its content's size. */
export function useScrollCue(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const cue = scrollCue(el.scrollLeft, el.scrollWidth, el.clientWidth);
      mark(el, "data-fade-start", cue.start);
      mark(el, "data-fade-end", cue.end);
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    resize?.observe(el);
    for (const child of Array.from(el.children)) resize?.observe(child);
    // Children that come and go (a chip list that loads): watch the list itself.
    const mutations =
      typeof MutationObserver === "undefined"
        ? null
        : new MutationObserver(() => {
            for (const child of Array.from(el.children)) resize?.observe(child);
            update();
          });
    mutations?.observe(el, { childList: true });
    return () => {
      el.removeEventListener("scroll", update);
      resize?.disconnect();
      mutations?.disconnect();
    };
  }, [ref]);
}
