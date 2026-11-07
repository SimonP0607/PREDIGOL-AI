/**
 * Product analytics (plan UX, A6 and section 39): the closed catalog of 40 events - the same as the backend's
 * (backend/src/fbi/customer/events_catalog.json; a test checks the parity) - and track(), which queues an event and
 * sends the queue in the background: every few seconds, at 20 events, and when the page is hidden. It never blocks
 * the interface, never retries, and an answer that is not 200 empties the queue. A property is an enumeration, a
 * bounded integer, a boolean, a slug or an id: never free text, an address or a form's content. The server decides
 * whether anything is recorded (FBI_PRODUCT_EVENTS, the reader's consent, the owner and the robot never).
 */
import { DATA_MODE } from "@/lib/api/mode";

type PropKind =
  | { readonly enum: readonly string[] }
  | { readonly int: readonly [number, number] }
  | { readonly bool: true }
  | { readonly slug: true }
  | { readonly id: true };

interface EventSpec {
  readonly group: string;
  readonly source: "web" | "server";
  readonly props: Readonly<Record<string, PropKind>>;
}

export const EVENTS = {
  account_activated: { group: "entry", source: "server", props: {} },
  onboarding_started: { group: "entry", source: "web", props: {} },
  onboarding_completed: { group: "entry", source: "web", props: { skipped: { int: [0, 20] } } },
  onboarding_step_skipped: { group: "entry", source: "web", props: { step: { slug: true } } },
  guide_started: {
    group: "entry",
    source: "web",
    props: {
      guide: {
        enum: [
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
        ],
      },
      version: { int: [1, 99] },
      trigger: { enum: ["auto", "replay", "resume"] },
    },
  },
  guide_completed: {
    group: "entry",
    source: "web",
    props: {
      guide: {
        enum: [
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
        ],
      },
      version: { int: [1, 99] },
    },
  },
  guide_skipped: {
    group: "entry",
    source: "web",
    props: {
      guide: {
        enum: [
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
        ],
      },
      version: { int: [1, 99] },
      step: { int: [0, 9] },
      method: { enum: ["button", "escape", "navigate"] },
    },
  },
  guide_paused: {
    group: "entry",
    source: "web",
    props: {
      guide: {
        enum: [
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
        ],
      },
      version: { int: [1, 99] },
      step: { int: [0, 9] },
    },
  },
  favorite_added: {
    group: "entry",
    source: "web",
    props: {
      kind: { enum: ["team", "competition", "player", "market"] },
      id: { id: true },
      market: { enum: ["1X2", "OU", "BTTS", "AH", "DC"] },
    },
  },
  favorite_removed: {
    group: "entry",
    source: "web",
    props: {
      kind: { enum: ["team", "competition", "player", "market"] },
      id: { id: true },
      market: { enum: ["1X2", "OU", "BTTS", "AH", "DC"] },
    },
  },
  session_started: {
    group: "use",
    source: "web",
    props: {
      device: { enum: ["phone", "tablet", "desktop"] },
      width: { int: [0, 10000] },
      client: { enum: ["pwa", "browser"] },
      lang: { enum: ["es", "en"] },
    },
  },
  screen_viewed: {
    group: "use",
    source: "web",
    props: {
      screen: {
        enum: [
          "home",
          "matches",
          "match",
          "live",
          "picks",
          "my_picks",
          "parlays",
          "odds",
          "updates",
          "transparency",
          "profile",
          "help",
          "legal",
          "welcome",
          "other",
        ],
      },
    },
  },
  match_opened: {
    group: "use",
    source: "web",
    props: {
      origin: {
        enum: [
          "home",
          "matches",
          "live",
          "picks",
          "my_picks",
          "parlays",
          "team_filter",
          "notification",
          "search",
          "direct",
          "other",
        ],
      },
      match_id: { id: true },
    },
  },
  match_section_opened: {
    group: "use",
    source: "web",
    props: { section: { slug: true }, match_id: { id: true } },
  },
  market_viewed: {
    group: "use",
    source: "web",
    props: { market: { slug: true }, match_id: { id: true } },
  },
  forecast_viewed: { group: "use", source: "web", props: { match_id: { id: true } } },
  term_explained: { group: "use", source: "web", props: { term: { slug: true } } },
  explain_opened: { group: "use", source: "web", props: { what: { slug: true } } },
  pick_opened: { group: "picks", source: "web", props: { pick_id: { id: true } } },
  pick_explanation_opened: { group: "picks", source: "web", props: { pick_id: { id: true } } },
  pick_saved: {
    group: "picks",
    source: "web",
    props: {
      origin: { enum: ["pick", "market", "odds", "other"] },
      market: { enum: ["1X2", "OU", "BTTS", "AH", "DC"] },
    },
  },
  pick_removed: { group: "picks", source: "web", props: {} },
  own_selection_saved: { group: "picks", source: "web", props: { market: { slug: true } } },
  slip_leg_added: {
    group: "parlays",
    source: "web",
    props: { legs: { int: [1, 30] }, market: { enum: ["1X2", "OU", "BTTS", "AH", "DC"] } },
  },
  parlay_created: { group: "parlays", source: "web", props: { legs: { int: [1, 30] } } },
  builder_run: { group: "parlays", source: "web", props: { legs: { int: [0, 30] } } },
  news_opened: { group: "news", source: "web", props: { match_id: { id: true } } },
  news_link_clicked: { group: "news", source: "web", props: {} },
  notification_enabled: {
    group: "notices",
    source: "web",
    props: {
      channel: { enum: ["email", "push"] },
      category: {
        enum: [
          "account",
          "security",
          "membership",
          "support",
          "service",
          "privacy",
          "legal",
          "match",
          "result",
          "lineup",
          "digest",
          "reminder",
          "device",
        ],
      },
    },
  },
  notification_opened: {
    group: "notices",
    source: "web",
    props: {
      category: {
        enum: [
          "account",
          "security",
          "membership",
          "support",
          "service",
          "privacy",
          "legal",
          "match",
          "result",
          "lineup",
          "digest",
          "reminder",
          "device",
        ],
      },
    },
  },
  notification_disabled: {
    group: "notices",
    source: "web",
    props: {
      channel: { enum: ["email", "push"] },
      category: {
        enum: [
          "account",
          "security",
          "membership",
          "support",
          "service",
          "privacy",
          "legal",
          "match",
          "result",
          "lineup",
          "digest",
          "reminder",
          "device",
        ],
      },
    },
  },
  pwa_installed: { group: "notices", source: "web", props: {} },
  ticket_created: { group: "support", source: "server", props: { kind: { slug: true } } },
  feedback_submitted: { group: "support", source: "web", props: { score: { int: [1, 5] } } },
  analysis_helpful_voted: { group: "support", source: "web", props: { helpful: { bool: true } } },
  trial_started: { group: "membership", source: "server", props: {} },
  membership_renewed: { group: "membership", source: "server", props: {} },
  membership_expired: { group: "membership", source: "server", props: {} },
  error_shown: {
    group: "other",
    source: "web",
    props: { code: { slug: true }, status: { int: [0, 599] } },
  },
  search_submitted: { group: "other", source: "web", props: { results: { int: [0, 1000] } } },
} as const satisfies Record<string, EventSpec>;

