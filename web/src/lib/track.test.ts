/// <reference types="bun" />
/**
 * Plan UX, A6: the browser's catalog of product events is the backend's, event by event and property by property, and
 * nothing outside it is ever sent. That the events of a journey arrive is checked in the browser
 * (e2e/analytics.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  EVENTS,
  deviceOf,
  noteLocation,
  noteNoticeLanding,
  originOf,
  screenOf,
  validEvent,
} from "./track";

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
  test("is the backend's: the same 36 events, groups, sources and properties", () => {
    const backend = JSON.parse(readFileSync(BACKEND, "utf8")) as {
      events: Record<string, { group: string; source: string; props: Record<string, unknown> }>;
    };
    expect(Object.keys(EVENTS).sort()).toEqual(Object.keys(backend.events).sort());
    expect(Object.keys(EVENTS)).toHaveLength(36);
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

  test("a pick's or a leg's market is one of the five, and a screen is a group of a closed list", () => {
    expect(validEvent("pick_saved", { origin: "market", market: "BTTS" })).toEqual({
      origin: "market",
      market: "BTTS",
    });
    expect(validEvent("slip_leg_added", { legs: 2, market: "OU" })).toEqual({
      legs: 2,
      market: "OU",
    });
    expect(validEvent("slip_leg_added", { legs: 2, market: undefined })).toEqual({ legs: 2 });
    expect(validEvent("pick_saved", { market: "CS" })).toBeNull();
    expect(validEvent("slip_leg_added", { market: "OU_2.5" })).toBeNull();
    expect(validEvent("screen_viewed", { screen: "my_picks" })).toEqual({ screen: "my_picks" });
    expect(validEvent("screen_viewed", { screen: "/matches/123?q=real" })).toBeNull();
    expect(validEvent("screen_viewed", { path: "/home" })).toBeNull();
    expect(validEvent("screen_viewed", { screen: "match", match_id: 5 })).toBeNull();
  });

  test("the screen a path is: its kind, never the address, a search or an id", () => {
    expect(screenOf("/")).toBe("home");
    expect(screenOf("/home")).toBe("home");
    expect(screenOf("/matches")).toBe("matches");
    expect(screenOf("/matches/")).toBe("matches");
    expect(screenOf("/matches/18423")).toBe("match");
    expect(screenOf("/matches/18423?tab=markets")).toBe("match");
    expect(screenOf("/my-picks")).toBe("my_picks");
    expect(screenOf("/help/glossary")).toBe("help");
    expect(screenOf("/help/messages/77")).toBe("help");
    expect(screenOf("/legal/privacy")).toBe("legal");
    for (const path of ["/live", "/picks", "/parlays", "/odds", "/updates", "/transparency"]) {
      expect(screenOf(path)).toBe(path.slice(1) as ReturnType<typeof screenOf>);
    }
    expect(screenOf("/profile")).toBe("profile");
    expect(screenOf("/welcome")).toBe("welcome");
    expect(screenOf("/admin/analytics")).toBe("other");
    expect(screenOf("/something-new")).toBe("other");
    // whatever it is given, what comes out is one of the catalog's values
    const allowed = (EVENTS.screen_viewed.props.screen as unknown as { enum: readonly string[] })
      .enum;
    for (const path of ["/", "/x/y/z", "/matches/9", "/my-picks", "", "/%20"]) {
      expect(allowed).toContain(screenOf(path));
    }
  });

  test("the origin and the device class", () => {
    expect(originOf(null)).toBe("direct");
    expect(originOf("/home")).toBe("home");
    expect(originOf("/my-picks")).toBe("my_picks");
    expect(originOf("/matches/12")).toBe("other");
    // Plan UX, B7: the page a tapped notice opened says so; the next page says where the reader came from
    noteLocation("/matches/12");
    noteNoticeLanding();
    expect(originOf()).toBe("notification");
    noteLocation("/my-picks");
    expect(originOf()).toBe("other");
    expect([deviceOf(320), deviceOf(767), deviceOf(768), deviceOf(1024), deviceOf(1025)]).toEqual([
      "phone",
      "phone",
      "tablet",
      "tablet",
      "desktop",
    ]);
  });
});
