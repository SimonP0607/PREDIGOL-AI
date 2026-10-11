/// <reference types="bun" />
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { SelectionQuotes } from "@/lib/api/v1/types_profile";
import { bookRows, captureLabel, openingNote } from "./books";

const book = (bookmaker: string, odds: string, opening: string) => ({
  bookmaker_id: bookmaker.length,
  bookmaker,
  odds,
  captured_at: "2026-10-10T08:00:00Z",
  opening_odds: opening,
  opening_at: "2026-10-07T16:00:00Z",
  captures: 3,
});

const sels: SelectionQuotes[] = [
  {
    market_key: "1X2",
    selection: "Home",
    line: "0.00",
    books: [book("Bet365", "1.95", "2.10"), book("1xBet", "2.05", "2.05")],
  },
  { market_key: "1X2", selection: "Away", line: "0.00", books: [book("Bet365", "4.00", "3.80")] },
  { market_key: "AH", selection: "Home", line: "-1.50", books: [book("Pinnacle", "2.66", "2.70")] },
  { market_key: "AH", selection: "Away", line: "1.50", books: [book("Pinnacle", "1.50", "1.48")] },
];

describe("every bookmaker's price (REVIEW point 10)", () => {
  afterAll(() => setLocale("es"));

  test("one row per bookmaker, the best price of each selection marked", () => {
    const rows = bookRows("1X2", sels, 0);
    expect(rows.map((r) => r.bookmaker)).toEqual(["1xBet", "Bet365"]);
    const bet365 = rows.find((r) => r.bookmaker === "Bet365");
    expect(bet365?.cells.map((c) => c?.odds ?? null)).toEqual(["1.95", null, "4.00"]);
    expect(rows.find((r) => r.bookmaker === "1xBet")?.cells[0]?.best).toBe(true);
    expect(bet365?.cells[0]?.best).toBe(false);
  });

  test("a handicap row pairs the home line with the away side's opposite line", () => {
    const rows = bookRows("AH", sels, -1.5);
    expect(rows[0]?.cells.map((c) => c?.odds ?? null)).toEqual(["2.66", "1.50"]);
  });

  test("where the best price opened, only when it moved", () => {
    setLocale("es");
    expect(openingNote(sels.slice(0, 2), "Home", 0, "2.05")).toBe("abrió 2,10");
    expect(openingNote(sels.slice(0, 2), "Away", 0, "4.00")).toBe("abrió 3,80");
    expect(openingNote(sels.slice(0, 1), "Home", 0, "2.10")).toBeNull();
  });

  test("captures are labelled by their distance to kick-off", () => {
    expect(captureLabel(4316)).toBe("T-72 h");
    expect(captureLabel(179)).toBe("T-3 h");
    expect(captureLabel(25)).toBe("T-25 min");
  });
});
