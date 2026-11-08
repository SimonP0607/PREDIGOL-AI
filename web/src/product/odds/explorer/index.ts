/**
 * The odds explorer (plan Cuotas, ola 3; UX-068), not wired yet. The route takes `parseExplorerSearch` as its search
 * validator, renders `OddsExplorer` with an `ExplorerData` built on the API hooks and writes `serializeExplorerState` back to
 * the URL on every `onStateChange`; it shows it only while `odds_explorer` (GET /auth/me) is on.
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
