/**
 * Cuotas as the explorer (plan Cuotas, UX-069), loaded only while `odds_explorer` is on: the route's search is the
 * explorer's state (`parseExplorerSearch`) and every choice writes it back (`serializeExplorerState`), the search box
 * replacing its history entry instead of adding one per pause.
 */
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useMemo } from "react";
import { API_EXPLORER_DATA } from "./explorer/apiData";
import {
  OddsExplorer,
  parseExplorerSearch,
  serializeExplorerState,
  type ExplorerData,
  type ExplorerState,
  type StateChange,
} from "./explorer";
import { validateOddsSearch } from "./oddsSearch";

/** A choice of the explorer: the page stays where it is, without the screens' cross-fade. */
const IN_PLACE = { resetScroll: false, viewTransition: false } as const;

export function ExplorerScreen({
  data = API_EXPLORER_DATA,
  guide = true,
  now,
}: {
  data?: ExplorerData;
  /** The screen's guide; off in the tests, which have no guides or session. */
  guide?: boolean;
  /** A fixed clock (tests). */
  now?: number;
}) {
  const search = useSearch({ strict: false }) as Record<string, unknown>;
  const navigate = useNavigate();
  const state = useMemo(() => parseExplorerSearch(search), [search]);
  const onStateChange = useCallback(
    (next: ExplorerState, how?: StateChange) => {
      void navigate({
        to: "/odds",
        search: validateOddsSearch(serializeExplorerState(next)),
        replace: how?.replace === true,
        ...IN_PLACE,
      });
    },
    [navigate],
  );
  return (
    <OddsExplorer
      data={data}
      state={state}
      onStateChange={onStateChange}
      guide={guide}
      {...(now !== undefined ? { now } : {})}
    />
  );
}
