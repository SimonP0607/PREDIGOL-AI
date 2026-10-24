import { useCallback, useEffect, useState } from "react";

/**
 * A page's tab in the address (`/admin/models#tab=markets`), so a reload keeps it and a link can name it (plan F13: the Admin
 * Console's tabs started again on the first one at every reload). It lives in the hash, which the server never sees and the
 * router does not own: choosing a tab replaces the current entry of the history (the back button still leaves the page), and a
 * page with two sets of tabs gives each its own parameter.
 */

/** The tab a hash names, when it is one of `tabs`; null otherwise. */
export function tabFromHash(hash: string, tabs: readonly string[], param = "tab"): string | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get(param);
  return value !== null && tabs.includes(value) ? value : null;
}

/** The hash with `param` set to `tab` (removed when null), every other parameter as it was. "" when nothing is left. */
export function hashWithTab(hash: string, param: string, tab: string | null): string {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  if (tab === null) params.delete(param);
  else params.set(param, tab);
  const text = params.toString();
  return text ? `#${text}` : "";
}

/** Like `useState` for the tab: starts on the one the address names, else on `initial`; the first tab leaves the address clean. */
export function useUrlTab<T extends string>(
  tabs: readonly T[],
  initial: T,
  param = "tab",
): [T, (tab: T) => void] {
  const [tab, setTab] = useState<T>(
    () => (tabFromHash(window.location.hash, tabs, param) as T | null) ?? initial,
  );
  // A link that changes the hash while the page is open (an anchor, an edited address) moves the tab too. Choosing a tab
  // replaces the entry without a hashchange, so the two never chase each other.
  useEffect(() => {
    const onHash = () =>
      setTab((tabFromHash(window.location.hash, tabs, param) as T | null) ?? initial);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [tabs, initial, param]);
  const choose = useCallback(
    (next: T) => {
      setTab(next);
      const hash = hashWithTab(window.location.hash, param, next === initial ? null : next);
      const { pathname, search } = window.location;
      window.history.replaceState(window.history.state, "", `${pathname}${search}${hash}`);
    },
    [initial, param],
  );
  return [tab, choose];
}
