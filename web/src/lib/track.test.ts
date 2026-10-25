/// <reference types="bun" />
/**
 * Plan UX, A6: the browser's catalog of product events is the backend's, event by event and property by property, and
 * nothing outside it is ever sent. That the events of a journey arrive is checked in the browser
 * (e2e/analytics.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { EVENTS, deviceOf, originOf, validEvent } from "./track";

const BACKEND = join(
  import.meta.dir,
  "..",
  "..",
  "..",
  "backend",
  "src",
  "fbi",
  "customer",
  "events_catalog.json",
);

describe("the catalog of product events", () => {
  test("is the backend's: the same 35 events, groups, sources and properties", () => {
    const backend = JSON.parse(readFileSync(BACKEND, "utf8")) as {
      events: Record<string, { group: string; source: string; props: Record<string, unknown> }>;
    };
    expect(Object.keys(EVENTS).sort()).toEqual(Object.keys(backend.events).sort());
    expect(Object.keys(EVENTS)).toHaveLength(35);
    for (const [name, spec] of Object.entries(backend.events)) {
      const mine = (EVENTS as Record<string, { group: string; source: string; props: unknown }>)[
        name
      ];
      expect(mine?.group, name).toBe(spec.group);
      expect(mine?.source, name).toBe(spec.source);
      expect(JSON.parse(JSON.stringify(mine?.props)), name).toEqual(spec.props);
    }
  });

  test("sends only what the catalog allows, and never a server's event", () => {
    expect(validEvent("match_opened", { origin: "home", match_id: 1234 })).toEqual({
      origin: "home",
      match_id: 1234,
    });
    expect(validEvent("match_opened", { origin: "somewhere" })).toBeNull();
    expect(validEvent("match_opened", { match_id: -1 })).toBeNull();
    expect(validEvent("match_opened", { query: "free text" })).toBeNull();
    expect(validEvent("search_submitted", { results: 3.5 })).toBeNull();
    expect(validEvent("term_explained", { term: "cuota según PrediGol" })).toBeNull();
    expect(validEvent("term_explained", { term: "fair_odds" })).toEqual({ term: "fair_odds" });
    expect(validEvent("analysis_helpful_voted", { helpful: "yes" })).toBeNull();
    expect(validEvent("account_activated", {})).toBeNull();
    expect(validEvent("no_such_event", {})).toBeNull();
    expect(validEvent("pick_removed", { origin: undefined })).toEqual({});
  });

  test("the origin and the device class", () => {
    expect(originOf(null)).toBe("direct");
    expect(originOf("/home")).toBe("home");
    expect(originOf("/my-picks")).toBe("my_picks");
    expect(originOf("/matches/12")).toBe("other");
    expect([deviceOf(320), deviceOf(767), deviceOf(768), deviceOf(1024), deviceOf(1025)]).toEqual([
      "phone",
      "phone",
      "tablet",
      "tablet",
      "desktop",
    ]);
  });
});
