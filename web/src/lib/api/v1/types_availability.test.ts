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
import competitionExample from "./fixtures/c16_competition.json";

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

  test("1.1.0: a season carries its phases and a match the phase that graded it (PM-02-07)", () => {
    const comp = competitionExample as unknown as Availability;
    expect(comp.contract_version).toBe("1.2.0");
    const phases = comp.competitions[0]?.seasons[0]?.phases ?? [];
    expect(phases.map((p) => p.phase)).toEqual(["previa", "liga_o_grupos"]);
    expect(phases[0]?.data.find((c) => c.key === "corners")?.level).toBe("C");
    expect((pub.match as MatchAvailability).phase).toBe("todas");
  });

  test("1.2.0: each competition carries its editorial priority (PM-09-05)", () => {
    const comp = competitionExample as unknown as Availability;
    expect(comp.competitions[0]?.priority).toBe("P1");
  });

  test("the private changes route carries the changes and the discrepancies", () => {
    expect(priv.projection).toBe("private");
    expect(priv.changes.items.length).toBeGreaterThan(0);
    expect(priv.discrepancies.items[0]?.shown).not.toBe(priv.discrepancies.items[0]?.matrix);
  });
});
