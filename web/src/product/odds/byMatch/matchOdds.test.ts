/// <reference types="bun" />
/** One match's markets and movement (UX-142, sheets C03 and C04): the book's order and the movement's four figures. */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { MatchOddsBook, OddsBookMarket } from "@/lib/api/v1/types_odds_explorer";
import { bookView, moveFacts } from "./MatchOdds";

setLocale("es");

const market = (key: string, family: string, period = "FT") =>
  ({
    info: { key, family, kind: "plain", subject: "match" },
    period,
    main_line: null,
    lines: [],
  }) as unknown as OddsBookMarket;

describe("a match's prices", () => {
  test("the three lead markets first, in the board's order, full time only; the rest by family", () => {
    const book = {
      families: [
        { key: "corners", markets: [market("corners.total", "corners")] },
        {
          key: "goals",
          markets: [
            market("goals.btts", "goals"),
            market("goals.total", "goals"),
            market("goals.total", "goals", "1H"),
          ],
        },
        { key: "result", markets: [market("result.1x2", "result")] },
      ],
    } as unknown as MatchOddsBook;
    const v = bookView(book);
    expect(v.lead.map((m) => m.info.key)).toEqual(["result.1x2", "goals.total", "goals.btts"]);
    expect(v.others.map((f) => [f.family, f.markets.length])).toEqual([
      ["corners", 1],
      ["goals", 1],
    ]);
    expect(bookView(undefined)).toEqual({ lead: [], others: [] });
  });

  test("opening, highest, lowest and now", () => {
    const p = (odds: number) => ({ t: 0, odds, bookmaker: "x" });
    expect(moveFacts([p(2.2), p(2.24), p(2.02), p(2.05)])).toEqual({
      open: 2.2,
      high: 2.24,
      low: 2.02,
      now: 2.05,
    });
    expect(moveFacts([])).toBeNull();
  });
});
