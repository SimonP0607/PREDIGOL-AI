/**
 * The open section lives in the URL hash (#stats, #markets...), so it survives a reload or a shared link. A link may also
 * name it in the query, in either language (plan UX, A9; section 25: `?s=noticias`, `?s=estadisticas`, `?s=stats`); the old
 * `#picks` opens the Resumen, where the picks of the match now live.
 *
 * Without either, the section to open depends on the match's state: Resumen before kick-off, Estadísticas while it is played,
 * Postpartido once it is over.
 */
import { useCallback, useState } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { TAB_KEYS, type TabKey } from "./context";
import type { Phase } from "./model";

function isTab(value: string): value is TabKey {
  return (TAB_KEYS as readonly string[]).includes(value);
}

/** What a link may call a section, in Spanish or English (accents optional); `picks` is where they were before A9. */
const ALIASES: Readonly<Record<string, TabKey>> = {
  resumen: "summary",
  summary: "summary",
  picks: "summary",
  analisis: "analysis",
  analysis: "analysis",
  estadisticas: "stats",
  stats: "stats",
  mercados: "markets",
  markets: "markets",
  alineaciones: "lineups",
  lineups: "lineups",
  postpartido: "postmatch",
  postmatch: "postmatch",
};

export function tabFromLink(value: string | null | undefined): TabKey | null {
  if (!value) return null;
  const key = value.trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  return ALIASES[key] ?? null;
}

/** The section a match opens on when the link names none (plan section 25). */
export function initialTab(phase: Phase | null): TabKey {
  if (phase === "live") return "stats";
  if (phase === "finished") return "postmatch";
  return "summary";
}

export function useMatchTab(
  fixtureId: string,
  available: readonly TabKey[],
  phase: Phase | null,
): [TabKey, (tab: TabKey) => void] {
  const hash = useRouterState({ select: (s) => s.location.hash });
  const searchStr = useRouterState({ select: (s) => s.location.searchStr });
  const navigate = useNavigate();
  const fromLink = isTab(hash)
    ? hash
    : (tabFromLink(hash) ?? tabFromLink(new URLSearchParams(searchStr).get("s")));
  // The state the match had when the page learnt it decides, once: a match that kicks off while its Resumen is open does not
  // move the reader to Estadísticas (the documented way of keeping a value from an earlier render).
  const [opened, setOpened] = useState<{ id: string; tab: TabKey } | null>(
    phase === null ? null : { id: fixtureId, tab: initialTab(phase) },
  );
  if (phase !== null && (opened === null || opened.id !== fixtureId)) {
    setOpened({ id: fixtureId, tab: initialTab(phase) });
  }
  const fallback: TabKey = opened?.id === fixtureId ? opened.tab : "summary";
  const requested: TabKey = fromLink ?? fallback;
  const active: TabKey = available.includes(requested)
    ? requested
    : available.includes(fallback)
      ? fallback
      : "summary";

  const select = useCallback(
    (tab: TabKey) => {
      void navigate({
        to: "/matches/$fixtureId",
        params: { fixtureId },
        // The section a reader chose is written down, even the one the match opens on: a match that starts while it is
        // open must not move the reader to another section.
        hash: tab,
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

const BASE_TABS: readonly TabKey[] = ["summary", "analysis", "stats", "markets", "lineups"];

/** The sections of a match: Postpartido once it is over (or waiting for its result); the owner's research view last. */
export function tabsFor(phase: Phase | null, admin: boolean): TabKey[] {
  const tabs: TabKey[] = [...BASE_TABS];
  if (phase === "finished" || phase === "awaiting") tabs.push("postmatch");
  if (admin) tabs.push("advanced");
  return tabs;
}
