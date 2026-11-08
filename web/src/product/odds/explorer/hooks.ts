/**
 * The explorer's small pieces of state: which prices moved since the last update, the last market of each tab, the
 * competitions and bookmakers the loaded pages named, and what a screen reader was last told.
 */
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { SlipLeg } from "@/product/records/model";
import { SlipContext } from "@/product/records/slipContext";
import { slipAnnouncement } from "./legs";
import type { CompetitionBadge, OddsBoardPage, OddsBoardRow } from "./model";
import { priceMap, priceMoves, type Move } from "./rows";
import { readMemory, rememberMarket, type MarketMemory, type TabKey } from "./tabs";

export interface PriceMoves {
  /** The prices that changed in the last update: their arrow stays until the next one. */
  moves: ReadonlyMap<string, Move>;
  /** Grows with every update that moved something: it replays the one tint. */
  version: number;
}

const NO_MOVES: PriceMoves = { moves: new Map(), version: 0 };

/**
 * Which prices moved between two updates of the SAME board (market, period, line, filters: `board`). Another board starts
 * afresh: a draw-no-bet «Home» is not the 1X2 «Home» it replaced.
 */
export function usePriceMoves(
  rows: readonly OddsBoardRow[],
  board: string,
  updatedAt: number,
): PriceMoves {
  const held = useRef<{ board: string; at: number; prices: Map<string, number> } | null>(null);
  const [state, setState] = useState<PriceMoves>(NO_MOVES);
  useEffect(() => {
    const prices = priceMap(rows);
    const before = held.current;
    if (before && before.board === board && updatedAt <= before.at) return;
    held.current = { board, at: updatedAt, prices };
    if (!before || before.board !== board) {
      setState((s) => (s.moves.size ? { moves: new Map(), version: s.version } : s));
      return;
    }
    const moves = priceMoves(before.prices, prices);
    setState((s) =>
      moves.size ? { moves, version: s.version + 1 } : s.moves.size ? { ...s, moves } : s,
    );
  }, [rows, board, updatedAt]);
  return state;
}

const MEMORY_KEY = "predigol.explorer.markets";

/** The last market used in each tab, remembered in this browser; without storage it is only this visit's. */
export function useMarketMemory(): [MarketMemory, (tab: TabKey, market: string) => void] {
  const [memory, setMemory] = useState<MarketMemory>({});
  // Written only after a choice of the reader's: never the empty memory of the first render over the stored one.
  const chosen = useRef(false);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(MEMORY_KEY);
      // a choice made before this read wins over the stored one
      if (raw) setMemory((m) => ({ ...readMemory(JSON.parse(raw)), ...m }));
    } catch {
      /* storage unavailable or unreadable: start empty */
    }
  }, []);
  useEffect(() => {
    if (!chosen.current) return;
    try {
      window.localStorage.setItem(MEMORY_KEY, JSON.stringify(memory));
    } catch {
      /* storage unavailable: kept for this visit only */
    }
  }, [memory]);
  const remember = useCallback((tab: TabKey, market: string) => {
    chosen.current = true;
    setMemory((m) => rememberMarket(m, tab, market));
  }, []);
  return [memory, remember];
}

export interface Seen {
  competitions: ReadonlyMap<number, CompetitionBadge>;
  bookmakers: ReadonlyMap<number, string>;
}

/**
 * Every competition and bookmaker the loaded pages named while the explorer is open: the dictionaries of the rows, and the
 * options of the filters (a country picked keeps the others on offer).
 */
export function useSeen(pages: readonly OddsBoardPage[] | undefined): Seen {
  const competitions = useRef(new Map<number, CompetitionBadge>());
  const bookmakers = useRef(new Map<number, string>());
  return useMemo(() => {
    for (const page of pages ?? []) {
      for (const c of page.competitions) competitions.current.set(c.id, c);
      for (const b of page.bookmakers) bookmakers.current.set(b.id, b.name);
    }
    return {
      competitions: new Map(competitions.current),
      bookmakers: new Map(bookmakers.current),
    };
  }, [pages]);
}

/** What a screen reader is told (aria-live): the same words twice are said twice. */
export function useAnnouncer(): [string, (message: string) => void] {
  const [said, setSaid] = useState({ text: "", n: 0 });
  const announce = useCallback(
    (text: string) => setSaid((s) => ({ text: s.n % 2 ? text : `${text}\u200b`, n: s.n + 1 })),
    [],
  );
  return [said.text, announce];
}

const NO_LEGS: readonly SlipLeg[] = [];

/**
 * Every leg in or out of the slip said through `announce` (the explorer's live region), with the leg's words and the new
 * count. The way back to the slip is the product's own button (records/SlipSheet), the same on every screen: a bar of the
 * explorer's own on a phone would be a second «Mi parlay · N» over the first.
 */
export function useSlipAnnouncer(announce: (message: string) => void): void {
  const slip = useContext(SlipContext);
  const legs = slip?.legs ?? NO_LEGS;
  const before = useRef(legs);
  useEffect(() => {
    const message = slipAnnouncement(before.current, legs);
    before.current = legs;
    if (message) announce(message);
  }, [legs, announce]);
}
