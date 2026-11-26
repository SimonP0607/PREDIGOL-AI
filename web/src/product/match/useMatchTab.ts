/**
 * The open section lives in the URL hash (#stats, #markets...), so it survives a reload or a shared link. A link may also
 * name it in the query, in either language (plan UX, A9; section 25: `?s=noticias`, `?s=estadisticas`, `?s=stats`); the old
 * `#picks` opens the Resumen, where the picks of the match now live.
 *
 * Without either, the section to open depends on the match's state: Resumen before kick-off and once it is over,
 * Estadísticas while it is played.
 *
 * Always six tabs (plan maestro UX/UI 2026, decision 11): Postpartido is no longer one - once the match is over it opens
 * on top of the Resumen, and `#postmatch`, `?s=postpartido` and every old link to it open the Resumen there - and the
 * owner's Avanzado is a button of the page (`#advanced` still opens it, for the owner alone).
 */
import { useCallback, useState } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { TAB_KEYS, type TabKey } from "./context";
import type { MatchAvailability } from "@/lib/api/v1/types_availability";
import { present } from "@/lib/api/v1/types_intelligence";
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
  noticias: "news",
  news: "news",
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
  return "summary";
}

/** The tab that shows a section: the Postpartido lives in the Resumen (decision 11). */
export function tabOf(section: TabKey): TabKey {
  return section === "postmatch" ? "summary" : section;
}

export function useMatchTab(
  fixtureId: string,
  available: readonly TabKey[],
  phase: Phase | null,
): [TabKey, (tab: TabKey) => void] {
  const hash = useRouterState({ select: (s) => s.location.hash });
  const searchStr = useRouterState({ select: (s) => s.location.searchStr });
  const navigate = useNavigate();
  const named = isTab(hash)
    ? hash
    : (tabFromLink(hash) ?? tabFromLink(new URLSearchParams(searchStr).get("s")));
  const fromLink = named ? tabOf(named) : null;
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
      // Switching from deep in a long tab: bring the new one's top under the sticky bar (the Postpartido is the top of
      // the Resumen, so the same place).
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

const BASE_TABS: readonly TabKey[] = ["summary", "analysis", "stats", "markets", "lineups", "news"];

/** The tabs of a match: always these six (decision 11), whatever its state and whoever reads it. */
export function tabsFor(noPrices = false): TabKey[] {
  return noPrices ? BASE_TABS.filter((tab) => !PRICE_TABS.includes(tab)) : [...BASE_TABS];
}

/**
 * The tabs that ARE a price or a pick (plan PM, PM-14-07): Mercados (every price of the match) and Análisis (the value of the
 * selections against them). A reader in «solo fútbol» or a pause does not get them; the rest of the match is football.
 */
export const PRICE_TABS: readonly TabKey[] = ["markets", "analysis"];

/** What the page may show: the tabs (the six, or the ones the coverage leaves) and, for the owner, the research view behind its button. */
export function sectionsFor(admin: boolean, tabs: readonly TabKey[] = BASE_TABS): TabKey[] {
  return admin ? [...tabs, "advanced"] : [...tabs];
}

/**
 * The tabs of a match read from C-16 (plan PM, PM-14-02, láminas I01 and I04; UX-177), only with `FBI_MATCH_COVERAGE` on: the same
 * six in the same order, less the ones that would open on nothing in this competition - never one that has something to show.
 *  - Alineaciones: gone when C-16 grades the line-ups D (the competition does not deliver them; C still shows the line-up alone).
 *  - Mercados: gone when no market exists for the match in C-16 and the page holds no price for it either.
 *  - Análisis: gone when PrediGol computed no probability for the match result and C-16 grades that market C or D (lámina I04:
 *    «sin probabilidad de PrediGol» in C and D); a market C-16 does not list leaves it.
 * Resumen, Estadísticas and Noticias always stay: the result, the events and the table are in every level.
 * Without C-16 (off, or not answered) the six, as always.
 */
export function tabsForCoverage(
  availability: Pick<MatchAvailability, "blocks" | "markets"> | null,
  opts: { pricesShown: boolean; noPrices?: boolean },
): TabKey[] {
  const noPrices = opts.noPrices === true;
  if (!availability) return tabsFor(noPrices);
  const lineups = availability.blocks.find((b) => b.key === "lineups");
  const lineupsLevel = lineups && lineups.reason !== "sin_medir" ? present(lineups.level) : null;
  const anyMarket = availability.markets.some((m) => m.exists);
  const result = availability.markets.find((m) => m.key === "1X2" || m.matrix_market === "1X2");
  const resultLevel = result ? present(result.level) : null;
  const noReading =
    result !== undefined && !result.prob_computed && (resultLevel === "C" || resultLevel === "D");
  return BASE_TABS.filter((tab) => {
    if (noPrices && PRICE_TABS.includes(tab)) return false;
    if (tab === "lineups") return lineupsLevel !== "D";
    if (tab === "markets") return anyMarket || opts.pricesShown;
    if (tab === "analysis") return !noReading;
    return true;
  });
}
