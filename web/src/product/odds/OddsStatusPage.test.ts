import { describe, expect, test } from "bun:test";
import type { OddsStatus } from "@/lib/api/v1/types_odds_explorer";
import { totals } from "./OddsStatusPage";

const status: OddsStatus = {
  last_read_at: "2026-11-12T12:00:00Z",
  by_horizon: [
    { horizon: "0-6h", fixtures: 4, with_price: 3, stale: 1 },
    { horizon: "6-24h", fixtures: 10, with_price: 9, stale: 0 },
    { horizon: "24-72h", fixtures: 20, with_price: 12, stale: 2 },
  ],
  without_price: [],
  without_price_total: 2,
  schedule_minutes: [1440, 360, 60],
  tolerance_minutes: 20,
};

describe("«Estado de los precios»", () => {
  test("the figures on top are the sums of the horizons the API answered", () => {
    expect(totals(status)).toEqual({ fixtures: 34, priced: 24, late: 3 });
  });
  test("no horizon, no figure", () => {
    expect(totals({ ...status, by_horizon: [] })).toEqual({ fixtures: 0, priced: 0, late: 0 });
  });
});
