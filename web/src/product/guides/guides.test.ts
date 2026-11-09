/// <reference types="bun" />
/**
 * The guides' engine (plan UX-051) without a browser: the registry's limits, who is owed what and what stands in the way of a
 * launch, the offline queue, the page's copy of the server's rules, the walk through the cards, where the card is put, and the
 * texts in both languages.
 */
import { afterAll, beforeEach, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { HOW_CARD_IDS } from "@/product/help/howItWorks";
import { setLocale, translate } from "@/lib/i18n";
import enGuides from "@/locales/en/guides.json";
import esGuides from "@/locales/es/guides.json";
import type { GuideIn, GuideKey, GuideState } from "@/lib/api/v1/types_guides";
import type { Me } from "@/lib/api/v1/types_auth";
import { anotherLayerOpen, placeCard, resolvable } from "./anchors";
import { MAX_SKIPS, blockedBy, owed, type Facts } from "./eligibility";
import { cardsOf, firstFrom, neighbour, numbered } from "./navigation";
import { PROFILE_STEPS, profileParts, profileTitle, type ProfileFacts } from "./profileText";
import { dequeue, dropLegacy, enqueue, flush, readQueue, refused } from "./queue";
import { GUIDES, GUIDE_LIST, guideOfScreen, launchable, stepCount } from "./registry";
import { applied, seenOf, withGuide } from "./state";

const FREE: Facts = {
  reader: true,
  guidesOn: true,
  auto: true,
  welcomeDue: false,
  consentsDue: false,
  limited: false,
  fromNotice: false,
  active: false,
  layerOpen: false,
  launchedThisVisit: false,
  skipsInARow: 0,
};
const there = () => ({}) as HTMLElement;
const everywhere = () => there();
const nowhere = () => null;

describe("the registry", () => {
  test("a definition for each of the ten guides, in the API's order, each under its own key", () => {
    expect(GUIDE_LIST.map((g) => g.key)).toEqual([
      "general",
      "home",
      "matches",
      "live",
      "match",
      "picks",
      "parlays",
      "odds",
      "my_picks",
      "profile",
    ]);
    for (const [key, def] of Object.entries(GUIDES)) expect(def.key).toBe(key as GuideKey);
  });

  test("only Perfil is owed; the general tour has a welcome and five steps", () => {
    expect(GUIDE_LIST.filter((g) => g.mandatory).map((g) => g.key)).toEqual(["profile"]);
    expect(GUIDES.general.welcome).toBe(true);
    expect(GUIDES.general.steps).toHaveLength(5);
    expect(stepCount(GUIDES.general)).toBe(6);
  });

  test("a guide never has more cards than the API accepts steps for (general 6, Perfil 6, a screen 3)", () => {
    const most: Partial<Record<GuideKey, number>> = { general: 6, profile: 6 };
    for (const def of GUIDE_LIST) expect(stepCount(def)).toBeLessThanOrEqual(most[def.key] ?? 3);
  });

  test("step ids and anchors are unique inside a guide and every guide has a path", () => {
    for (const def of GUIDE_LIST) {
      const ids = def.steps.map((s) => s.id);
      expect(new Set(ids).size).toBe(ids.length);
      expect(def.path.startsWith("/")).toBe(true);
      for (const s of def.steps) expect(s.anchors.length).toBeGreaterThan(0);
    }
  });

  test("Inicio's own guide is covered by the general tour, and a screen finds the guide built for it", () => {
    expect(GUIDES.home.coveredBy).toBe("general");
    expect(guideOfScreen("home")?.key).toBe("general");
    expect(guideOfScreen("odds")?.key).toBe("odds");
    expect(guideOfScreen("profile")?.key).toBe("profile");
    expect(guideOfScreen("live")?.key).toBe("live");
  });
});

describe("who is owed what", () => {
  const general = GUIDES.general;
  const seen = (status: GuideState["status"], step = 0, version = 1) => ({ status, step, version });

  test("never seen: start; completed or skipped: nothing; left half way: resume from the step", () => {
    expect(owed(general, undefined)).toBe("start");
    expect(owed(general, seen("pending"))).toBe("start");
    expect(owed(general, seen("completed"))).toBeNull();
    expect(owed(general, seen("skipped", 2))).toBeNull();
    expect(owed(general, seen("in_progress", 3))).toBe("resume");
    expect(owed(general, seen("in_progress", 0))).toBe("start");
  });

  test("a guide without steps (not built) owes nothing and is not launchable", () => {
    const empty = { ...GUIDES.odds, steps: [] };
    expect(owed(empty, undefined)).toBeNull();
    expect(launchable(empty)).toBe(false);
  });

  test("an earlier version than the one to show again starts over, whatever it was", () => {
    const later = { ...general, version: 2, reshowFrom: 2 };
    expect(owed(later, seen("completed", 5, 1))).toBe("start");
    expect(owed(later, seen("completed", 5, 2))).toBeNull();
  });
});

describe("what stands in the way", () => {
  const screen = GUIDES.general;
  const owedGuide = { ...GUIDES.profile, steps: [{ id: "x", anchors: ["x"] }] };

  test("free: it may launch", () => {
    expect(blockedBy(screen, FREE)).toBeNull();
  });

  test.each([
    ["not-a-reader", { reader: false }],
    ["switch-off", { guidesOn: false }],
    ["welcome-due", { welcomeDue: true }],
    ["consents-due", { consentsDue: true }],
    ["limited", { limited: true }],
    ["another-guide", { active: true }],
    ["layer-open", { layerOpen: true }],
    ["from-notice", { fromNotice: true }],
    ["one-per-visit", { launchedThisVisit: true }],
    ["skips", { skipsInARow: MAX_SKIPS }],
  ] as const)("%s", (reason, change) => {
    expect(blockedBy(screen, { ...FREE, ...change })).toBe(reason);
  });

  test("the reader's own switch stops a screen's guide but not the general tour", () => {
    const home = { ...GUIDES.home, steps: [{ id: "x", anchors: ["x"] }] };
    expect(blockedBy(home, { ...FREE, auto: false })).toBe("personal-switch");
    expect(blockedBy(GUIDES.general, { ...FREE, auto: false })).toBeNull();
  });

  test("the owed guide ignores the personal switch, the visit and the skips, but not the account's rules", () => {
    const worn = {
      ...FREE,
      auto: false,
      fromNotice: true,
      launchedThisVisit: true,
      skipsInARow: 9,
    };
    expect(blockedBy(owedGuide, worn)).toBeNull();
    expect(blockedBy(owedGuide, { ...worn, consentsDue: true })).toBe("consents-due");
    expect(blockedBy(owedGuide, { ...worn, limited: true })).toBe("limited");
    expect(blockedBy(owedGuide, { ...worn, reader: false })).toBe("not-a-reader");
    expect(blockedBy(owedGuide, { ...worn, guidesOn: false })).toBe("switch-off");
    expect(blockedBy(owedGuide, { ...worn, layerOpen: true })).toBe("layer-open");
  });
});

describe("the queue of what could not be sent", () => {
  const store = new Map<string, string>();
  // The page is stubbed here and given back as it was: a later test file must find no window left behind (the rows of
  // «Más» read window.location when there is a window at all).
  const scope = globalThis as { window?: unknown };
  const realWindow = scope.window;
  afterAll(() => {
    if (realWindow === undefined) delete scope.window;
    else scope.window = realWindow;
  });
  beforeEach(() => {
    store.clear();
    Object.assign(globalThis, {
      window: {
        localStorage: {
          getItem: (k: string) => store.get(k) ?? null,
          setItem: (k: string, v: string) => void store.set(k, v),
          removeItem: (k: string) => void store.delete(k),
        },
      },
    });
  });
  const body = (status: GuideIn["status"], step = 0): GuideIn => ({ version: 1, status, step });

  const A = 11;
  const B = 12;

  test("keeps the last thing per guide and forgets what was sent", () => {
    enqueue(A, "general", body("in_progress", 1));
    enqueue(A, "general", body("completed", 5));
    enqueue(A, "picks", body("skipped", 0));
    expect(readQueue(A).general).toEqual(body("completed", 5));
    dequeue(A, "general");
    expect(Object.keys(readQueue(A))).toEqual(["picks"]);
    dequeue(A, "picks");
    expect(store.size).toBe(0);
  });

  test("each account has its own queue: what one reader left is never another's (UX-070)", async () => {
    enqueue(A, "odds", body("skipped", 0));
    enqueue(A, "profile", body("completed", 5));
    expect(readQueue(B)).toEqual({});
    const sent: string[] = [];
    await flush(B, (guide) => {
      sent.push(guide);
      return Promise.resolve();
    });
    expect(sent).toEqual([]);
    expect(Object.keys(readQueue(A)).sort()).toEqual(["odds", "profile"]);
  });

  test("the device-wide queue of before, whose owner is unknown, is dropped and never sent", () => {
    store.set("predigol.guides.queue.v1", JSON.stringify({ profile: body("completed", 5) }));
    expect(readQueue(A)).toEqual({});
    dropLegacy();
    expect(store.has("predigol.guides.queue.v1")).toBe(false);
  });

  test("flush sends each guide once and stops at the first that fails, keeping the rest", async () => {
    enqueue(A, "general", body("completed", 5));
    enqueue(A, "picks", body("skipped", 0));
    const sent: string[] = [];
    await flush(A, (guide) => {
      if (guide === "picks") return Promise.reject(new Error("offline"));
      sent.push(guide);
      return Promise.resolve();
    });
    expect(sent).toEqual(["general"]);
    expect(Object.keys(readQueue(A))).toEqual(["picks"]);
  });

  test("a write the API turned down for good is dropped; a lost connection or an ended session waits", async () => {
    const error = (status: number) => Object.assign(new Error(String(status)), { status });
    expect(refused(error(422))).toBe(true);
    expect(refused(error(409))).toBe(true);
    for (const status of [0, 401, 403, 408, 429, 500, 503])
      expect(refused(error(status))).toBe(false);
    expect(refused(new Error("offline"))).toBe(false);
    enqueue(A, "general", body("completed", 5));
    enqueue(A, "picks", body("skipped", 0));
    const sent: string[] = [];
    await flush(A, (guide) => {
      if (guide === "general") return Promise.reject(error(422));
      sent.push(guide);
      return Promise.resolve();
    });
    expect(sent).toEqual(["picks"]);
    expect(readQueue(A)).toEqual({});
  });

  test("a damaged or missing storage is an empty queue, never an error", () => {
    store.set("predigol.guides.queue.v2:11", "{not json");
    expect(readQueue(A)).toEqual({});
    store.set("predigol.guides.queue.v2:11", "[1,2]");
    expect(readQueue(A)).toEqual({});
    Object.assign(globalThis, { window: {} });
    expect(readQueue(A)).toEqual({});
    expect(() => enqueue(A, "general", body("pending"))).not.toThrow();
    expect(() => dropLegacy()).not.toThrow();
  });
});

describe("the page's copy of the server's rules", () => {
  const T0 = "2026-11-07T10:00:00.000Z";
  const T1 = "2026-11-07T10:05:00.000Z";
  const state = (over: Partial<GuideState> = {}): GuideState => ({
    guide: "general",
    version: 1,
    status: "in_progress",
    step: 2,
    first_seen_at: T0,
    started_at: T0,
    completed_at: null,
    skipped_at: null,
    ...over,
  });

  test("a first write opens the row; a status going forward keeps the first moments", () => {
    const first = applied(undefined, "general", { version: 1, status: "pending", step: 0 }, T0);
    expect(first).toMatchObject({ status: "pending", started_at: null, first_seen_at: T0 });
    const done = applied(state(), "general", { version: 1, status: "completed", step: 5 }, T1);
    expect(done).toMatchObject({ status: "completed", started_at: T0, completed_at: T1 });
  });

  test("within a version the status never goes down and a repeat keeps its first moment", () => {
    const completed = state({ status: "completed", completed_at: T0, step: 5 });
    expect(applied(completed, "general", { version: 1, status: "skipped", step: 1 }, T1)).toBe(
      completed,
    );
    expect(applied(completed, "general", { version: 1, status: "completed", step: 5 }, T1)).toBe(
      completed,
    );
  });

  test("a lower version changes nothing and a higher one starts over", () => {
    const now = state({ version: 2 });
    expect(applied(now, "general", { version: 1, status: "completed", step: 5 }, T1)).toBe(now);
    const over = applied(
      state({ status: "completed", completed_at: T0 }),
      "general",
      { version: 2, status: "in_progress", step: 0 },
      T1,
    );
    expect(over).toMatchObject({
      version: 2,
      status: "in_progress",
      completed_at: null,
      started_at: T1,
      first_seen_at: T0,
    });
  });

  test("withGuide puts one guide's state in the account, replacing its earlier one", () => {
    const me = { guides: [state({ guide: "picks" }), state()] } as unknown as Me;
    const out = withGuide(me, state({ status: "completed" }));
    expect(out.guides).toHaveLength(2);
    expect(seenOf(out, "general")?.status).toBe("completed");
    expect(seenOf(out, "picks")?.status).toBe("in_progress");
    expect(seenOf(undefined, "general")).toBeUndefined();
  });
});

describe("the guides of the screens", () => {
  const screens = GUIDE_LIST.filter(
    (g) => g.key !== "general" && g.key !== "profile" && launchable(g),
  );

  test("seven screens and Inicio are built, each with two or three steps", () => {
    expect(screens.map((g) => g.key)).toEqual([
      "home",
      "matches",
      "live",
      "match",
      "picks",
      "parlays",
      "odds",
      "my_picks",
    ]);
    for (const g of screens) {
      expect(g.steps.length).toBeGreaterThanOrEqual(2);
      expect(g.steps.length).toBeLessThanOrEqual(3);
      expect(g.welcome).toBe(false);
    }
  });

  test("each links its last step to a card of «Cómo funciona» that exists", () => {
    for (const g of screens) expect(HOW_CARD_IDS).toContain(g.more as never);
  });

  test("every anchor a step rests on is drawn by the code (data-guide) on some screen", () => {
    const src = (file: string) => readFileSync(join(import.meta.dir, "..", file), "utf8");
    const code = [
      "home/TodayBlocks.tsx",
      "home/ParaTi.tsx",
      "home/ResultsBlock.tsx",
      "matches/Filters.tsx",
      "matches/MatchesPage.tsx",
      "live/LivePage.tsx",
      "match/MatchHeader.tsx",
      "match/MatchPage.tsx",
      "match/ForecastBlock.tsx",
      "picks/PicksPage.tsx",
      "parlays/Builder.tsx",
      "parlays/ParlaysPage.tsx",
      "records/ParlayRecordCard.tsx",
      "odds/OddsPage.tsx",
      "odds/explorer/Navigation.tsx",
      "odds/explorer/OddsExplorer.tsx",
      "records/MyPicksPage.tsx",
      "../components/layout/Bars.tsx",
      "../components/layout/MoreSheet.tsx",
    ]
      .map(src)
      .join("\n");
    // the blocks of Perfil carry data-guide={`profile-${id}`}, one per block
    expect(src("profile/Block.tsx")).toContain("data-guide={`profile-${id}`}");
    const dynamic = ["layer-for-you", "layer-predigol", "nav-home", "nav-matches", "nav-picks"];
    for (const g of GUIDE_LIST.filter(launchable))
      for (const step of g.steps)
        for (const anchor of step.anchors) {
          if (dynamic.includes(anchor) || /^(nav|profile)-/.test(anchor)) continue;
          expect(code, `${g.key}/${step.id}: ${anchor}`).toContain(`data-guide="${anchor}"`);
        }
  });
});

describe("the guide of Perfil", () => {
  const all: ProfileFacts = {
    digest: true,
    device: true,
    whatsapp: true,
    membership: true,
    desk: false,
  };
  const none: ProfileFacts = {
    digest: false,
    device: false,
    whatsapp: false,
    membership: false,
    desk: true,
  };

  test("six steps, owed, with no welcome, on the page's blocks", () => {
    const g = GUIDES.profile;
    expect(g.mandatory).toBe(true);
    expect(g.welcome).toBe(false);
    expect(g.steps.map((s) => s.id)).toEqual([...PROFILE_STEPS]);
    expect(stepCount(g)).toBe(6);
    expect(g.steps.flatMap((s) => s.anchors).every((a) => a.startsWith("profile-"))).toBe(true);
  });

  test("it asks for no «¿Seguimos?» and cannot be skipped, only paused", () => {
    const g = GUIDES.profile;
    expect(owed(g, { status: "in_progress", step: 3, version: 1 })).toBe("resume");
    expect(blockedBy(g, { ...FREE, consentsDue: true })).toBe("consents-due");
    expect(blockedBy(g, { ...FREE, auto: false, skipsInARow: 5 })).toBeNull();
  });

  test("the words are built from what exists for the account, never naming what is off", () => {
    expect(profileParts("notifications", none)).toEqual(["guides.profile.notifications.body"]);
    expect(profileParts("notifications", all)).toEqual([
      "guides.profile.notifications.body",
      "guides.profile.notifications.digest",
      "guides.profile.notifications.device",
    ]);
    expect(profileParts("last", none)).toEqual(["guides.profile.last.help"]);
    expect(profileParts("last", all)).toEqual([
      "guides.profile.last.membership",
      "guides.profile.last.help",
      "guides.profile.last.whatsapp",
    ]);
    expect(profileParts("account", all)).toContain("guides.profile.account.tap");
    expect(profileParts("account", none)).not.toContain("guides.profile.account.tap");
    expect(profileTitle("last", { membership: false })).toBe("guides.profile.last.titleHelp");
    expect(profileTitle("last", { membership: true })).toBe("guides.profile.last.title");
  });

  test("every part of every step exists in both languages and stays short", () => {
    for (const lang of ["es", "en"] as const) {
      setLocale(lang);
      for (const step of PROFILE_STEPS) {
        for (const key of profileParts(step, all)) {
          const text = translate(key);
          expect(text, `${lang} ${key}`).not.toBe(key);
          expect(text.length, `${lang} ${key}`).toBeLessThanOrEqual(190);
        }
        expect(translate(profileTitle(step, none))).not.toContain("guides.profile");
      }
    }
    setLocale("es");
  });
});

describe("the walk through the cards", () => {
  const def = GUIDES.general;

  test("the welcome is the card 0 and the steps follow", () => {
    expect(cardsOf(def)).toHaveLength(6);
    expect(cardsOf(def)[0]?.id).toBe("welcome");
  });

  test("with every element on the screen, the cards go one by one and the last has no next", () => {
    expect(neighbour(def, 0, 1, everywhere)).toBe(1);
    expect(neighbour(def, 4, 1, everywhere)).toBe(5);
    expect(neighbour(def, 5, 1, everywhere)).toBeNull();
    expect(neighbour(def, 1, -1, everywhere)).toBe(0);
    expect(neighbour(def, 0, -1, everywhere)).toBeNull();
    expect(numbered(def, everywhere)).toEqual([1, 2, 3, 4, 5]);
  });

  test("a step whose element is not there is left out, going forward or back", () => {
    const find = (anchors: readonly string[]) => (anchors.includes("nav-picks") ? null : there());
    expect(neighbour(def, 2, 1, find)).toBe(4);
    expect(neighbour(def, 4, -1, find)).toBe(2);
    expect(numbered(def, find)).toEqual([1, 2, 4, 5]);
  });

  test("firstFrom answers the card itself when it can be shown, else the next one, else null", () => {
    expect(firstFrom(def, 2, everywhere)).toBe(2);
    expect(firstFrom(def, 0, nowhere)).toBe(0); // the welcome needs no element
    expect(firstFrom(def, 1, nowhere)).toBeNull();
  });

  test("a card without anchors always can be shown", () => {
    expect(resolvable({ id: "welcome", anchors: [] }, nowhere)).toBe(true);
    expect(resolvable({ id: "x", anchors: ["a"] }, nowhere)).toBe(false);
  });
});

describe("another layer over the page", () => {
  type Fake = { getAttribute: (name: string) => string | null; firstElementChild: Fake | null };
  const el = (state: string | null, child: Fake | null = null): Fake => ({
    getAttribute: (name) => (name === "data-state" ? state : null),
    firstElementChild: child,
  });
  const page = (...layers: Fake[]) => ({ querySelectorAll: () => layers }) as unknown as ParentNode;

  test("an open sheet, dialog or menu holds the guide back", () => {
    expect(anotherLayerOpen(page(el("open")))).toBe(true);
    expect(anotherLayerOpen(page(el(null, el("open"))))).toBe(true);
    expect(anotherLayerOpen(page(el(null)))).toBe(true);
  });

  test("a layer that is closing does not: «Más» stays in the page for its exit while the next screen is there (UX-070)", () => {
    expect(anotherLayerOpen(page())).toBe(false);
    expect(anotherLayerOpen(page(el("closed")))).toBe(false);
    // the menu's popper wrapper carries no state of its own: its content does
    expect(anotherLayerOpen(page(el(null, el("closed"))))).toBe(false);
    expect(anotherLayerOpen(page(el("closed"), el("open")))).toBe(true);
  });
});

describe("where the card goes", () => {
  const view = { width: 1280, height: 800 };
  const card = { width: 416, height: 180 };

  test("below the element when there is room, with the card's left edge on the element's", () => {
    const at = placeCard({ top: 20, left: 100, width: 80, height: 32 }, card, view);
    expect(at).toEqual({ top: 64, left: 100 });
  });

  test("above it when there is no room below", () => {
    const at = placeCard({ top: 700, left: 100, width: 80, height: 32 }, card, view);
    expect(at.top).toBe(700 - 12 - card.height);
  });

  test("never leaves the viewport, and without an element it is centred", () => {
    const edge = placeCard({ top: 20, left: 1250, width: 30, height: 30 }, card, view);
    expect(edge.left + card.width).toBeLessThanOrEqual(view.width - 12);
    const mid = placeCard(null, card, view);
    expect(mid).toEqual({ top: 310, left: 432 });
    const tiny = placeCard(null, card, { width: 200, height: 100 });
    expect(tiny.left).toBeGreaterThanOrEqual(12);
    expect(tiny.top).toBeGreaterThanOrEqual(12);
  });
});

describe("the texts", () => {
  type Cards = Record<string, { title: string; body: string }>;
  const BUILT = GUIDE_LIST.filter(launchable).map((g) => g.key);

  test("both languages carry the same keys, in every namespace", () => {
    const keys = (o: unknown, prefix = ""): string[] =>
      Object.entries(o as Record<string, unknown>).flatMap(([k, v]) =>
        typeof v === "object" && v !== null ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`],
      );
    expect(keys(enGuides).sort()).toEqual(keys(esGuides).sort());
  });

  test("every card of every built guide has a title and a short body in both languages", () => {
    for (const lang of [esGuides, enGuides]) {
      for (const key of BUILT) {
        const texts = (lang as unknown as Record<string, Cards>)[key] ?? {};
        for (const card of cardsOf(GUIDES[key])) {
          const id = card.id;
          const entry = texts[id];
          expect(entry, `${key}.${id}`).toBeDefined();
          if (!entry) continue;
          expect(entry.title.length).toBeGreaterThan(0);
          // a card is read on a phone at 320 px: one or two short sentences
          if ("body" in entry) expect(entry.body.length).toBeLessThanOrEqual(180);
        }
      }
    }
  });

  test("the welcome says how many steps there are, as many as the guide has", () => {
    const n = String(GUIDES.general.steps.length);
    expect(esGuides.general.welcome.start).toContain(n);
    expect(enGuides.general.welcome.start).toContain(n);
  });

  test("a built guide is named for Ayuda, in both languages", () => {
    for (const def of GUIDE_LIST.filter(launchable)) {
      expect((esGuides.names as Record<string, string>)[def.key]).toBeTruthy();
      expect((enGuides.names as Record<string, string>)[def.key]).toBeTruthy();
    }
  });
});