type Catalog = typeof EVENTS;
/** The events the browser sends (the server records the others: activation, membership, tickets). */
export type WebEvent = {
  [K in keyof Catalog]: Catalog[K]["source"] extends "web" ? K : never;
}[keyof Catalog];
type ValueOf<P> = P extends { enum: readonly (infer E)[] }
  ? E
  : P extends { bool: true }
    ? boolean
    : P extends { slug: true }
      ? string
      : number;
export type PropsOf<K extends WebEvent> = {
  [P in keyof Catalog[K]["props"]]?: ValueOf<Catalog[K]["props"][P]>;
};

const SLUG = /^[A-Za-z0-9_.+-]{1,40}$/;
const MAX_ID = Number.MAX_SAFE_INTEGER;
const BATCH = 20;
const FLUSH_MS = 4000;

/** The properties as the catalog allows them, or null: an event the server would refuse is never sent. */
export function validEvent(
  name: string,
  props: Record<string, unknown> = {},
): Record<string, unknown> | null {
  const spec = (EVENTS as Readonly<Record<string, EventSpec>>)[name];
  if (!spec || spec.source !== "web") return null;
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined) continue;
    const kind = spec.props[key];
    if (!kind) return null;
    const ok =
      ("enum" in kind && typeof value === "string" && kind.enum.includes(value)) ||
      ("int" in kind &&
        Number.isInteger(value) &&
        (value as number) >= kind.int[0] &&
        (value as number) <= kind.int[1]) ||
      ("bool" in kind && typeof value === "boolean") ||
      ("slug" in kind && typeof value === "string" && SLUG.test(value)) ||
      ("id" in kind &&
        Number.isInteger(value) &&
        (value as number) > 0 &&
        (value as number) <= MAX_ID);
    if (!ok) return null;
    clean[key] = value;
  }
  return clean;
}

