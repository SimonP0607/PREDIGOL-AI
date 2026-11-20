/// <reference types="bun" />
/**
 * Plan PM, PM-08-06 (UX-180; lámina I06): the goalkeeper gets «Bajo los palos» (saves, the share saved, goals conceded, penalties
 * saved) and «Con el balón»; every player gets penalties and offsides as API-Football measured them. In a competition at level A
 * the blocks are drawn as the lámina; at C they say they are partial; at D, or with a short sample, they are not drawn and one line
 * says why. A figure without coverage keeps its reason, never a zero; a goalkeeper's goals prevented stay out and the page says why.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { PlayerBody, StatFigure, StatsEntity } from "@/lib/api/v1/types_stats";
import example from "@/lib/api/v1/fixtures/c13_player.json";
import { PlayerExtrasView } from "./PlayerExtras";
import { blockState, hasValues, playerExtrasView } from "./extrasModel";

afterAll(() => setLocale("es"));

const forward = (example as unknown as { entities: StatsEntity[] }).entities[0]!
  .player as PlayerBody;

function fig(key: string, value: number, unit: StatFigure["unit"], league: number): StatFigure {
  return {
    key,
    unit,
    better: key === "goals_conceded" ? "menos" : "mas",
    value,
    matches_with_data: 16,
    percentile: 60,
    league_value: league,
    distribution: { missing_reason: "sin_datos" },
  } as StatFigure;
}

const keeper: PlayerBody = {
  ...forward,
  player: { id: 1, name: "J. Quiceno" },
  position: "portero",
  appearances: 16,
  minutes: 1440,
  nineties: 16,
  min_nineties: 5,
  figures: [
    fig("saves", 3.06, "por_90", 2.8),
    fig("save_pct", 77.8, "porcentaje", 70.1),
    fig("goals_conceded", 0.88, "por_90", 1.2),
    fig("passes", 24.5, "por_90", 21.0),
    fig("pass_accuracy", 71.0, "porcentaje", 66.0),
  ],
  provider_extras: [
    {
      key: "penalties_saved",
      unit: "total",
      better: "mas",
      value: 2,
      matches_with_data: 16,
      coverage: 1,
      origin: "api_football",
    },
    {
      key: "offsides",
      unit: "por_90",
      better: "menos",
      value: { missing_reason: "sin_cobertura" },
      matches_with_data: 3,
      coverage: 0.2,
      origin: "api_football",
    },
  ],
};

describe("the model", () => {
  test("a goalkeeper: under the posts with his penalties saved, on the ball, and his goals prevented held", () => {
    const v = playerExtrasView(keeper, "A");
    expect(v.keeper).toBe(true);
    expect(v.underPosts.map((f) => f.key)).toEqual([
      "saves",
      "save_pct",
      "goals_conceded",
      "penalties_saved",
    ]);
    expect(v.underPosts.at(-1)?.origin).toBe("api_football");
    expect(v.withBall.map((f) => f.key)).toEqual(["passes", "pass_accuracy"]);
    expect(v.goalsPreventedHeld).toBe(true);
    expect(v.discipline.find((f) => f.key === "offsides")?.missing).toBe("sin_cobertura");
  });

  test("an outfield player: no goalkeeper blocks, penalties and offsides from the provider", () => {
    const v = playerExtrasView(forward, "A");
    expect(v.keeper).toBe(false);
    expect(v.underPosts).toEqual([]);
    expect(v.discipline.map((f) => f.key)).toEqual([
      "penalties_won",
      "penalties_committed",
      "offsides",
      "dribbled_past",
    ]);
    expect(v.goalsPreventedHeld).toBe(false);
  });

  test("the state follows the level of the player data, and a short sample", () => {
    expect(blockState("A", false)).toBe("visible");
    expect(blockState(null, false)).toBe("visible");
    expect(blockState("C", false)).toBe("parcial");
    expect(blockState("D", false)).toBe("no_ofrece");
    expect(blockState("MI", false)).toBe("muestra_corta");
    expect(blockState("A", true)).toBe("muestra_corta");
    expect(hasValues([])).toBe(false);
  });
});

describe("the blocks", () => {
  test("level A: the goalkeeper's blocks with units, league and sample, and why goals prevented are not shown", () => {
    const out = renderToStaticMarkup(<PlayerExtrasView body={keeper} level="A" />);
    expect(out).toContain("Bajo los palos");
    expect(out).toContain("Con el balón");
    expect(out).toContain("77,8 %");
    expect(out).toContain("liga 70,1 %");
    expect(out).toContain("Penaltis parados");
    expect(out).toContain("Muestra: 16 partidos y 1440 minutos");
    expect(out).toContain("Pocos partidos de esta competición traen estos datos (3 como mucho)");
    expect(out).toContain("Goles evitados");
    expect(out).toContain("no pasó la comprobación de calidad");
    expect(out).toContain("Dato de API-Football");
    expect(out).not.toContain("parcial");
  });

  test("level C: drawn, and said to be partial", () => {
    const out = renderToStaticMarkup(<PlayerExtrasView body={forward} level="C" />);
    expect(out).toContain("Penaltis y fueras de juego");
    expect(out).toContain('data-unavailable="cobertura_parcial"');
    expect(out).not.toContain("Bajo los palos");
  });

  test("level D: not drawn, one line says the competition does not offer it", () => {
    const out = renderToStaticMarkup(<PlayerExtrasView body={keeper} level="D" />);
    expect(out).toContain('data-unavailable="no_existe"');
    expect(out).not.toContain('data-testid="player-extras"');
  });

  test("a reserve goalkeeper with a short sample: the count, never a rate", () => {
    const out = renderToStaticMarkup(
      <PlayerExtrasView body={{ ...keeper, appearances: 2, nineties: 1.5 }} level="A" />,
    );
    expect(out).toContain('data-unavailable="muestra_insuficiente"');
    expect(out).not.toContain("77,8 %");
  });
});
