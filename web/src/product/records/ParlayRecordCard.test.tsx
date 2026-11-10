/// <reference types="bun" />
/**
 * The compact parlay card of Inicio, one row per leg (UX-100). While a leg's match is in play its row carries a chip
 * («En juego · 4' · 0–0») that is wider than what a phone leaves next to the leg's text: in a row that could not wrap it
 * squeezed the text to a few letters per line and a leg grew to ~450-590 px. The row now wraps - the price and the state go
 * under the text, to the right, when they do not fit - and a leg without a chip keeps its row as it was.
 * Without a browser the layout is pinned by its classes; the widths were measured in a browser (see the PR).
 */
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import { setTimeZone } from "@/lib/time";
import type { MatchRef, ParlayRecord, ParlayRecordLeg } from "@/lib/api/v1/types_records";
import { ParlayRecordCard } from "./ParlayRecordCard";

setLocale("es");
beforeEach(() => setTimeZone("America/Bogota"));
afterEach(() => setTimeZone("UTC"));

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function text(markup: string): string {
  return markup
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/[\u00a0\u202f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

const MINUTE = 60_000;
let next = 700;

function match(over: Partial<MatchRef>): MatchRef {
  return {
    fixture_id: next++,
    kickoff_at: new Date(Date.now() + 3 * 60 * MINUTE).toISOString(),
    status_group: "scheduled",
    status_short: "NS",
    phase: "scheduled",
    competition: {
      id: 1,
      name: "Liga BetPlay",
      country: "Colombia",
      logo_url: null,
      flag_url: null,
    },
    home: { id: 1, name: "Nacional", logo_url: null },
    away: { id: 2, name: "Millonarios", logo_url: null },
    score_home: null,
    score_away: null,
    ...over,
  };
}

function leg(n: number, status: ParlayRecordLeg["status"], m: MatchRef): ParlayRecordLeg {
  return {
    leg_no: n,
    pick_id: 5000 + n,
    match: m,
    market_key: "OU",
    selection: "Over",
    line: "2.5",
    odds: "1.85",
    bookmaker: null,
    p_model: "0.6100",
    p_low: "0.5600",
    p_market: "0.5300",
    ev: "0.1200",
    status,
    why: null,
  };
}

function parlay(legs: ParlayRecordLeg[]): ParlayRecord {
  return {
    id: 1,
    kind: "daily",
    day: "2026-11-10",
    source: "qualified",
    rule_version: "parlay-v1",
    status: "ACTIVE",
    min_legs: 2,
    max_legs: 4,
    window_from: new Date(Date.now() - 60 * MINUTE).toISOString(),
    window_to: new Date(Date.now() + 6 * 60 * MINUTE).toISOString(),
    combined_odds: "5.20",
    p_all_low: "0.1800",
    expected_log_growth: null,
    ready_at: null,
    settled_at: null,
    profit_units: null,
    legs,
  };
}

const LIVE = (): MatchRef =>
  match({
    kickoff_at: new Date(Date.now() - 4 * MINUTE).toISOString(),
    status_group: "live",
    status_short: "1H",
    phase: "live",
    live_minute: 4,
    live_home: 0,
    live_away: 0,
  });

const SETTLING = (): MatchRef =>
  match({
    kickoff_at: new Date(Date.now() - 115 * MINUTE).toISOString(),
    status_group: "finished",
    status_short: "FT",
    phase: "finished",
    score_home: 1,
    score_away: 0,
  });

async function render(legs: ParlayRecordLeg[]): Promise<string[]> {
  const out = await html(<ParlayRecordCard kind="daily" parlay={parlay(legs)} variant="compact" />);
  return out.match(/<li\b[^>]*data-testid="parlay-leg"[\s\S]*?<\/li>/g) ?? [];
}

function tag(markup: string, testid: string): string {
  const found = markup.match(new RegExp(`<[a-z]+\\b[^>]*${testid}[^>]*>`));
  if (!found) throw new Error(`no ${testid} in the leg`);
  return found[0];
}

describe("compact parlay legs, UX-100", () => {
  test("a leg in play says so with its minute and score, and its row can wrap", async () => {
    const [row] = await render([leg(1, "PENDING", LIVE()), leg(2, "PENDING", match({}))]);
    expect(row).toBeDefined();
    expect(text(row!)).toContain("En juego · 4' · 0–0");
    // The row wraps; the text is given a basis so that it, not the chip, is what ends up on the first line.
    expect(row!.match(/<li\b[^>]*>/)![0]).toContain("flex-wrap");
    expect(row!.match(/<a\b[^>]*>/)![0]).toContain("basis-48");
  });

  test("the price and the state sit in a column that goes to the right of the row", async () => {
    const [row] = await render([leg(1, "PENDING", LIVE()), leg(2, "PENDING", match({}))]);
    const column = row!.match(/<div class="[^"]*ml-auto[^"]*"/)?.[0] ?? "";
    expect(column).toContain("shrink-0");
    expect(column).toContain("flex-col");
    expect(tag(row!, "match-state")).toContain('data-phase="live"');
  });

  test("a finished leg that is still settling and a settled one use the same row", async () => {
    const rows = await render([
      leg(1, "PENDING", SETTLING()),
      leg(2, "WIN", SETTLING()),
      leg(3, "PENDING", match({})),
    ]);
    expect(rows).toHaveLength(3);
    expect(text(rows[0]!)).toContain("Terminado · liquidando");
    expect(tag(rows[1]!, "result-badge")).toContain('data-status="WIN"');
    for (const row of rows) {
      expect(row.match(/<li\b[^>]*>/)![0]).toContain("flex-wrap");
    }
  });

  test("a leg that has not started shows no chip: only its price", async () => {
    const [row] = await render([leg(1, "PENDING", match({})), leg(2, "PENDING", match({}))]);
    expect(row).not.toContain("match-state");
    expect(row).not.toContain("result-badge");
    expect(row).toContain("selectable-price");
  });
});
