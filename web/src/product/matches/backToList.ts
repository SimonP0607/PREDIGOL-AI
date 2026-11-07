/**
 * «‹ Partidos» goes back when the match was opened from the list (plan Partidos, P4): the list comes back as it was -
 * its filters (in its URL), its folded competitions and its scroll - instead of opening again at the top.
 *
 * The list writes down, as a row is opened, which match and which entry of the tab's history it is on (the router's
 * own index, which a replace - the Match Center's tabs - keeps). The match page goes back only when it is that match,
 * one entry after the list's; anything else (a shared link, a match opened from Inicio, a second match opened from the
 * first) links to /matches as before.
 */

const KEY = "predigol.matches.opened";

/** The router's index of the current entry of this tab's history (0 when it cannot tell). */
export function historyIndex(): number {
  try {
    const state: unknown = window.history.state;
    const index =
      state && typeof state === "object" ? (state as Record<string, unknown>)["__TSR_index"] : 0;
    return typeof index === "number" && Number.isSafeInteger(index) ? index : 0;
  } catch {
    return 0;
  }
}

export function rememberOpened(fixtureId: number, listIndex: number = historyIndex()): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ fixture: fixtureId, index: listIndex }));
  } catch {
    /* storage unavailable: «‹ Partidos» links to the list */
  }
}

/** Whether the entry before this one is the list this match was opened from. */
export function openedFromList(fixtureId: number, index: number = historyIndex()): boolean {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return false;
    const saved = JSON.parse(raw) as { fixture?: unknown; index?: unknown };
    return (
      saved.fixture === fixtureId && typeof saved.index === "number" && saved.index + 1 === index
    );
  } catch {
    return false;
  }
}
