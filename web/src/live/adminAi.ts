/**
 * Plan F13 (section 16): the pages of the Admin Console that talked about the AI - PrediGol Intelligence, the AI decision layer, AI and research,
 * Evolución - and Memoria, which F8 had already gathered, are two now: OPERACIÓN (what happens each day, what was decided and what it costs) and
 * APRENDIZAJE (what is learned, remembered, tried and measured). Every view they had is a tab of one of the two; this file says which, so that the
 * old addresses keep opening what they opened (a bookmark of /admin/ai-layer#tab=costs lands on the costs of Operación) and a test can check that
 * no tab was left without a home.
 *
 * The tabs of a page live in the address (`#tab=costs`); a tab that holds views of its own keeps the chosen one in `view`
 * (`#tab=ai&view=reviews`). The first tab, and the first view of a tab, leave the address clean (see useUrlTab).
 */
import { tabFromHash } from "@/lib/useUrlTab";

/** OPERACIÓN: the day of PrediGol Intelligence, its decisions, the dossier of a match, the work of the AI, what it costs, and what ran. */
export const OPERATION_TABS = ["day", "decisions", "match", "ai", "costs", "runs"] as const;
/** The views of the "ai" tab of Operación: the analysis of each match, the research, the reviews of the picks, the evidence and the sources. */
export const AI_VIEWS = ["today", "research", "reviews", "evidence", "sources"] as const;
/** APRENDIZAJE: the close of the day, what was learned, the post-mortems, the memory, the experiments and promotions, the calibration, the markets and the AI against the model. */
export const LEARNING_TABS = [
  "close",
  "learned",
  "postmortems",
  "memory",
  "experiments",
  "calibration",
  "markets",
  "shadow",
] as const;
/** The views of the "memory" tab of Aprendizaje: the entities over time, the matches, the notes of the learning cycle and the research findings. */
export const MEMORY_VIEWS = ["entities", "matches", "notes", "findings"] as const;

export type OperationTab = (typeof OPERATION_TABS)[number];
export type AiView = (typeof AI_VIEWS)[number];
export type LearningTab = (typeof LEARNING_TABS)[number];
export type MemoryView = (typeof MEMORY_VIEWS)[number];

export const OPERATION_PATH = "/admin/operation" as const;
export const LEARNING_PATH = "/admin/learning" as const;
export type AdminAiPath = typeof OPERATION_PATH | typeof LEARNING_PATH;

/** The query parameter of the views inside a tab (the tab itself is `tab`). */
export const VIEW_PARAM = "view";

/** The views a tab holds, or none. */
const VIEWS: Record<AdminAiPath, Record<string, readonly string[]>> = {
  [OPERATION_PATH]: { ai: AI_VIEWS },
  [LEARNING_PATH]: { memory: MEMORY_VIEWS },
};
const TABS: Record<AdminAiPath, readonly string[]> = {
  [OPERATION_PATH]: OPERATION_TABS,
  [LEARNING_PATH]: LEARNING_TABS,
};

/** A place in one of the two pages. */
export interface Place {
  path: AdminAiPath;
  tab: string;
  view?: string;
}

/** The address of a place: its path and its hash (without the `#`), the first tab and the first view left out as the pages themselves leave them. */
export function addressOf(place: Place): { to: AdminAiPath; hash: string } {
  const params = new URLSearchParams();
  const tabs = TABS[place.path];
  if (place.tab !== tabs[0]) params.set("tab", place.tab);
  const views = VIEWS[place.path][place.tab];
  if (place.view !== undefined && views && place.view !== views[0])
    params.set(VIEW_PARAM, place.view);
  return { to: place.path, hash: params.toString() };
}

/** True when `place` names a tab of its page, and a view the tab holds (or no view, for a tab that holds none). */
export function isPlace(place: Place): boolean {
  if (!TABS[place.path].includes(place.tab)) return false;
  const views = VIEWS[place.path][place.tab];
  if (place.view === undefined) return true;
  return views !== undefined && views.includes(place.view);
}

export const LEGACY_PAGES = [
  "intelligence",
  "ai-layer",
  "ai-analyst",
  "evolution",
  "memory",
] as const;
export type LegacyPage = (typeof LEGACY_PAGES)[number];

