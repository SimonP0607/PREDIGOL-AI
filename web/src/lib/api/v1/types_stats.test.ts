/// <reference types="bun" />
/**
 * Plan PM (PM-05-05): C-13 1.1.0 carries the provider's extras of a player, read from the backend's own example (copied here from
 * `backend/tests/fixtures/contracts/intelligence/C-13/jugador.public.json`): each with its sample, its coverage and its origin.
 */
import { describe, expect, test } from "bun:test";
import type { PlayerBody, ProviderFigure } from "./types_stats";
import { isMissing } from "./types_intelligence";
import playerExample from "./fixtures/c13_player.json";

const example = playerExample as unknown as {
  contract: string;
  contract_version: string;
  entities: { player: PlayerBody }[];
};

describe("C-13 types: the provider's extras", () => {
  test("every extra says it is API-Football's, with its coverage", () => {
    expect(example.contract).toBe("C-13");
    expect(example.contract_version).toBe("1.1.0");
    const extras: ProviderFigure[] = example.entities[0]?.player.provider_extras ?? [];
    expect(extras.map((e) => e.key)).toEqual([
      "offsides",
      "dribbled_past",
      "penalties_won",
      "penalties_committed",
      "penalties_saved",
    ]);
    for (const e of extras) {
      expect(e.origin).toBe("api_football");
      expect(e.coverage).toBeGreaterThanOrEqual(0);
      expect(e.coverage).toBeLessThanOrEqual(1);
    }
    const saved = extras.find((e) => e.key === "penalties_saved");
    expect(saved && isMissing(saved.value)).toBe(true);
  });
});
