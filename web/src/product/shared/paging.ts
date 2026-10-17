/**
 * Pages of 15 (REVIEW PREDIGOL, points 13 and 14: thousands of cards made pages too long). The page resets to
 * the first when the list it pages changes (a filter, a new window), and never points past the last.
 */
import { useEffect, useState } from "react";

export const PAGE_SIZE = 15;

export interface Paged<T> {
  items: T[];
  page: number;
  pages: number;
  total: number;
  from: number;
  to: number;
  setPage: (page: number) => void;
}

/** Pure: the slice of a page (1-based), clamped to the pages there are. */
export function pageSlice<T>(all: readonly T[], page: number, size = PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(all.length / size));
  const p = Math.min(Math.max(1, page), pages);
  const start = (p - 1) * size;
  const items = all.slice(start, start + size);
  return {
    items,
    page: p,
    pages,
    total: all.length,
    from: all.length ? start + 1 : 0,
    to: start + items.length,
  };
}

/** `resetKey`: whatever identifies the list (filters, window) - when it changes, back to page 1. */
export function usePaged<T>(all: readonly T[], resetKey: string, size = PAGE_SIZE): Paged<T> {
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [resetKey]);
  return { ...pageSlice(all, page, size), setPage };
}
