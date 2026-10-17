import { describe, expect, test } from "bun:test";
import type { Leader, SeasonRound } from "@/lib/api/v1/types_center";
import {
  careerSpan,
  leaderFigure,
  provenanceParts,
  ratingCountsUnrated,
  roundSpan,
} from "./reference";

const leader: Leader = {
  rank: 1,
  provider_player_id: 13491,
  player_id: null,
  name: "Y. Guzmán",
  photo_url: null,
  team_id: null,
  provider_team_id: 1138,
  team: "America de Cali",
  team_logo: null,
  appearances: 29,
  minutes: 2397,
  goals: 18,
  assists: 4,
  penalties_scored: 3,
  yellow_cards: 4,
  yellowred_cards: 0,
  red_cards: 0,
  rating: "7.55",
  unrated_matches: 0,
};

describe("reference helpers", () => {
  test("each top list ranks by its own figure", () => {
    expect(leaderFigure("topscorers", leader)).toBe(18);
    expect(leaderFigure("topassists", leader)).toBe(4);
    expect(leaderFigure("topyellowcards", leader)).toBe(4);
    expect(leaderFigure("topredcards", leader)).toBe(0);
  });

  test("a season rating that counts unrated matches as 0 is marked (Reinaldo 2026: 3.98)", () => {
    expect(ratingCountsUnrated(leader)).toBe(false);
    expect(ratingCountsUnrated({ ...leader, rating: "3.98", unrated_matches: 2 })).toBe(true);
  });

  test("a round spans its first and last listed date, in any order", () => {
    const r: SeasonRound = {
      ordinal: 1,
      round: "Apertura - 2",
      stage: "Apertura",
      phase: "Apertura",
      dates: ["2026-04-07", "2026-01-23", "2026-01-26"],
      is_current: false,
    };
    expect(roundSpan(r)).toEqual(["2026-01-23", "2026-04-07"]);
    expect(roundSpan({ ...r, dates: [] })).toBeNull();
  });

  test("a provenance line names the source and only what is known", () => {
    const parts = provenanceParts({
      source: "API-Football /trophies",
      observed_at: null,
      payload_hash: null,
      normalizer_version: null,
      checked_at: "2026-10-04T18:00:00Z",
    });
    expect(parts.map((p) => p.key)).toEqual(["source", "asked"]);
  });
});

describe("careerSpan", () => {
  test("a run of consecutive seasons reads as a span, gaps as a list, newest first", () => {
    expect(careerSpan([2022, 2023, 2024, 2025, 2026])).toBe("2026–2022");
    expect(careerSpan([2024, 2026, 2021])).toBe("2026, 2024, 2021");
    expect(careerSpan([2026, 2025])).toBe("2026, 2025");
    expect(careerSpan([2026, 2026])).toBe("2026");
    expect(careerSpan([])).toBe("");
  });
});
