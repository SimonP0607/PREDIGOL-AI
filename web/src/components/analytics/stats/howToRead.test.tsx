/// <reference types="bun" />
/**
 * AP-T03: the sentences «Cómo leerlo» of a team's charts are written from the contract's figures (C-13, the backend's own fixture),
 * in words, with no method names and no «p63»; the review of the 14 checks stays true (texts of 12 px, a table for each chart).
 */
import { afterEach, describe, expect, test } from "bun:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { StatsProfile, TeamBody } from "@/lib/api/v1/types_stats";
import { present } from "@/lib/api/v1/types_intelligence";
import { readingSentence, reviewProblems } from "../evidence";
import { READER_REVIEW } from "../readerReview";
import preview from "./fixtures/c13_preview.json";
import player from "./fixtures/c13_player.json";
import type { PlayerBody } from "@/lib/api/v1/types_stats";
import {
  comparePlayersReading,
  compareRadarReading,
  figurePlace,
  lastFiveReading,
  minutesReading,
  playerReading,
  scatterReading,
  halvesReading,
  intervalsReading,
  performanceReading,
  placeInWords,
  pulseReading,
  radarReading,
  slotWords,
  statesReading,
  survivalReading,
  trendsReading,
  xgReading,
  xgPoint,
} from "./howToRead";
import { PercentileBars } from "./PercentileBars";
import { RadarBars } from "./RadarBars";
import { XgLine } from "./SmallCharts";

afterEach(() => setLocale("es"));

const body = (preview as unknown as StatsProfile).entities[0]!.team as TeamBody;
const name = body.team.name;
const said = (r: { sentence: string }) => r.sentence;

describe("the place in its league, in words", () => {
  test("better, worse and the middle", () => {
    setLocale("es");
    expect(placeInWords(63)).toBe("mejor que el 63 % de su liga");
    expect(placeInWords(20)).toBe("peor que el 80 % de su liga");
    expect(placeInWords(50)).toBe("justo en la mitad de su liga");
    setLocale("en");
    expect(placeInWords(63)).toBe("better than 63 % of its league");
  });

  test("the bins of the pulse are said as minutes, the added time as added time", () => {
    setLocale("es");
    expect(slotWords("46-50")).toBe("los minutos 46–50");
    expect(slotWords("45+")).toBe("el tiempo añadido del primer tiempo");
    expect(slotWords("90+")).toBe("el tiempo añadido del segundo tiempo");
  });

  test("a percentile bar says it in words, never as «p63», and turns a less-is-better figure round", () => {
    setLocale("es");
    const html = renderToStaticMarkup(<PercentileBars figures={body.figures} />);
    expect(html).toMatch(
      /mejor que el \d+ % de su liga|peor que el \d+ % de su liga|mitad de su liga/,
    );
    expect(html).not.toMatch(/>p\d+</);
  });
});

describe("the sentences of the team's charts come from the contract", () => {
  test("every chart with data has a sentence with the team's name and its sample", () => {
    setLocale("es");
    const n = body.record.matches;
    const sentences = [
      performanceReading(name, body.figures, n, 18),
      body.states && present(body.states) ? statesReading(name, present(body.states)!) : null,
      present(body.pulse_for)
        ? pulseReading(name, present(body.pulse_for)!, present(body.pulse_against))
        : null,
      present(body.intervals) ? intervalsReading(name, present(body.intervals)!) : null,
      present(body.survival) ? survivalReading(name, present(body.survival)!) : null,
      present(body.halves) ? halvesReading(name, present(body.halves)!) : null,
      radarReading(name, body.radar, n),
    ].filter((x): x is NonNullable<typeof x> => x !== null);
    expect(sentences.length).toBeGreaterThanOrEqual(5);
    for (const s of sentences) {
      expect(s.kind).toBe("text");
      expect(readingSentence(s)).toContain(name);
      expect(s.sentence).not.toMatch(/\\bp\\d{2}\\b|bootstrap|Kaplan|pulso-v|API-Football/i);
      expect(s.sentence).not.toMatch(/undefined|NaN|\\{[a-z]+\\}/);
    }
  });

  test("the pulse names its best stretch with the figure the server sent", () => {
    setLocale("es");
    const pulse = present(body.pulse_for)!;
    const top = pulse.bins
      .filter((b) => typeof b.index === "number")
      .reduce((a, b) => ((b.index as number) > (a.index as number) ? b : a));
    const s = said(pulseReading(name, pulse, null));
    if ((top.index as number) > 100) {
      expect(s).toContain(`un ${Math.round((top.index as number) - 100)} % más de goles`);
      expect(s).toContain(slotWords(top.label));
    } else expect(s).toContain("no supera a la media de su liga");
  });

  test("a sample under five matches is said to be an anecdote", () => {
    setLocale("es");
    const r = halvesReading(name, { ...present(body.halves)!, matches_with_data: 3 });
    expect(r.sentence).toContain("Muestra pequeña (3 partidos)");
    expect(r.n).toBeLessThan(r.minSample);
  });

  test("the xG sentence needs xG: a league without it has none, so no chart is drawn", () => {
    setLocale("es");
    const none = body.series.map((p) => ({ ...p, xg_for_avg5: null, xg_against_avg5: null }));
    expect(xgPoint(none as never)).toBeNull();
    expect(xgReading(name, none as never)).toBeNull();
  });

  test("English reads in English", () => {
    setLocale("en");
    const s = said(radarReading(name, body.radar, body.record.matches));
    expect(s).toMatch(/strongest aspect/);
    expect(s).not.toMatch(/mejor|peor/);
  });

  test("the trends name what differs most from the league, with its sample", () => {
    setLocale("es");
    const r = trendsReading(name, body.trends.items, body.record.matches);
    if (r) expect(r.sentence).toMatch(/de \d+ partidos; en su liga, el \d+ %/);
  });
});

