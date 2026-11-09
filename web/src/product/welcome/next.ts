/** Where the reader goes after the welcome (plan UX, A13): the page they asked for (a link they opened), else Inicio. */
export function afterWelcome(searchStr: string | undefined): string {
  const next = new URLSearchParams(searchStr ?? "").get("next");
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/welcome")
    ? next
    : "/home";
}

/**
 * Where the welcome page sends the reader once it has finished (UX-081, Sentry PREDIGOL-WEB-8): only when the cached account
 * - the one the gate reads in the same render - no longer says the welcome is owed. Navigating at the API's answer, a moment
 * before the cache caught up, made the gate send the reader back to /welcome for an instant (three navigations in a hundred
 * milliseconds). ``null`` = not yet (still owed, or nothing to leave for).
 */
export function welcomeExit(owed: boolean, leaving: string | null): string | null {
  return owed ? null : leaving;
}
