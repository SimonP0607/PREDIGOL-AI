/// <reference types="bun" />
/**
 * Plan PM (PM-02-05): the types of C-16 «Disponibilidad» read the backend's own examples (copied here from
 * `backend/tests/fixtures/contracts/intelligence/C-16/`): the public projection never carries Mi parlay's verdict by selection,
 * and every market says what Mi parlay, Picks and Cuotas do with it.
 */
import { describe, expect, test } from "bun:test";
import type { Availability, AvailabilityPrivate, MatchAvailability } from "./types_availability";
import { isMissing } from "./types_intelligence";
import matchExample from "./fixtures/c16_match.json";
import changesExample from "./fixtures/c16_changes_private.json";

const pub = matchExample as unknown as Availability;
const priv = changesExample as unknown as AvailabilityPrivate;

describe("C-16 types", () => {
  test("the match answer is the public projection, with its seven states per market", () => {
    expect(pub.contract).toBe("C-16");
    expect(pub.projection).toBe("public");
    expect(pub.scope).toBe("partido");
    expect(isMissing(pub.match)).toBe(false);
    const match = pub.match as MatchAvailability;
    for (const m of match.markets) {
      expect(m.modules.map((v) => v.module)).toEqual(["mi_parlay", "picks", "cuotas"]);
      expect("selections" in m).toBe(false);
      expect(typeof m.price_in_force).toBe("boolean");
    }
  });

  test("the private changes route carries the changes and the discrepancies", () => {
    expect(priv.projection).toBe("private");
    expect(priv.changes.items.length).toBeGreaterThan(0);
    expect(priv.discrepancies.items[0]?.shown).not.toBe(priv.discrepancies.items[0]?.matrix);
  });
});
