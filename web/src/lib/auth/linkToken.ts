/**
 * The token of a one-use link (plan UX, A7): the e-mail's link carries it in the address's fragment (`#t=...`), the
 * part a browser never sends to a server - so it is in no access log, no referrer and no URL the API sees. The page
 * reads it once and takes it out of the address at once (it is not left in the history either); the API gets it in
 * the body of a request.
 */

const TOKEN = /(?:^#|&)t=([A-Za-z0-9_-]{20,128})(?:&|$)/;

let kept: { path: string; token: string } | null = null;

/**
 * The link's token for this page, or null. Pure apart from remembering it for the page: a second render (React
 * renders twice in development) finds it after the address was cleaned.
 */
export function readLinkToken(
  loc: Pick<Location, "hash" | "pathname"> | undefined = typeof window === "undefined"
    ? undefined
    : window.location,
): string | null {
  if (!loc) return null; // rendered on the server: no address to read
  const found = TOKEN.exec(loc.hash);
  if (found?.[1]) {
    kept = { path: loc.pathname, token: found[1] };
    return found[1];
  }
  return kept && kept.path === loc.pathname ? kept.token : null;
}

/** The address without its fragment, in place (no new entry in the history). */
export function forgetLinkFromAddress(win: Pick<Window, "location" | "history"> = window): void {
  if (!win.location.hash) return;
  win.history.replaceState(win.history.state, "", `${win.location.pathname}${win.location.search}`);
}

/** Tests: forget the remembered token. */
export function resetLinkToken(): void {
  kept = null;
}
