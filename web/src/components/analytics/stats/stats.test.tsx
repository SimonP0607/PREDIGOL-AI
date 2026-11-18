/// <reference types="bun" />
/**
 * Plan EA (EA-101): the statistics' components draw the contract's examples (the backend's own fixtures of C-13 and C-14, copied
 * here) without recomputing them, say why a value is missing, and never show a model's figure on a market that is not evaluable.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { MarketProbs, StatsProfile, TeamBody, PlayerBody } from "@/lib/api/v1/types_stats";
import preview from "./fixtures/c13_preview.json";
import player from "./fixtures/c13_player.json";
import probs from "./fixtures/c14_match.json";
import probsPrivate from "./fixtures/c14_match_private.json";
import { lineWindow } from "@/product/match/stats/lines";
import { PercentileBars } from "./PercentileBars";
import { PulseChart } from "./PulseChart";
import { MirrorBins } from "./MirrorBins";
import { SurvivalCurve } from "./SurvivalCurve";
import { TrendMatrix, WilsonRow } from "./Trends";
import { DistributionRow } from "./PositionDistribution";
import { LastFive, StateBar } from "./SmallCharts";
import { figValue, goodness, missingText } from "./format";
import { TriMark } from "@/product/match/stats/ProbabilitiesPanel";

setLocale("es");
afterEach(() => setLocale("es"));

const profile = preview as unknown as StatsProfile;
const home = profile.entities[0]!.team as TeamBody;
const p = (player as unknown as StatsProfile).entities[0]!.player as PlayerBody;

describe("C-13 drawn", () => {
  test("percentile bars: every figure, its value and its percentile", () => {
    const html = renderToStaticMarkup(<PercentileBars figures={home.figures} />);
    expect(html).toContain("xG a favor");
    expect(html).toContain("Sin datos");
    expect(html.match(/<li/g)?.length).toBe(home.figures.length);
  });

  test("a value under the coverage says so, never a zero", () => {
    expect(missingText({ missing_reason: "sin_cobertura" })).toBe(
      "Su liga no lo registra lo suficiente",
    );
    expect(
      missingText({ missing_reason: "muestra_insuficiente", sample: 2, min_sample: 8 }),
    ).toContain("2 de 8");
  });

  test("a less-is-better figure turns its percentile round for its colour only", () => {
    const f = home.figures.find((x) => x.key === "goals_against")!;
    expect(goodness({ ...f, percentile: 20 })).toBe(80);
    expect(figValue({ ...f, value: 1.5 })).toBe("1,50");
  });

  test("the pulse draws the band and keeps a table of its numbers", () => {
    const pulse = home.pulse_for as Exclude<TeamBody["pulse_for"], { missing_reason: string }>;
    const html = renderToStaticMarkup(
      <PulseChart label="Pulso" series={[{ name: "A favor", pulse, color: "red" }]} />,
    );
    expect(html).toContain("<polygon");
    expect(html).toContain("<table");
    expect(html).toContain("90+");
  });

  test("goals by interval, survival, states and trends", () => {
    const intervals = home.intervals as Exclude<TeamBody["intervals"], { missing_reason: string }>;
    expect(renderToStaticMarkup(<MirrorBins intervals={intervals} />)).toContain("1-15");
    const s = home.survival as Exclude<TeamBody["survival"], { missing_reason: string }>;
    expect(
      renderToStaticMarkup(
        <SurvivalCurve series={[{ name: "x", points: s.points, color: "red" }]} />,
      ),
    ).toContain("<path");
    const st = home.states as Exclude<TeamBody["states"], { missing_reason: string }>;
    expect(renderToStaticMarkup(<StateBar states={st} />)).toContain("puntos rescatados");
    const row = home.trends.items[0]!;
    expect(renderToStaticMarkup(<WilsonRow label="x" row={row} />)).toContain(
      `${row.hits}/${row.n}`,
    );
    expect(
      renderToStaticMarkup(
        <TrendMatrix
          columns={[{ context: "all", matches: 5, rows: home.trends.items }]}
          keys={["win"]}
        />,
      ),
    ).toContain("Gana");
  });

  test("a player on the distribution of his position, and his last five", () => {
    const f = p.figures[0]!;
    const html = renderToStaticMarkup(
      <DistributionRow players={[{ name: "J", figure: f, color: "red" }]} />,
    );
    expect(html).toContain("rounded-full");
    const strip = renderToStaticMarkup(<LastFive strip={p.last5} metric="goals" />);
    expect(strip).toContain("Media");
  });
});

describe("C-14 drawn", () => {
  const reader = probs as unknown as MarketProbs;
  const owner = probsPrivate as unknown as MarketProbs;
  test("the reader never gets a model figure on a market in calibration", () => {
    const corners = reader.markets.items.find((m) => m.unit === "CORNERS_OU")!;
    expect(corners.state).toBe("en_calibracion");
    for (const s of corners.selections) {
      expect("missing_reason" in (s.model as object)).toBe(true);
      expect(s.model_shadow).toBeUndefined();
    }
  });

  test("three marks: the model's bar only where there is one; the owner sees the shadow as such", () => {
    const one = reader.markets.items.find((m) => m.unit === "1X2")!;
    expect(renderToStaticMarkup(<TriMark s={one.selections[0]!} owner={false} />)).toContain(
      "bg-primary",
    );
    const corners = owner.markets.items.find((m) => m.unit === "CORNERS_OU")!;
    expect(
      renderToStaticMarkup(<TriMark s={corners.selections[0]!} owner={false} />),
    ).not.toContain("bg-warning");
    expect(renderToStaticMarkup(<TriMark s={corners.selections[0]!} owner={true} />)).toContain(
      "bg-warning",
    );
  });
});

describe("the lines of a total (FE-003)", () => {
  test("the chip of the line shown is always among the eight", () => {
    const lines = [4.5, 5.5, 6.5, 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12.5];
    expect(lineWindow(lines, 11)).toContain(11);
    expect(lineWindow(lines, 11)).toHaveLength(8);
    expect(lineWindow(lines, 4.5)[0]).toBe(4.5);
    expect(lineWindow(lines, 12.5).at(-1)).toBe(12.5);
    expect(lineWindow([1, 2, 3], 2)).toEqual([1, 2, 3]);
  });
});
