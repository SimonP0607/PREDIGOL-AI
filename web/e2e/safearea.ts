/**
 * The installed app's safe areas, simulated (mobile UX plan, UX-090). No browser engine Playwright drives reports the
 * insets of an installed iPhone app: env(safe-area-inset-*) is 0 everywhere. So the page's own styles are rewritten
 * with the insets an iPhone gives an app installed from Safari (black-translucent status bar, viewport-fit=cover):
 * 59 px at the top in portrait (an iPhone with the Dynamic Island; 47 px with the notch), 34 px at the bottom, and
 * held sideways 47 px on each side and 21 px at the bottom. Then nothing a finger needs may sit in those bands.
 *
 * Works on a production build (a <link> stylesheet, fetched and inlined) and on the dev server (<style> tags).
 */
import type { Page } from "@playwright/test";

export interface Insets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const IPHONE_PORTRAIT: Insets = { top: 59, right: 0, bottom: 34, left: 0 };
export const IPHONE_LANDSCAPE: Insets = { top: 0, right: 47, bottom: 21, left: 47 };
/** An iPad's installed app: the status bar only. */
export const IPAD: Insets = { top: 24, right: 0, bottom: 20, left: 0 };

/** Rewrites the page's stylesheets with these insets. Call it after every full page load. */
export async function simulateInsets(page: Page, insets: Insets): Promise<void> {
  await page.evaluate(async (i) => {
    const swap = (css: string) =>
      css.replace(
        /env\(\s*safe-area-inset-(top|right|bottom|left)\s*(?:,[^)]*)?\)/g,
        (_m, side: string) => `${i[side as keyof typeof i]}px`,
      );
    for (const style of Array.from(document.querySelectorAll("style"))) {
      if (style.textContent?.includes("safe-area-inset"))
        style.textContent = swap(style.textContent);
    }
    for (const link of Array.from(
      document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]'),
    )) {
      if (link.disabled) continue;
      // `direct`: the dev server answers a stylesheet's address with a script unless asked for the CSS itself
      const url = new URL(link.href);
      url.searchParams.set("direct", "");
      const res = await fetch(url);
      if (!(res.headers.get("content-type") ?? "").includes("text/css")) continue;
      const css = await res.text();
      if (!css.includes("safe-area-inset")) continue;
      const inline = document.createElement("style");
      inline.textContent = swap(css);
      link.after(inline);
      link.disabled = true;
    }
  }, insets);
  // one frame for the layout to take the new sizes
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(null))));
}

/**
 * Every visible control that reaches into a band of the system: the status bar (top), the notch or the rounded
 * corners held sideways (left, right). The bottom band (the home indicator) is not counted: content scrolls past it.
 * `scope`: a CSS selector - after a scroll only the bars that stay (the header) are asked, not the content under them.
 */
export async function controlsUnderSystemBars(
  page: Page,
  insets: Insets,
  scope = "body",
): Promise<string[]> {
  return page.evaluate(
    ({ i, scope }) => {
      const W = window.innerWidth;
      const out: string[] = [];
      const sel =
        'a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="tab"], [role="switch"], [role="combobox"]';
      const roots = Array.from(document.querySelectorAll(scope));
      const els = roots.flatMap((root) => Array.from(root.querySelectorAll<HTMLElement>(sel)));
      for (const el of els) {
        const b = el.getBoundingClientRect();
        // the part a finger can reach: clipped by every scrolling or clipping box around it (a strip of chips)
        const r = { top: b.top, left: b.left, right: b.right, bottom: b.bottom };
        for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
          const ps = getComputedStyle(p);
          if (ps.overflowX !== "visible" || ps.overflowY !== "visible") {
            const c = p.getBoundingClientRect();
            r.top = Math.max(r.top, c.top);
            r.left = Math.max(r.left, c.left);
            r.right = Math.min(r.right, c.right);
            r.bottom = Math.min(r.bottom, c.bottom);
          }
        }
        if (r.right - r.left < 1 || r.bottom - r.top < 1) continue;
        const s = getComputedStyle(el);
        if (s.visibility === "hidden" || s.display === "none" || Number(s.opacity) === 0) continue;
        if (el.closest('[aria-hidden="true"], [inert]')) continue;
        // off-screen (scrolled away, or a strip's hidden part): not a control under a bar
        if (r.bottom <= 0 || r.top >= window.innerHeight || r.right <= 0 || r.left >= W) continue;
        const name = (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30);
        const id = el.dataset["testid"] ?? el.tagName.toLowerCase();
        if (i.top > 0 && r.top < i.top - 0.5)
          out.push(`${id} «${name}» top ${Math.round(r.top)} < ${i.top}`);
        if (i.left > 0 && r.left < i.left - 0.5)
          out.push(`${id} «${name}» left ${Math.round(r.left)} < ${i.left}`);
        if (i.right > 0 && r.right > W - i.right + 0.5)
          out.push(`${id} «${name}» right ${Math.round(r.right)} > ${W - i.right}`);
      }
      return out;
    },
    { i: insets, scope },
  );
}
