/**
 * The screens the 2026 redesign («Noche de partido», plan maestro UX/UI 2026, wave 0) measures before it changes
 * anything, and again after every wave: the reader's destinations, the pages before the product and the Admin
 * Console's menu. One list for the three measurements (screens.spec.ts, a11y.spec.ts, perf.spec.ts), so the pictures,
 * the axe results and the web vitals are always of the same pages.
 */
import type { Page } from "@playwright/test";
import { settle } from "./support";

/** A reader's destinations: the bottom bar, «Más» and what they lead to. */
export const READER_PAGES = [
  "/home",
  "/matches",
  "/live",
  "/picks",
  "/my-picks",
  "/parlays",
  "/odds",
  "/odds/status",
  "/profile",
  "/transparency",
  "/updates",
  "/help",
  "/help/glossary",
  "/help/how-it-works",
] as const;

/** The pages before the product: no session. */
export const PUBLIC_PAGES = [
  "/login",
  "/register",
  "/forgot-password",
  "/legal/terms",
  "/legal/privacy",
  "/legal/responsible-gaming",
] as const;

/** The Admin Console's 28 destinations, in the menu's order (components/layout/nav.ts). */
export const CONSOLE_PAGES = [
  "/admin/overview",
  "/admin/picks",
  "/admin/performance",
  "/admin/odds",
  "/admin/customers",
  "/admin/support",
  "/admin/models",
  "/admin/backtesting",
  "/admin/analytics",
  "/admin/operation",
  "/admin/learning",
  "/admin/competitions",
  "/admin/teams",
  "/admin/players",
  "/admin/referees",
  "/admin/rankings",
  "/admin/data-truth",
  "/admin/data-quality",
  "/admin/system",
  "/admin/storage",
  "/admin/migration",
  "/admin/users",
  "/admin/messages",
  "/admin/announcements",
  "/admin/payments",
  "/admin/product",
  "/admin/audit",
  "/admin/settings",
] as const;

/** The sections of a match a reader always has (product/match/useMatchTab.ts reads them from the hash). */
export const MATCH_TABS = [
  "resumen",
  "analisis",
  "estadisticas",
  "mercados",
  "alineaciones",
  "noticias",
] as const;

export const PHONE_WIDTHS = [320, 360, 390, 412, 430] as const;
export const TABLET_WIDTHS = [768, 820, 1024] as const;
export const DESK_WIDTHS = [1280, 1440] as const;

/** The height a screen of that width usually has: a small phone, a phone, a tablet upright, a laptop. */
export function heightFor(width: number): number {
  if (width < 360) return 568;
  if (width < 600) return 844;
  if (width < 1024) return 1180;
  if (width < 1280) return 768;
  return 900;
}

/** A file name for a path: /help/how-it-works -> help_how_it_works. */
export function slugOf(path: string): string {
  return path.replace(/\W+/g, "_").replace(/^_|_$/g, "") || "root";
}

/** The first match of Partidos, without its query: the match the measurements open. Null on a day without matches. */
export async function firstMatchPath(page: Page): Promise<string | null> {
  await page.goto("/matches");
  await settle(page);
  const href = await page.locator('a[href^="/matches/"]').first().getAttribute("href");
  return href ? (href.split(/[?#]/)[0] ?? href) : null;
}
