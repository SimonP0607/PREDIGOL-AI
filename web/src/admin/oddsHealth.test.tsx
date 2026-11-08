/// <reference types="bun" />
/**
 * «Salud de cuotas» (plan Cuotas, section 6.6): the plan's acceptance criteria as tones - the quota over 45 % of our daily
 * budget, the last six hours' prices older than 70 minutes, the extractor behind, `odds_quotes` near its brake - and the
 * panel as the owner reads it.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { OddsHealth } from "@/lib/api/v1/types_odds_explorer";
import { setLocale } from "@/lib/i18n";
import { OddsHealthView } from "./OddsHealthTab";
import { ageText, brakeTone, horizonAgeTone, lagTone, quotaTone } from "./oddsHealth";

setLocale("es");
afterAll(() => setLocale("es"));

const HEALTH: OddsHealth = {
  by_horizon: [
    { horizon: "0-6h", fixtures: 14, with_book: 14, median_age_min: 52, stale: 0 },
    { horizon: "6-24h", fixtures: 61, with_book: 60, median_age_min: 140, stale: 2 },
    { horizon: "24-72h", fixtures: 0, with_book: 0, median_age_min: null, stale: 0 },
  ],
  extraction_lag_min: 0,
  book_rows: 9312,
  book_mb: 71.4,
  quota_today: 18240,
  quota_limit: 75000,
  provider_requests_remaining: 56110,
  default_partition_rows: 0,
  odds_quotes_gb: 6.2,
  odds_quotes_brake_gb: 25,
};

describe("the judgements", () => {
  test("the quota: fine under 45 % of our budget, a look above it, red from 90 %", () => {
    expect(quotaTone(18240, 75000)).toBe("default");
    expect(quotaTone(36000, 75000)).toBe("warning");
    expect(quotaTone(70000, 75000)).toBe("negative");
    expect(quotaTone(10, 0)).toBe("muted");
  });

  test("the extractor's lag, the brake and the last six hours' age", () => {
    expect([lagTone(null), lagTone(0), lagTone(90), lagTone(240)]).toEqual([
      "muted",
      "default",
      "warning",
      "negative",
    ]);
    expect([brakeTone(6, 25), brakeTone(21, 25), brakeTone(25, 25), brakeTone(1, 0)]).toEqual([
      "default",
      "warning",
      "negative",
      "muted",
    ]);
    expect(horizonAgeTone("0-6h", 70)).toBe("positive");
    expect(horizonAgeTone("0-6h", 71)).toBe("warning");
    // only the last six hours have a target
    expect(horizonAgeTone("6-24h", 500)).toBe("default");
    expect(horizonAgeTone("0-6h", null)).toBe("default");
  });

  test("an age in words", () => {
    expect([ageText(45), ageText(120), ageText(200), ageText(1600)]).toEqual([
      "45 min",
      "2 h",
      "3 h 20 min",
      "26 h",
    ]);
  });
});

describe("the panel", () => {
  test("what the owner reads", () => {
    const html = renderToStaticMarkup(<OddsHealthView h={HEALTH} />);
    expect(html).toContain('data-testid="odds-health"');
    expect(html).toContain(">18.240<");
    expect(html).toMatch(/24\s%\sde nuestro tope diario de 75\.000/);
    expect(html).toContain("quedan 56.110");
    expect(html).toContain("Al día");
    // four digits without a separator, as Spanish writes them
    expect(html).toContain("9312 filas");
    expect(html).toContain("71,4 MB");
    expect(html).toContain("6,2 / 25 GB");
    expect(html).toContain("0 a 6 h");
    expect(html).toContain("52 min");
    expect(html).toContain("2 h 20 min");
    expect(html).toContain("Ninguno");
    expect(html).toContain("2 partidos");
    expect(html).toContain("Ninguna fila en las particiones DEFAULT");
  });

  test("the provider silent today, the extractor behind, rows in a DEFAULT partition", () => {
    const html = renderToStaticMarkup(
      <OddsHealthView
        h={{
          ...HEALTH,
          provider_requests_remaining: null,
          extraction_lag_min: 95,
          default_partition_rows: 3,
        }}
      />,
    );
    expect(html).toContain("El proveedor aún no ha dicho hoy cuántas quedan.");
    expect(html).toContain("1 h 35 min");
    expect(html).toContain(
      '<p class="text-sm text-negative" data-testid="odds-health-partitions">',
    );
    expect(html).toContain("3 filas en las particiones DEFAULT");
  });
});
