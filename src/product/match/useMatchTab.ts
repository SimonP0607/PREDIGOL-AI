/** The open tab lives in the URL hash (#stats, #markets...), so it survives a reload or a shared link. */
import { useCallback } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { TAB_KEYS, type TabKey } from "./context";

function isTab(value: string): value is TabKey {
  return (TAB_KEYS as readonly string[]).includes(value);
}

export function useMatchTab(
  fixtureId: string,
  available: readonly TabKey[],
): [TabKey, (tab: TabKey) => void] {
  const hash = useRouterState({ select: (s) => s.location.hash });
  const navigate = useNavigate();
  const requested: TabKey = isTab(hash) ? hash : "summary";
  const active: TabKey = available.includes(requested) ? requested : "summary";

  const select = useCallback(
    (tab: TabKey) => {
      void navigate({
        to: "/matches/$fixtureId",
        params: { fixtureId },
        hash: tab === "summary" ? "" : tab,
        replace: true,
        resetScroll: false,
        hashScrollIntoView: false,
      });
      // Switching from deep in a long tab: bring the new one's top under the sticky bar.
      requestAnimationFrame(() => {
        const anchor = document.getElementById("match-tabs-anchor");
        if (!anchor) return;
        const top = anchor.getBoundingClientRect().top + window.scrollY - 56;
        if (window.scrollY > top + 1) window.scrollTo({ top, behavior: "smooth" });
      });
    },
    [navigate, fixtureId],
  );

  return [active, select];
}
