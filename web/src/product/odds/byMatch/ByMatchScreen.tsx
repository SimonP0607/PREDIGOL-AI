/** Cuotas «Por partido» on the API (UX-141): the view by match over the explorer's own data layer. Its own chunk. */
import type { ReactNode } from "react";
import { API_EXPLORER_DATA } from "../explorer/apiData";
import { ByMatchView } from "./ByMatchView";

export function ByMatchScreen({ modeSwitch }: { modeSwitch?: ReactNode }) {
  return <ByMatchView data={API_EXPLORER_DATA} modeSwitch={modeSwitch} />;
}
