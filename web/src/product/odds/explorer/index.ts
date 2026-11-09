/**
 * The odds explorer (plan Cuotas, ola 3; UX-068), wired in UX-069: the route `/odds` reads its search with
 * `validateOddsSearch` (../oddsSearch.ts) and, while `odds_explorer` (GET /auth/me) is on, renders `OddsExplorer` with the
 * data layer on the API (`API_EXPLORER_DATA`, ./apiData.ts), writing `serializeExplorerState` back to the URL on every
 * `onStateChange` (../ExplorerScreen.tsx).
 */
export { OddsExplorer, type OddsExplorerProps, type StateChange } from "./OddsExplorer";
export {
  DEFAULT_EXPLORER_STATE,
  parseExplorerSearch,
  serializeExplorerState,
  type ExplorerFilters,
  type ExplorerState,
  type ExplorerWindow,
} from "./state";
export type {
  BoardPages,
  BoardQuery,
  BoardSort,
  BookmakerRef,
  CompetitionBadge,
  ExplorerData,
  ExplorerFollow,
  FamiliesQuery,
  LiveOptions,
  Loadable,
  MatchOddsBook,
  MovementQuery,
  OddsBoardPage,
  OddsBoardRow,
  OddsBookLine,
  OddsBookMarket,
  OddsFamilies,
  OddsFamily,
  OddsHealth,
  OddsMarketInfo,
  OddsMovement,
  OddsMovementPoint,
  OddsMovementSeries,
  OddsSelectionPrice,
  TeamBadge,
} from "./model";
export type { TabKey } from "./tabs";
