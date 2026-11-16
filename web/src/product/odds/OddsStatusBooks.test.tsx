/// <reference types="bun" />
/** «Por casa» (BE-043, UX-143): a row per bookmaker, its matches and the matches' own reading hour, late ones marked in words. */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { OddsStatus } from "@/lib/api/v1/types_odds_explorer";
import { ByBook } from "./OddsStatusPage";

setLocale("es");

const base: OddsStatus = {
  last_read_at: "2026-11-12T12:00:00Z",
  by_horizon: [],
  without_price: [],
  without_price_total: 0,
  schedule_minutes: [60],
  tolerance_minutes: 20,
  by_book: [
    { id: 8, name: "Casa Uno", matches: 12, stale: 0, last_read_at: "2026-11-12T12:00:00Z" },
    { id: 11, name: "Casa Dos", matches: 9, stale: 2, last_read_at: "2026-11-12T11:00:00Z" },
  ],
};

describe("«Por casa»", () => {
  test("each bookmaker with its matches out of the priced ones, the late ones said in words, and the honest note", () => {
    const html = renderToStaticMarkup(<ByBook data={base} total={14} />);
    expect(html.match(/data-testid="odds-status-book"/g)).toHaveLength(2);
    expect(html).toContain("12 de 14 con precio");
    expect(html).toContain("2 con retraso");
    expect(html).toContain("Las casas no publican su propia hora");
  });
});
