/**
 * The guides (plan UX-051 to UX-054; PLAN_BIENVENIDA_RECORRIDO): one registry for the optional welcome tour, the optional
 * first-visit guide of each screen and the first guide of Perfil. Each guide has a key of the closed list (the same the API
 * keeps: types_guides.ts), two numbers - `version`, which goes up with any change of text or steps, and `reshowFrom`, which goes up
 * only with a change large enough to show it once more to whoever saw an earlier version - whether it is owed, the screen it
 * belongs to and its steps.
 *
 * A step rests on the first visible element carrying one of its `anchors` (`data-guide="…"`), in the order given: the first is
 * the element, the next ones its alternatives. A step whose anchors are all missing is left out - a guide never breaks a screen.
 * A step without anchors is a card of its own (the welcome). The texts are in the catalog (locales/{es,en}/guides.json) under
 * `guides.<key>.<step>.title|body`.
 */
import type { GuideKey } from "@/lib/api/v1/types_guides";

export interface StepDef {
  /** Names the texts: guides.<key>.<id>.title and .body. */
  readonly id: string;
  /** `data-guide` values, the element first and then its alternatives; none: a card on its own. */
  readonly anchors: readonly string[];
}

export interface GuideDef {
  readonly key: GuideKey;
  readonly version: number;
  /** Whoever saw an earlier version than this sees the guide once more. */
  readonly reshowFrom: number;
  /** Owed once (Perfil): no «Saltar», and Escape pauses it. */
  readonly mandatory: boolean;
  /** The screen it opens on, as `screenOf` names it; where «Ver» takes the reader. */
  readonly screen: string;
  readonly path: string;
  /** The guide that covers this one: finishing that one counts this one as seen (Inicio is covered by the general tour). */
  readonly coveredBy?: GuideKey;
  /** Opens with a card of its own (a welcome) before the numbered steps. */
  readonly welcome: boolean;
  readonly steps: readonly StepDef[];
}

const none = (
  key: GuideKey,
  screen: string,
  path: string,
  extra: Partial<GuideDef> = {},
): GuideDef => ({
  key,
  version: 1,
  reshowFrom: 1,
  mandatory: false,
  screen,
  path,
  welcome: false,
  steps: [],
  ...extra,
});

export const GUIDES: Readonly<Record<GuideKey, GuideDef>> = {
  general: {
    key: "general",
    version: 1,
    reshowFrom: 1,
    mandatory: false,
    screen: "home",
    path: "/home",
    welcome: true,
    steps: [
      { id: "home", anchors: ["layer-for-you", "layer-predigol", "nav-home"] },
      { id: "matches", anchors: ["nav-matches"] },
      { id: "picks", anchors: ["nav-picks"] },
      { id: "myPicks", anchors: ["nav-my-picks"] },
      { id: "more", anchors: ["nav-more"] },
    ],
  },
  home: none("home", "home", "/home", { coveredBy: "general" }),
  matches: none("matches", "matches", "/matches"),
  live: none("live", "live", "/live"),
  match: none("match", "match", "/matches"),
  picks: none("picks", "picks", "/picks"),
  parlays: none("parlays", "parlays", "/parlays"),
  odds: none("odds", "odds", "/odds"),
  my_picks: none("my_picks", "my_picks", "/my-picks"),
  profile: none("profile", "profile", "/profile", { mandatory: true }),
};

/** The guides in the order the API keeps them. */
export const GUIDE_LIST: readonly GuideDef[] = Object.values(GUIDES);

/** A guide with steps is one the reader can be shown; the others are not built yet. */
export function launchable(def: GuideDef): boolean {
  return def.steps.length > 0;
}

/** The numbered steps of a guide: the welcome card, when it has one, is the step 0 the API records. */
export function stepCount(def: GuideDef): number {
  return def.steps.length + (def.welcome ? 1 : 0);
}

/** The guide that opens on a screen, when there is one the reader can be shown. */
export function guideOfScreen(screen: string): GuideDef | null {
  return GUIDE_LIST.find((g) => g.screen === screen && launchable(g)) ?? null;
}
