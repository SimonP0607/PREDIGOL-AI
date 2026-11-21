/// <reference types="bun" />
/**
 * Plan PM, PM-10-07 (lámina I09 «M08»; UX-182): the result forecast in 100 icons explains the figure of the bars and computes none.
 * Rounding (the icons are the whole percentages the bars show; when those do not add up to 100, the largest remainders, said on the
 * page), the contract (no icons unless calibrated and authorised: 1X2 with a validated calibrator), the switch (off: the block is as
 * it was) and accessibility (one image with its sentence, shapes as well as colours, the toggle's pressed state).
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { contrast, over, rootTokens } from "@/lib/a11y/contrast";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { fmtPct } from "@/lib/i18n/format";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  ForecastBasis,
  ForecastCalibration,
  ForecastMarket,
  MatchForecast,
} from "@/lib/api/v1/types_forecast";
import { ForecastView } from "@/product/match/ForecastBlock";
import type { ForecastLoad } from "@/product/match/forecast";
import {
  PROB_ICONS_REVIEW,
  iconCells,
  iconCounts,
  iconsAllowed,
  shownPercent,
  sideOf,
} from "./iconArray";
import { reviewProblems } from "@/components/analytics/evidence";
import { MythOrFact, ProbabilityIcons } from "./ProbabilityIcons";

setLocale("es");
afterEach(() => setLocale("es"));

const o = (selection: string, p: number) => ({ selection, probability: p.toFixed(4) });

function result(
  probs: [number, number, number],
  calibration: ForecastCalibration = "CALIBRATED",
  basis: ForecastBasis = "champion",
): ForecastMarket {
  return {
    market: "1X2",
    line: "0.00",
    family: "RESULT",
    model: null,
    calibration,
    basis,
    known_at: "2026-11-21T17:05:00Z",
    data_cutoff_at: "2026-11-21T16:30:00Z",
    outcomes: [
      { ...o("Home", probs[0]), low: "0.4800", high: "0.6300", likely: true },
      { ...o("Draw", probs[1]), low: null, high: null, likely: false },
      { ...o("Away", probs[2]), low: null, high: null, likely: false },
    ],
  };
}

function load(markets: ForecastMarket[]): ForecastLoad {
  const data: MatchForecast = {
    fixture_id: 1,
    kickoff_at: "2026-11-21T23:30:00Z",
    status_group: "NS",
    forecast: { status: "ok", data: markets },
  } as MatchForecast;
  return { status: "success", envelope: { status: "ok", data } as Envelope<MatchForecast | null> };
}

describe("rounding: the icons are the figure the bars show", () => {
  test("lámina I09: 56 / 24 / 20", () => {
    expect(iconCounts([o("Home", 0.56), o("Draw", 0.24), o("Away", 0.2)])).toEqual({
      home: 56,
      draw: 24,
      away: 20,
      adjusted: false,
    });
  });

  test("the whole percentage is the one fmtPct(p, 0) shows, across the whole range", () => {
    for (let i = 0; i <= 2000; i++) {
      const p = i / 2000;
      expect(`${shownPercent(p)}`).toBe(fmtPct(p, 0).replace(/\D/g, ""));
    }
  });

  test("three thirds: 34 / 33 / 33 by the largest remainders, and it says so", () => {
    const c = iconCounts([o("Home", 0.3334), o("Draw", 0.3333), o("Away", 0.3333)]);
    expect(c).toEqual({ home: 34, draw: 33, away: 33, adjusted: true });
  });

  test("rounded up past 100: 101 becomes 100", () => {
    const c = iconCounts([o("Home", 0.445), o("Draw", 0.275), o("Away", 0.28)]);
    expect(c && c.home + c.draw + c.away).toBe(100);
    expect(c?.adjusted).toBe(true);
  });

  test("always 100 icons, each side at most one icon away from its bar", () => {
    for (let h = 1; h < 98; h += 3) {
      for (let d = 1; d < 100 - h; d += 7) {
        const ph = h / 100 + 0.0049;
        const pd = d / 100 + 0.0049;
        const pa = 1 - ph - pd;
        if (pa <= 0) continue;
        const c = iconCounts([o("Home", ph), o("Draw", pd), o("Away", pa)]);
        expect(c).not.toBeNull();
        if (!c) continue;
        expect(c.home + c.draw + c.away).toBe(100);
        expect(Math.abs(c.home - shownPercent(ph))).toBeLessThanOrEqual(1);
        expect(Math.abs(c.draw - shownPercent(pd))).toBeLessThanOrEqual(1);
        expect(iconCells(c)).toHaveLength(100);
      }
    }
  });

  test("the cells come in order: home, then draws, then away", () => {
    const cells = iconCells({ home: 2, draw: 1, away: 97 });
    expect(cells.slice(0, 4)).toEqual(["home", "home", "draw", "away"]);
  });
});

describe("the contract: no icons unless calibrated and authorised", () => {
  test("only the result (1X2), calibrated, with a validated calibrator", () => {
    expect(iconsAllowed(result([0.56, 0.24, 0.2]))).toBe(true);
    expect(iconsAllowed(result([0.56, 0.24, 0.2], "UNCALIBRATED", "no_champion"))).toBe(false);
    expect(iconsAllowed(result([0.56, 0.24, 0.2], "CALIBRATED", "needs_price"))).toBe(false);
    expect(iconsAllowed({ ...result([0.56, 0.24, 0.2]), market: "OU" })).toBe(false);
  });

  test("a side missing or repeated, or a number that is not a probability: no icons", () => {
    expect(iconCounts([o("Home", 0.6), o("Away", 0.4)])).toBeNull();
    expect(iconCounts([o("Home", 0.5), o("Home", 0.3), o("Away", 0.2)])).toBeNull();
    expect(iconCounts([o("Home", 0.5), o("Draw", 0.3), o("Away", 0.5)])).toBeNull();
    expect(
      iconCounts([{ selection: "Home", probability: "x" }, o("Draw", 0.5), o("Away", 0.5)]),
    ).toBeNull();
  });

  test("the API's names and the short ones", () => {
    expect(["Home", "draw", "AWAY", "1", "X", "2", "Over"].map(sideOf)).toEqual([
      "home",
      "draw",
      "away",
      "home",
      "draw",
      "away",
      null,
    ]);
  });
});

describe("the block", () => {
  const view = (markets: ForecastMarket[], icons: boolean) =>
    renderToStaticMarkup(
      <ForecastView
        load={load(markets)}
        home="Atlético Cordillera"
        away="Real Altiplano"
        preview={false}
        icons={icons}
      />,
    );

  test("switch off: no toggle, the bars as they were", () => {
    const out = view([result([0.56, 0.24, 0.2])], false);
    expect(out).not.toContain("forecast-view-toggle");
    expect(out).toContain('data-testid="forecast-outcome"');
  });

  test("switch on, calibrated result: the toggle, bars first (the default view does not change)", () => {
    const out = view([result([0.56, 0.24, 0.2])], true);
    expect(out).toContain('data-testid="forecast-view-toggle"');
    expect(out).toMatch(/aria-pressed="true"[^>]*data-testid="forecast-view-bars"/);
    expect(out).toMatch(/aria-pressed="false"[^>]*data-testid="forecast-view-icons"/);
    expect(out).toContain('data-testid="forecast-outcome"');
  });

  test("switch on, uncalibrated result: no toggle", () => {
    const out = view([result([0.56, 0.24, 0.2], "UNCALIBRATED", "no_champion")], true);
    expect(out).not.toContain("forecast-view-toggle");
  });
});

describe("the icons (lámina I09)", () => {
  const counts = { home: 56, draw: 24, away: 20, adjusted: false };
  const out = renderToStaticMarkup(
    <ProbabilityIcons
      counts={counts}
      home="Atlético Cordillera"
      away="Real Altiplano"
      figure="56 %, entre 48 % y 63 %"
    />,
  );

  test("100 shapes in one image with its sentence", () => {
    const grid = out.slice(out.indexOf('data-testid="prob-icons-grid"'), out.indexOf("</svg>"));
    expect(grid.match(/<circle/g)?.length).toBe(56);
    expect(grid.match(/<rect/g)?.length).toBe(24);
    expect(grid.match(/<polygon/g)?.length).toBe(20);
    expect(out).toContain(
      'role="img" aria-label="De cada 100 partidos como este: 56 los gana Atlético Cordillera, 24 terminan en empate y 20 los gana Real Altiplano."',
    );
  });

  test("the legend, the sentence the other way round and the warning", () => {
    expect(out).toContain("De cada 100 partidos como este…");
    expect(out).toContain("gana Atlético Cordillera");
    expect(out).toContain("terminan en empate");
    expect(out).toContain("Dicho al revés: Atlético Cordillera no gana 44 de cada 100.");
    expect(out).toContain("No es una certeza.");
    expect(out).toContain("Es la misma cifra de las barras (56 %, entre 48 % y 63 %)");
    expect(out).toContain("no añade ningún cálculo");
    expect(out).not.toContain("prob-icons-adjusted");
  });

  test("adjusted counts are said", () => {
    const html = renderToStaticMarkup(
      <ProbabilityIcons
        counts={{ home: 34, draw: 33, away: 33, adjusted: true }}
        home="A"
        away="B"
        figure="33 %"
      />,
    );
    expect(html).toContain('data-testid="prob-icons-adjusted"');
  });

  test("in English", () => {
    setLocale("en");
    const html = renderToStaticMarkup(
      <ProbabilityIcons
        counts={counts}
        home="Atlético Cordillera"
        away="Real Altiplano"
        figure="56 %, entre 48 % y 63 %"
      />,
    );
    expect(html).toContain("Out of every 100 matches like this one…");
    expect(html).toContain("Put the other way: Atlético Cordillera do not win 44 out of 100.");
  });
});

describe("accessibility review (the 14 checks of FE-004)", () => {
  test("complete", () => {
    expect(reviewProblems(PROB_ICONS_REVIEW)).toEqual([]);
  });

  test("shapes as well as colours: circle, square and triangle in the legend", () => {
    const html = renderToStaticMarkup(
      <ProbabilityIcons
        counts={{ home: 1, draw: 1, away: 98, adjusted: false }}
        home="A"
        away="B"
        figure="1 %"
      />,
    );
    const legend = html.slice(html.indexOf("prob-icons-legend"));
    expect(legend).toContain("<circle");
    expect(legend).toContain("<rect");
    expect(legend).toContain("<polygon");
  });
});

describe("contrast (WCAG AA) of the icons and the toggle", () => {
  const css = readFileSync(join(import.meta.dir, "..", "..", "styles.css"), "utf8");
  const tok = rootTokens(css);
  const solid = (name: string) => {
    const c = tok[name];
    if (!c) throw new Error(`no token ${name}`);
    return over(c, [0, 0, 0]);
  };
  const card = solid("card");
  // the market's frame: elevated at 30 % over the card (MarketView)
  const frame = over({ rgb: solid("elevated"), alpha: 0.3 }, card);

  test("the three shapes read at 3:1 or more on the market's frame (non-text contrast)", () => {
    const pairs: Array<[string, number]> = [
      ["home circle (primary)", contrast(solid("primary"), frame)],
      ["draw square (muted)", contrast(solid("muted-foreground"), frame)],
      ["away triangle (foreground)", contrast(solid("foreground"), frame)],
    ];
    expect(pairs.filter(([, r]) => r < 3).map(([n, r]) => `${n}: ${r.toFixed(2)}`)).toEqual([]);
  });

  test("the legend's and the toggle's words read at 4.5:1 or more", () => {
    const pairs: Array<[string, number]> = [
      ["legend (muted) on the frame", contrast(solid("muted-foreground"), frame)],
      ["note (subtle) on the frame", contrast(solid("subtle-foreground"), frame)],
      [
        "pressed option on primary at 15 %",
        contrast(solid("foreground"), over({ rgb: solid("primary"), alpha: 0.15 }, frame)),
      ],
    ];
    expect(pairs.filter(([, r]) => r < 4.5).map(([n, r]) => `${n}: ${r.toFixed(2)}`)).toEqual([]);
  });
});

describe("Mito o dato", () => {
  test("four statements, fixed words, no figure", () => {
    const html = renderToStaticMarkup(<MythOrFact />);
    expect(html.match(/data-testid="myth-item"/g)?.length).toBe(4);
    expect(html).toContain('data-verdict="fact"');
    const text = html.replace(/<[^>]+>/g, " ");
    expect(text).not.toMatch(/\d/);
  });
});
