/// <reference types="bun" />
/**
 * Plan PM, PM-10-04 (OP-23, lámina I02 «M02»; UX-176): the data layers of the line-up pitch, with and without player statistics.
 * With them: four layers, the rating by default with the side's best in gold, the label «posición nominal», the table, sample and
 * origin. Without a line for every starter the layers are not drawn (the pitch is the line-up alone, as today).
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { reviewProblems } from "@/components/analytics/evidence";
import type { TeamRef } from "@/lib/api/v1/types";
import type { LineupPlayer, MatchEvent, PlayerLine, TeamLineup } from "@/lib/api/v1/types_center";
import { setLocale } from "@/lib/i18n";
import {
  LINEUP_LAYERS_REVIEW,
  bestRatings,
  goalsAssistsText,
  layerBadge,
  layerFigures,
  layersReady,
  tableRows,
} from "./layers";
import { LineupLayers } from "./LineupLayers";
import { Pitch } from "./Pitch";

setLocale("es");
afterEach(() => setLocale("es"));

function lp(id: number, side: "home" | "away", grid: string, name: string): LineupPlayer {
  return {
    provider_player_id: id,
    player_id: id,
    name,
    number: id % 100,
    position: "M",
    grid,
    starter: true,
  };
}

function pl(id: number, side: "home" | "away", over: Partial<PlayerLine> = {}): PlayerLine {
  return {
    provider_player_id: id,
    player_id: id,
    side,
    name: null,
    minutes: 90,
    rating: "7.0",
    goals: 0,
    assists: 0,
    shots: null,
    shots_on: null,
    passes: null,
    key_passes: null,
    tackles: null,
    yellow_cards: 0,
    red_cards: 0,
    saves: null,
    substitute: false,
    ...over,
  };
}

const HOME: TeamLineup = {
  side: "home",
  formation: "2-1",
  coach: null,
  players: [
    lp(101, "home", "1:1", "J. Quiceno"),
    lp(109, "home", "2:1", "T. Arbeláez"),
    lp(107, "home", "2:2", "J. Viáfara"),
    lp(110, "home", "3:1", "E. Lozada"),
  ],
};
const AWAY: TeamLineup = {
  side: "away",
  formation: "2-1",
  coach: null,
  players: [
    lp(201, "away", "1:1", "R. Uno"),
    lp(202, "away", "2:1", "R. Dos"),
    lp(203, "away", "2:2", "R. Tres"),
    lp(204, "away", "3:1", "R. Cuatro"),
  ],
};
const PLAYERS: PlayerLine[] = [
  pl(101, "home", { rating: "7.5" }),
  pl(109, "home", { rating: "8.3", goals: 1, assists: 1 }),
  pl(107, "home", { rating: "7.1", yellow_cards: 1 }),
  pl(110, "home", { rating: "7.2", minutes: 78, goals: 1 }),
  pl(201, "away", { rating: "6.6" }),
  pl(202, "away", { rating: "6.9" }),
  pl(203, "away", { rating: "6.4", red_cards: 1 }),
  pl(204, "away", { rating: "6.8" }),
];
const CARD: MatchEvent = {
  seq: 1,
  minute: 40,
  extra_minute: null,
  side: "home",
  player: "J. Viáfara",
  player_id: 107,
  assist: null,
  type: "Card",
  detail: "Yellow Card",
  comments: null,
};
const TEAMS = {
  home: { id: 1, name: "Cordillera" },
  away: { id: 2, name: "Altiplano" },
} as unknown as {
  home: TeamRef;
  away: TeamRef;
};
const WORDS = { yellowShort: "1 A", redShort: "R" };

describe("the layers (pure)", () => {
  const figures = layerFigures([HOME, AWAY], PLAYERS, [CARD]);

  test("each starter's four figures, cards from the events when there are some", () => {
    expect(figures.get(109)).toEqual({
      rating: 8.3,
      minutes: 90,
      yellow: 0,
      red: 0,
      goals: 1,
      assists: 1,
    });
    expect(figures.get(107)?.yellow).toBe(1);
    // the events name no card for 203: the events are the source when there are some
    expect(figures.get(203)?.red).toBe(0);
    expect(layerFigures([AWAY], PLAYERS, null).get(203)?.red).toBe(1);
    expect(layersReady([HOME, AWAY], figures)).toBe(true);
  });

  test("without a line for every starter, no layers", () => {
    const some = layerFigures([HOME, AWAY], PLAYERS.slice(0, 5), null);
    expect(layersReady([HOME, AWAY], some)).toBe(false);
    expect(layersReady([HOME, AWAY], layerFigures([HOME, AWAY], [], null))).toBe(false);
  });

  test("the badge of each layer: the side's best in gold, minutes, the card, G + A; nothing rather than a made-up zero", () => {
    const best = bestRatings([HOME, AWAY], figures);
    expect(best).toEqual({ home: 8.3, away: 6.9 });
    expect(layerBadge("rating", figures.get(109), best.home, WORDS)).toEqual({
      text: "8,3",
      tone: "best",
    });
    expect(layerBadge("rating", figures.get(101), best.home, WORDS)).toEqual({
      text: "7,5",
      tone: undefined,
    });
    expect(layerBadge("minutes", figures.get(110), null, WORDS)).toEqual({ text: "78'" });
    expect(layerBadge("cards", figures.get(107), null, WORDS)).toEqual({
      text: "1 A",
      tone: "yellow",
    });
    expect(layerBadge("cards", figures.get(101), null, WORDS)).toBeNull();
    expect(layerBadge("goalsAssists", figures.get(109), null, WORDS)).toEqual({ text: "1 + 1" });
    expect(layerBadge("goalsAssists", figures.get(101), null, WORDS)).toBeNull();
    expect(
      goalsAssistsText({
        rating: null,
        minutes: null,
        yellow: 0,
        red: 0,
        goals: null,
        assists: null,
      }),
    ).toBe("—");
  });

  test("the table: best rated first", () => {
    expect(tableRows(HOME, figures).map((r) => r.player.provider_player_id)).toEqual([
      109, 101, 110, 107,
    ]);
  });
});

describe("the card", () => {
  test("rating by default, the label, the table, sample and origin, E1 and a complete review", () => {
    const ratings = new Map(PLAYERS.map((p) => [p.provider_player_id, Number(p.rating)]));
    const html = renderToStaticMarkup(
      <LineupLayers
        home={HOME}
        away={AWAY}
        teams={TEAMS}
        players={PLAYERS}
        events={[CARD]}
        ratings={ratings}
      />,
    );
    expect(html).toContain("Capas de la alineación");
    for (const s of ["Valoración", "Minutos", "Tarjetas", "Goles y asistencias"])
      expect(html).toContain(s);
    expect(html).toContain('role="radiogroup"');
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain('data-layer="rating"');
    expect(html).toContain('data-badge="best"');
    expect(html).toContain("Posición nominal de formación, no posición real en el campo");
    expect(html).toContain("Las cuatro capas, en tabla");
    expect(html).toContain("Cordillera · 2-1");
    expect(html).toContain(
      "1 partido; estadísticas por jugador y eventos del partido de API-Football",
    );
    expect(html).toContain('data-evidence="E1"');
    expect(html).toContain('data-review="completa"');
    expect(reviewProblems(LINEUP_LAYERS_REVIEW)).toEqual([]);
  });

  test("the plain pitch is unchanged: the number and the small rating, no layer", () => {
    const html = renderToStaticMarkup(
      <Pitch home={HOME} away={AWAY} teams={TEAMS} ratings={new Map([[109, 8.3]])} />,
    );
    expect(html).toContain("8,3");
    expect(html).not.toContain("data-badge");
    expect(html).toContain("text-[0.55rem]");
  });

  test("in English", () => {
    setLocale("en");
    const html = renderToStaticMarkup(
      <LineupLayers
        home={HOME}
        away={AWAY}
        teams={TEAMS}
        players={PLAYERS}
        events={null}
        ratings={new Map()}
      />,
    );
    expect(html).toContain("Line-up layers");
    expect(html).toContain("Nominal position of the formation");
  });
});