const pl = (player as unknown as StatsProfile).entities[0]!.player as PlayerBody;

describe("the sentences of a player's charts and of the comparisons", () => {
  test("a player against his position, in words, with the 90 minutes behind it", () => {
    setLocale("es");
    const r = playerReading(pl, "delantero");
    expect(r.sentence).toContain(pl.player.name);
    expect(r.sentence).toMatch(
      /mejor que el \d+ % de su liga|peor que el \d+ % de su liga|mitad de su liga/,
    );
    expect(r.sentence).not.toMatch(/\bp\d{2}\b|undefined|NaN/);
    expect(r.minSample).toBe(Math.ceil(pl.min_nineties));
  });

  test("few minutes played are said to be an anecdote", () => {
    setLocale("es");
    const r = playerReading({ ...pl, nineties: 1.2, min_nineties: 5 }, "medio");
    expect(r.sentence).toContain("Pocos minutos jugados (1 partidos completos)");
    expect(r.n).toBeLessThan(r.minSample);
  });

  test("the last five say the values the server sent and their mean", () => {
    setLocale("es");
    const metric = pl.last5[0]!.values[0]!.key;
    const r = lastFiveReading(pl.player.name, pl.last5, metric);
    expect(r.sentence).toContain(pl.player.name);
    expect(r.sentence).toMatch(/de media, [\d,]+/);
  });

  test("minutes: starts of appearances and the sum of the last ones", () => {
    setLocale("es");
    const r = minutesReading(pl);
    expect(r.sentence).toContain(`titular en ${pl.starts} de ${pl.appearances} partidos`);
    expect(r.sentence).toContain(
      `sumó ${pl.recent_minutes.reduce((a, m) => a + m.minutes, 0)} minutos`,
    );
  });

  test("two teams: the aspect where they differ most; two players: the figure", () => {
    setLocale("es");
    const r = compareRadarReading(
      { name: "A", axes: body.radar },
      {
        name: "B",
        axes: body.radar.map((x) => ({ ...x, percentile: 100 - (x.percentile as number) })),
      },
      20,
    );
    expect(r.sentence).toMatch(/^A y B se parecen menos en /);
    const other = { ...pl, player: { ...pl.player, name: "Otro" } };
    const p = comparePlayersReading(pl, other);
    expect(p.sentence).toContain(pl.player.name);
    expect(p.sentence).toContain("Otro");
  });

  test("the scatter sentence needs both points", () => {
    setLocale("es");
    const pt = { player_id: 1, shots_per90: 3.456, on_target_pct: 41.6 };
    expect(scatterReading({ name: "A", point: pt }, { name: "B", point: null }, 10, 5)).toBeNull();
    expect(
      scatterReading(
        { name: "A", point: pt },
        { name: "B", point: { ...pt, shots_per90: 1 } },
        10,
        5,
      )!.sentence,
    ).toBe("A: 3,5 tiros por 90 minutos y 42 % a puerta; B: 1,0 y 42 %.");
  });

  test("a figure's place is null when the server sent no percentile", () => {
    const f = { ...pl.figures[0]!, percentile: { missing_reason: "sin_datos" } } as never;
    expect(figurePlace(f)).toBeNull();
  });
});

describe("the review of the 14 checks stays true", () => {
  test("it is complete", () => {
    expect(reviewProblems(READER_REVIEW)).toEqual([]);
  });

  test("no text of the drawings is under 12 px", () => {
    const dir = join(import.meta.dir);
    const bad: string[] = [];
    for (const f of readdirSync(dir).filter((x) => /\.tsx$/.test(x) && !/\.test\./.test(x))) {
      const src = readFileSync(join(dir, f), "utf8");
      for (const m of src.matchAll(/fontSize[=:]\s*\{?\s*"?([\d.]+)/g))
        if (Number(m[1]) < 12) bad.push(`${f}: fontSize ${m[1]}`);
      if (/text-caption|text-\[(?:[0-9]|1[01])px\]/.test(src)) bad.push(`${f}: text under 12 px`);
    }
    expect(bad).toEqual([]);
  });

  test("the radar starts as bars, and each drawing keeps its table or list for a screen reader", () => {
    setLocale("es");
    const radar = renderToStaticMarkup(
      <RadarBars sides={[{ name, axes: body.radar, color: "red" }]} />,
    );
    expect(radar).toContain('aria-checked="true"');
    expect(radar).not.toMatch(/>p\d+</);
    const xg = renderToStaticMarkup(<XgLine series={body.series} />);
    expect(xg).toContain("<table");
  });
});