interface Queued {
  name: string;
  props: Record<string, unknown>;
}
const queue: Queued[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let listening = false;

function send(batch: Queued[], keepalive: boolean): void {
  void fetch(`${window.location.origin}/api/v1/events`, {
    method: "POST",
    credentials: "same-origin",
    keepalive,
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      "x-requested-with": "predigol",
    },
    body: JSON.stringify({ events: batch }),
  })
    .then((res) => {
      // signed out, the consent gate, the limit: what is queued is dropped, never retried
      if (!res.ok) queue.length = 0;
    })
    .catch(() => {
      queue.length = 0;
    });
}

/** Send what is queued now. */
export function flushEvents(keepalive = false): void {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
  while (queue.length > 0) send(queue.splice(0, BATCH), keepalive);
}

function listen(): void {
  if (listening) return;
  listening = true;
  window.addEventListener("pagehide", () => flushEvents(true));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushEvents(true);
  });
}

/** Queue a product event. Never throws, never waits. */
export function track<K extends WebEvent>(name: K, props?: PropsOf<K>): void {
  if (typeof window === "undefined" || DATA_MODE === "mock") return;
  const clean = validEvent(name, (props ?? {}) as Record<string, unknown>);
  if (clean === null) return;
  listen();
  queue.push({ name, props: clean });
  if (queue.length >= BATCH) flushEvents();
  else timer ??= setTimeout(() => flushEvents(), FLUSH_MS);
}

/** Where the reader came from, for match_opened: the last page they were on in this tab. */
let previousPath: string | null = null;
let currentPath: string | null = null;

export function noteLocation(pathname: string): void {
  if (pathname === currentPath) return;
  previousPath = currentPath;
  currentPath = pathname;
}

export type Origin = PropsOf<"match_opened">["origin"];

/** The page a tapped notice opened (plan UX, B7: sw.js marks it ?notice=…): its match_opened comes from the notice. */
const FROM_NOTICE = "\u0000notice";

export function noteNoticeLanding(): void {
  previousPath = FROM_NOTICE;
}

export function originOf(path: string | null = previousPath): NonNullable<Origin> {
  if (path === null) return "direct";
  if (path === FROM_NOTICE) return "notification";
  if (path === "/home" || path === "/") return "home";
  if (path === "/matches") return "matches";
  if (path === "/live") return "live";
  if (path === "/picks") return "picks";
  if (path === "/my-picks") return "my_picks";
  if (path === "/parlays") return "parlays";
  return "other";
}

export type Screen = NonNullable<PropsOf<"screen_viewed">["screen"]>;

/**
 * The kind of screen a path is (closing plan 3.3), for screen_viewed: a group from a closed list - never the address, a
 * search, a match or a pick. Only the first segment of the path is read; anything unknown is «other».
 */
export function screenOf(pathname: string): Screen {
  const [first = "", second] = (pathname.split(/[?#]/, 1)[0] ?? "").split("/").filter(Boolean);
  switch (first) {
    case "":
    case "home":
      return "home";
    case "matches":
      return second === undefined ? "matches" : "match";
    case "live":
    case "picks":
    case "parlays":
    case "odds":
    case "updates":
    case "transparency":
    case "profile":
    case "help":
    case "legal":
    case "welcome":
      return first;
    case "my-picks":
      return "my_picks";
    default:
      return "other";
  }
}

/** The device class from the width: the tablet trigger of block C (C5) reads it. */
export function deviceOf(width: number): "phone" | "tablet" | "desktop" {
  if (width < 768) return "phone";
  return width <= 1024 ? "tablet" : "desktop";
}

const SESSION_KEY = "predigol.session_started";

/** session_started, once per tab and signed-in reader: the device class, the width, PWA or browser, the language. */
export function startSession(lang: "es" | "en"): void {
  if (typeof window === "undefined") return;
  try {
    if (window.sessionStorage.getItem(SESSION_KEY)) return;
    window.sessionStorage.setItem(SESSION_KEY, "1");
  } catch {
    // no storage (a private window that refuses it): one event per page load is still an answer
  }
  const width = Math.max(0, Math.min(10_000, Math.round(window.innerWidth)));
  const standalone =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(display-mode: standalone)").matches;
  track("session_started", {
    device: deviceOf(width),
    width,
    client: standalone ? "pwa" : "browser",
    lang,
  });
}
