/** What every part of the Match Center receives: the match, its detail and the page state. */
import type {
  DataStatus,
  MarketPriceStatus,
  MarketQuote,
  MatchSummary,
  Section,
  VenueRef,
} from "@/lib/api/v1/types";
import type { MatchCenter } from "@/lib/api/v1/types_center";
import type { Goals, LiveSnapshot, Phase } from "./model";

export const TAB_KEYS = ["summary", "picks", "stats", "markets", "lineups", "advanced"] as const;
export type TabKey = (typeof TAB_KEYS)[number];

/** GET /matches/{id}/center, as loaded: each block renders its own state from it. */
export interface CenterState {
  data: MatchCenter | null;
  loading: boolean;
  error: unknown;
  /** The envelope's status when the API had no detail at all. */
  status: DataStatus | null;
  retry: () => void;
}

export interface MatchCtx {
  fixtureId: string;
  match: MatchSummary;
  venue: VenueRef | null;
  markets: Section<MarketQuote[]>;
  /** Before kick-off: why a core market has no price, and the model's view where none exists. */
  priceStatus: MarketPriceStatus[];
  phase: Phase;
  live: LiveSnapshot | null;
  score: Goals | null;
  center: CenterState;
  /** SUPER_ADMIN, not previewing as a USER: player links and the advanced tab. */
  showAdmin: boolean;
  goTo: (tab: TabKey) => void;
}
