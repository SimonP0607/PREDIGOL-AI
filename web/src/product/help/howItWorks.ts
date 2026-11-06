/**
 * «Cómo funciona PrediGol» (plan de cierre UX, 1.6): the eleven cards that explain the app - what each part is, how it is
 * read, an example and where to see it. The words live in the catalogue (support.howItWorks.cards.<id>); this file says which
 * cards there are, in what order, where each one leads and which glossary terms it shows under it, so that the welcome, the
 * tour, the help and the empty states can all point to one place instead of repeating the explanation.
 */
import type { TermKey } from "@/lib/glossary";

export const HOW_PATH = "/help/how-it-works";

export const HOW_CARD_IDS = [
  "home",
  "matches",
  "picks",
  "parlays",
  "odds",
  "myPicks",
  "favorites",
  "analysis",
  "probabilities",
  "markets",
  "states",
] as const;

export type HowCardId = (typeof HOW_CARD_IDS)[number];

export interface HowCard {
  id: HowCardId;
  /** «Verlo en la app»: the page that shows it. */
  to: string;
  /** The anchor on that page, when the card leads to a block of it (Perfil → Tu fútbol). */
  hash?: string;
  /** The glossary term the card opens at the foot («Ver en el glosario»). */
  term: TermKey;
  /** The terms shown under the card with their one definition: the markets and the states of a pick. */
  shows?: readonly TermKey[];
}

export const HOW_CARDS: readonly HowCard[] = [
  { id: "home", to: "/home", term: "forecast" },
  { id: "matches", to: "/matches", term: "forecast" },
  { id: "picks", to: "/picks", term: "pick" },
  { id: "parlays", to: "/parlays", term: "parlay" },
  { id: "odds", to: "/odds", term: "bestOdds" },
  { id: "myPicks", to: "/my-picks", term: "settlement" },
  { id: "favorites", to: "/profile", hash: "football", term: "forecast" },
  { id: "analysis", to: "/matches", term: "forecast" },
  { id: "probabilities", to: "/matches", term: "probability" },
  {
    id: "markets",
    to: "/matches",
    term: "market",
    shows: ["market1x2", "overUnder", "btts", "asianHandicap", "doubleChance"],
  },
  {
    id: "states",
    to: "/picks",
    term: "recommended",
    shows: [
      "recommended",
      "pending",
      "inPlay",
      "won",
      "lost",
      "push",
      "halfWon",
      "halfLost",
      "void",
    ],
  },
];

/** The anchor of a card on its page: /help/how-it-works#card-picks. */
export function cardAnchor(id: HowCardId): string {
  return `card-${id}`;
}