/** The tabs each of the old pages had, as the addresses people kept name them. Evolución had none: it was one long page. */
export const LEGACY_TABS: Record<LegacyPage, readonly string[]> = {
  intelligence: ["day", "decisions", "match", "calibration", "markets", "costs"],
  "ai-layer": ["reviews", "evidence", "costs", "shadow"],
  "ai-analyst": ["today", "close", "research", "learning", "sources", "costs"],
  evolution: [],
  memory: ["entities", "matches", "postmortems", "events", "research"],
};

const op = (tab: OperationTab, view?: AiView): Place =>
  view ? { path: OPERATION_PATH, tab, view } : { path: OPERATION_PATH, tab };
const learn = (tab: LearningTab, view?: MemoryView): Place =>
  view ? { path: LEARNING_PATH, tab, view } : { path: LEARNING_PATH, tab };

/**
 * Where each old tab went. The three costs views (PrediGol Intelligence, the decision layer, AI and research) are one now; the learning tab of
 * AI and research (the notes and proposals of a day, read-only) is "Lo aprendido", where the owner also answers the proposals.
 */
const MOVED: Record<LegacyPage, { home: Place; tabs: Record<string, Place> }> = {
  intelligence: {
    home: op("day"),
    tabs: {
      day: op("day"),
      decisions: op("decisions"),
      match: op("match"),
      calibration: learn("calibration"),
      markets: learn("markets"),
      costs: op("costs"),
    },
  },
  "ai-layer": {
    home: op("ai", "reviews"),
    tabs: {
      reviews: op("ai", "reviews"),
      evidence: op("ai", "evidence"),
      costs: op("costs"),
      shadow: learn("shadow"),
    },
  },
  "ai-analyst": {
    home: op("ai", "today"),
    tabs: {
      today: op("ai", "today"),
      close: learn("close"),
      research: op("ai", "research"),
      learning: learn("learned"),
      sources: op("ai", "sources"),
      costs: op("costs"),
    },
  },
  evolution: { home: learn("learned"), tabs: {} },
  memory: {
    home: learn("memory", "entities"),
    tabs: {
      entities: learn("memory", "entities"),
      matches: learn("memory", "matches"),
      postmortems: learn("postmortems"),
      events: learn("memory", "notes"),
      research: learn("memory", "findings"),
    },
  },
};

/** The place an old page, opened with this hash, lives in now: the tab its address named, else the one the page opened on. */
export function legacyPlace(page: LegacyPage, hash: string): Place {
  const moved = MOVED[page];
  const tab = tabFromHash(hash, LEGACY_TABS[page]);
  return (tab !== null ? moved.tabs[tab] : undefined) ?? moved.home;
}

/** The address an old page, opened with this hash, is sent to. */
export function legacyAddress(page: LegacyPage, hash: string): { to: AdminAiPath; hash: string } {
  return addressOf(legacyPlace(page, hash));
}

/** What a tab of the old pages is called now: the whole table, for the tests and for the owner's guide. */
export function legacyMoves(): Array<{ page: LegacyPage; tab: string | null; place: Place }> {
  return LEGACY_PAGES.flatMap((page) => [
    { page, tab: null, place: MOVED[page].home },
    ...Object.entries(MOVED[page].tabs).map(([tab, place]) => ({ page, tab, place })),
  ]);
}

/**
 * A hash that names a tab of the OTHER page of the two - a link to `/admin/operation#tab=calibration`, or a redirect that kept the hash of an
 * old address - is moved to the page that has it. Returns the address to go to, or null when the hash names a tab of this page or none.
 */
export function strayAddress(
  path: AdminAiPath,
  hash: string,
): { to: AdminAiPath; hash: string } | null {
  const other: AdminAiPath = path === OPERATION_PATH ? LEARNING_PATH : OPERATION_PATH;
  if (tabFromHash(hash, TABS[path]) !== null) return null;
  const tab = tabFromHash(hash, TABS[other]);
  if (tab === null) return null;
  const view = tabFromHash(hash, VIEWS[other][tab] ?? [], VIEW_PARAM) ?? undefined;
  const place: Place = view !== undefined ? { path: other, tab, view } : { path: other, tab };
  return addressOf(place);
}
