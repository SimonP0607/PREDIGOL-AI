/** What every row of the board shares: the market on show, the dictionaries, the clock and the last update's moves. */
import type { CompetitionBadge, ExplorerData, OddsMarketInfo } from "./model";
import type { Move } from "./rows";

export interface RowEnv {
  data: ExplorerData;
  info: OddsMarketInfo;
  period: string;
  /** The family the match's book is asked for («Comparar casas»). */
  family: string;
  bookmakers: ReadonlyMap<number, string>;
  competitions: ReadonlyMap<number, CompetitionBadge>;
  now: number;
  /** The prices that moved in the last update (their arrows) and the update's number (it replays the tint). */
  moves: ReadonlyMap<string, Move>;
  version: number;
  /** Out of the day groups (another order): the day goes with the time. */
  withDay: boolean;
}

/** Long markets (exact score, scorers) show this many selections, then «Ver todas» and a search. */
export const LONG_MARKET = 8;
