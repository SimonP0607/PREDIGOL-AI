/**
 * Text that fits its box (mobile UX plan, UX-094). A row squeezed by what sits beside it (the odds, a state, the
 * bookmakers) left a team's name 66 px and the browser broke it between letters - «Gana Sandefjord» on three lines,
 * «Berkhamsted» in two halves. These helpers find a word broken across lines, and give the page longer names than the
 * QA data has, so a test sees the names production has (Borussia Mönchengladbach, Deportivo Independiente Medellín).
 */
import type { Page } from "@playwright/test";

/** Real names, the longest words a row must hold whole. */
export const LONG_NAMES = [
  "Borussia Mönchengladbach",
  "Wolverhampton Wanderers",
  "Deportivo Independiente Medellín",
  "Liptovský Mikuláš",
];

/**
 * Words of up to `maxLen` letters drawn on more than one line, inside `scope`. A longer word may break where nothing
 * else can hold it; one of 16 letters or fewer breaks only because its box is too narrow.
 */
export async function splitWords(page: Page, scope = "main", maxLen = 16): Promise<string[]> {
  return page.evaluate(
    ({ scope, maxLen }) => {
      const out: string[] = [];
      for (const root of Array.from(document.querySelectorAll(scope))) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        for (let n = walker.nextNode(); n; n = walker.nextNode()) {
          const el = n.parentElement;
          const text = n.textContent ?? "";
          if (!el || !text.trim()) continue;
          const box = el.getBoundingClientRect();
          if (box.width < 1 || box.height < 1) continue;
          const s = getComputedStyle(el);
          if (s.visibility === "hidden" || s.textOverflow === "ellipsis") continue;
          for (const m of text.matchAll(/[\p{L}\p{N}]{4,}/gu)) {
            if (m[0].length > maxLen) continue;
            const range = document.createRange();
            range.setStart(n, m.index ?? 0);
            range.setEnd(n, (m.index ?? 0) + m[0].length);
            const tops = new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top)));
            if (tops.size > 1)
              out.push(`«${m[0]}» in «${text.trim().slice(0, 40)}» (${Math.round(box.width)} px)`);
          }
        }
      }
      return out;
    },
    { scope, maxLen },
  );
}

/** Gives every team name on the page (data-testid="team-name") and every mention of it a long real name. */
export async function lengthenNames(page: Page): Promise<number> {
  return page.evaluate((longNames) => {
    const names = Array.from(document.querySelectorAll('[data-testid="team-name"]'))
      .map((e) => (e.textContent ?? "").trim())
      .filter((t) => t.length > 2);
    const unique = Array.from(new Set(names)).sort((a, b) => b.length - a.length);
    const swap = new Map(unique.map((n, i) => [n, longNames[i % longNames.length] ?? n]));
    let changed = 0;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes: Text[] = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n as Text);
    for (const node of nodes) {
      let text = node.textContent ?? "";
      for (const [from, to] of swap) if (text.includes(from)) text = text.split(from).join(to);
      if (text !== node.textContent) {
        node.textContent = text;
        changed += 1;
      }
    }
    return changed;
  }, LONG_NAMES);
}

/**
 * Text cut with «…» inside `scope` (mobile UX plan, UX-095): a section's title, the bookmaker with the best price, the
 * logo's tagline. Their whole text was only in a hover hint, which a phone never shows.
 */
export async function ellipsized(page: Page, scope: string): Promise<string[]> {
  return page.evaluate((scope) => {
    const out: string[] = [];
    for (const root of Array.from(document.querySelectorAll(scope))) {
      for (const el of [root, ...Array.from(root.querySelectorAll("*"))]) {
        const s = getComputedStyle(el);
        if (s.textOverflow !== "ellipsis" || s.display === "none") continue;
        if (el.getBoundingClientRect().width < 1) continue;
        if (el.scrollWidth > el.clientWidth + 1)
          out.push(
            `«${(el.textContent ?? "").trim().slice(0, 50)}» ${el.clientWidth}/${el.scrollWidth} px`,
          );
      }
    }
    return out;
  }, scope);
}
